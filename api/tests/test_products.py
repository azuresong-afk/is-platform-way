import httpx

from app import products
from app.builtin_manifests import BUILTIN_MANIFESTS
from app.models import Product
from tests.helpers import bearer, login


def _mock_client(manifest: dict | None, health_status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/manifest":
            if manifest is None:
                raise httpx.ConnectError("нет связи", request=request)
            return httpx.Response(200, json=manifest)
        if request.url.path == "/health/ready":
            return httpx.Response(health_status, json={})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_only_configured_products_exist(db):
    assert products.enabled_ids(db) == ["scanner", "vm"]  # grc не задан в окружении
    grc = db.get(Product, "grc")
    assert grc is None


def test_refresh_reads_manifest_and_health(db):
    prod = db.get(Product, "vm")
    manifest = {**BUILTIN_MANIFESTS["vm"], "version": "1.2.3", "title": "Устранение"}
    products.refresh_product(db, prod, _mock_client(manifest))
    assert prod.health == "ok" and prod.version == "1.2.3" and prod.manifest_fetched_at


def test_down_product_keeps_previous_manifest(db):
    prod = db.get(Product, "scanner")
    products.refresh_product(db, prod, _mock_client(None, 503))
    assert prod.health == "down"
    assert prod.manifest["roles"]["operator"] == "Оператор"
    assert "манифест" in prod.last_error


def test_foreign_manifest_rejected(db):
    prod = db.get(Product, "scanner")
    products.refresh_product(db, prod, _mock_client({"id": "vm", "roles": {}}))
    assert prod.manifest["id"] == "scanner"
    assert prod.last_error == "манифест не соответствует контракту"


def test_user_sees_only_tabs_with_roles(client):
    h = bearer(login(client)[0])
    u = client.post("/admin/users", json={"username": "op", "password": "long-password-1"}, headers=h).json()
    client.put(f"/admin/users/{u['id']}/roles", json={"products": {"vm": ["viewer"]}}, headers=h)
    uh = bearer(login(client, "op", "long-password-1")[0])
    tabs = client.get("/products", headers=uh).json()
    assert [t["id"] for t in tabs] == ["vm"]
    assert tabs[0]["my_roles"] == ["viewer"] and "internal_url" not in tabs[0]
    # Администратор без рабочих ролей не видит вкладок продуктов, но видит их в администрировании.
    assert client.get("/products", headers=h).json() == []
    admin_view = client.get("/admin/products", headers=h).json()
    assert [p["id"] for p in admin_view] == ["scanner", "vm"]
    assert admin_view[0]["manifest_source"] == "default"


def test_role_removed_from_manifest_is_dropped(client, db):
    from app import access, users
    from app.models import UserProductRole

    u = users.create_user(db, username="x", password="long-password-1")
    db.add(UserProductRole(user_id=u.id, product_id="vm", role="custom_commands"))
    db.commit()
    assert access.effective_roles(db, u) == {"vm": ["custom_commands"]}
    prod = db.get(Product, "vm")
    m = dict(BUILTIN_MANIFESTS["vm"])
    m["roles"] = {k: v for k, v in m["roles"].items() if k != "custom_commands"}
    products.refresh_product(db, prod, _mock_client(m))
    assert access.effective_roles(db, u) == {}
