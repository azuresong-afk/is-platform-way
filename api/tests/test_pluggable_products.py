"""Модульность (roadmap §1а, шаг М.1): новый продукт подключается только переменными окружения."""

import httpx
import pytest

from app import products
from app.config import Settings, parse_product_ids
from app.models import Product
from tests.helpers import bearer, claims, login, make_user

DEMO_MANIFEST = {
    "id": "demo",
    "title": "Демо",
    "subtitle": "проверка подключения",
    "icon": "box",
    "base_path": "/demo/",
    "api_base": "/api/demo/",
    "version": "0.1.0",
    "roles": {"admin": "Администратор", "viewer": "Наблюдатель"},
    "admin_roles": ["admin"],
    "nav": [],
    "search_url": "/api/demo/search",
    "health_url": "/api/demo/health/ready",
    "summary_url": "/api/demo/summary",
}


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("PLATFORM_PRODUCTS", "scanner, vm grc,demo")
    monkeypatch.setenv("DEMO_API_UPSTREAM", "http://demo.test/")
    monkeypatch.setenv("DEMO_WEB_UPSTREAM", "http://demo-web.test")
    monkeypatch.setenv("DEMO_EVENTS_SECRET", "demo-secret-0123456789")
    # Адрес есть, а в PLATFORM_PRODUCTS продукта нет — его нет и в кабинете.
    monkeypatch.setenv("OTHER_API_UPSTREAM", "http://other.test")


@pytest.fixture
def app(demo_env, app):  # noqa: F811 - переопределяем фикстуру conftest с окружением demo
    return app


def _manifest_client(manifest: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/manifest":
            return httpx.Response(200, json=manifest)
        return httpx.Response(200, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_product_ids():
    assert parse_product_ids("scanner,vm , grc\ndemo,vm") == ["scanner", "vm", "grc", "demo"]
    assert parse_product_ids("") == []
    for bad in ("Demo", "1abc", "a", "de-mo", "x" * 21):
        with pytest.raises(RuntimeError, match="недопустимый id"):
            parse_product_ids(bad)
    for reserved in ("platform", "admin", "assets"):
        with pytest.raises(RuntimeError, match="зарезервирован"):
            parse_product_ids(reserved)


def test_settings_read_product_vars_dynamically(demo_env):
    cfg = {p.id: p for p in Settings().products()}
    # grc в списке, но без адреса (conftest) — не подключён; other не в списке.
    assert list(cfg) == ["scanner", "vm", "demo"]
    demo = cfg["demo"]
    assert demo.api_upstream == "http://demo.test"
    assert demo.web_upstream == "http://demo-web.test"
    assert demo.events_secret == "demo-secret-0123456789"
    assert demo.position == 3


def test_default_product_list(monkeypatch):
    monkeypatch.delenv("PLATFORM_PRODUCTS", raising=False)
    assert Settings().product_ids() == ["scanner", "vm", "grc"]


def test_new_product_gets_placeholder_then_real_manifest(client, db):
    assert products.enabled_ids(db) == ["scanner", "vm", "demo"]
    prod = db.get(Product, "demo")
    assert prod.internal_url == "http://demo.test"
    # До ответа продукта — минимальная заглушка без ролей.
    assert prod.manifest["id"] == "demo" and prod.manifest["roles"] == {}
    assert prod.manifest["summary_url"] == "/api/demo/summary"
    products.refresh_product(db, prod, _manifest_client(DEMO_MANIFEST))
    assert prod.title == "Демо" and prod.manifest_fetched_at

    h = bearer(login(client)[0])
    u = make_user(client, h, "demouser")
    r = client.put(f"/admin/users/{u['id']}/roles", json={"products": {"demo": ["viewer"]}}, headers=h)
    assert r.status_code == 200, r.text
    token = login(client, "demouser", "long-password-1", platform=False)[0]
    assert claims(token)["aud"] == ["scanner", "vm", "demo"]
    assert claims(token)["products"] == {"demo": ["viewer"]}
    tabs = client.get("/products", headers=bearer(token)).json()
    assert [t["id"] for t in tabs] == ["demo"] and tabs[0]["title"] == "Демо"


def test_tab_order_from_manifest_or_env(client, db):
    assert [p.id for p in products.enabled_products(db)] == ["scanner", "vm", "demo"]
    demo = db.get(Product, "demo")
    products.refresh_product(db, demo, _manifest_client({**DEMO_MANIFEST, "order": -1}))
    assert [p.id for p in products.enabled_products(db)] == ["demo", "scanner", "vm"]
