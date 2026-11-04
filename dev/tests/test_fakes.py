"""Заглушки продуктов проверяют JWT платформы по контракту v1.1."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from fakeproduct.auth import JwksCache

DEV = Path(__file__).resolve().parents[1]
PROJECT = str(uuid.uuid4())
KEY = Ed25519PrivateKey.generate()
KID = "test-key-1"


def _jwks() -> dict:
    raw = KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": x, "kid": KID, "alg": "EdDSA", "use": "sig"}]}


def token(
    products: dict,
    projects=None,
    aud=("scanner", "vm", "grc", "demo", "platform"),
    exp_in=900,
    key=KEY,
    kid=KID,
):
    now = int(time.time())
    claims = {
        "iss": "platform",
        "sub": str(uuid.uuid4()),
        "aud": list(aud),
        "typ": "user",
        "preferred_username": "ivanov",
        "name": "Иванов И. И.",
        "products": products,
        "projects": projects if projects is not None else [PROJECT],
        "iat": now,
        "exp": now + exp_in,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid})


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"fake_{name}", DEV / f"fake-{name}" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.app.state.jwks = JwksCache("http://unused", fetch=_jwks)
    return TestClient(mod.app)


@pytest.fixture(params=["scanner", "vm", "grc", "demo"])
def product(request):
    return request.param, load(request.param)


def h(t):
    return {"authorization": f"Bearer {t}"}


def test_manifest_without_auth(product):
    pid, c = product
    m = c.get("/manifest").json()
    assert m["id"] == pid and m["base_path"] == f"/{pid}/" and m["summary_url"] == f"/api/{pid}/summary"
    assert c.get("/health/ready").status_code == 200


def test_product_page_without_auth(product):
    """Страница для e2e отдаётся без токена (вход проверяет её скрипт), без inline-скриптов под CSP."""
    pid, c = product
    r = c.get("/")
    assert r.status_code == 200 and f'data-product="{pid}"' in r.text
    assert '<script type="module" src="./app.js">' in r.text and "<script>" not in r.text
    assert c.get("/app.js").headers["content-type"].startswith("text/javascript")
    assert c.get("/app.css").headers["content-type"].startswith("text/css")


def test_no_token_401_no_roles_403(product):
    pid, c = product
    assert c.get(f"/summary?project={PROJECT}").status_code == 401
    other = "vm" if pid != "vm" else "scanner"
    r = c.get(f"/summary?project={PROJECT}", headers=h(token({other: ["viewer"]})))
    assert r.status_code == 403 and r.json()["detail"] == "no_product_roles"


def test_summary_shape(product):
    pid, c = product
    role = {"scanner": "auditor", "vm": "viewer", "grc": "viewer", "demo": "viewer"}[pid]
    r = c.get(f"/summary?project={PROJECT}", headers=h(token({pid: [role]})))
    assert r.status_code == 200
    body = r.json()
    assert body["product"] == pid and body["project_id"] == PROJECT and body["link"].startswith(f"/{pid}/")
    keys = {
        "scanner": {"open", "last_run"},
        "vm": {"open_tickets", "overdue_tickets", "verified_week", "next_window"},
        "grc": {"systems", "measures_percent", "documents"},
        # Новый продукт — общий формат сводки (контракт v1.1, п. 10.1).
        "demo": {"kpis", "note"},
    }[pid]
    assert set(body["data"]) == keys
    # Стабильно между запросами.
    assert (
        c.get(f"/summary?project={PROJECT}", headers=h(token({pid: [role]}))).json()["data"] == body["data"]
    )
    if "kpis" in body["data"]:
        kpis = body["data"]["kpis"]
        assert 1 <= len(kpis) <= 6 and all({"label", "value"} <= set(k) for k in kpis)


def test_project_access(product):
    pid, c = product
    t = token({pid: ["viewer"]}, projects=[str(uuid.uuid4())])
    assert c.get(f"/summary?project={PROJECT}", headers=h(t)).json()["detail"] == "no_project_access"
    assert (
        c.get(f"/summary?project={PROJECT}", headers=h(token({pid: ["viewer"]}, projects=["*"]))).status_code
        == 200
    )


def test_invalid_tokens(product):
    pid, c = product
    url = f"/summary?project={PROJECT}"
    bad = [
        token({pid: ["viewer"]}, exp_in=-120),
        token({pid: ["viewer"]}, aud=("platform",)),
        token({pid: ["viewer"]}, key=Ed25519PrivateKey.generate()),
        token({pid: ["viewer"]}, kid="unknown"),
        jwt.encode(
            {"sub": "x", "aud": pid, "iss": "platform", "exp": time.time() + 60, "iat": time.time()},
            "secret",
            algorithm="HS256",
            headers={"kid": KID},
        ),
    ]
    for t in bad:
        assert c.get(url, headers=h(t)).status_code == 401


def test_search(product):
    pid, c = product
    q = {"scanner": "openssh", "vm": "openssh", "grc": "УПД", "demo": "подключения"}[pid]
    r = c.get(f"/search?q={q}&project={PROJECT}", headers=h(token({pid: ["viewer"]})))
    items = r.json()["items"]
    assert items and all({"kind", "title", "subtitle", "link"} <= set(i) for i in items)
    assert all(i["link"].startswith(f"/{pid}/") and PROJECT in i["link"] for i in items)
    assert c.get(f"/search?q=&project={PROJECT}", headers=h(token({pid: ["viewer"]}))).json() == {"items": []}


def test_failure_mode(monkeypatch):
    c = load("vm")
    monkeypatch.setenv("FAKE_FAIL", "1")
    assert c.get(f"/summary?project={PROJECT}", headers=h(token({"vm": ["viewer"]}))).status_code == 500


def test_event_webhook_hmac(monkeypatch):
    c = load("vm")
    monkeypatch.setenv("PLATFORM_EVENTS_SECRET", "s3cret")
    ev = {
        "id": str(uuid.uuid4()),
        "type": "scanner.run.finished",
        "source": "scanner",
        "time": "2026-11-04T16:54:52Z",
        "project_id": PROJECT,
        "subject": "run/1",
        "data": {},
    }
    body = json.dumps(ev).encode()
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert c.post("/events/platform", content=body, headers={"x-signature": "sha256=00"}).status_code == 401
    assert c.post("/events/platform", content=body, headers={"x-signature": sig}).status_code == 202
    assert c.post("/events/platform", content=body, headers={"x-signature": sig}).json() == {
        "duplicate": True
    }
    assert len(c.get("/events/received", headers=h(token({"vm": ["viewer"]}))).json()) == 1


def test_jwks_refetch_on_unknown_kid():
    calls = []

    def fetch():
        calls.append(1)
        return _jwks()

    cache = JwksCache("x", fetch=fetch)
    assert cache.get(KID) is not None and len(calls) == 1
    assert cache.get(KID) is not None and len(calls) == 1  # из кэша
    assert cache.get("other") is None and len(calls) == 1  # не чаще раза в 30 с
    cache._fetched_at -= 31
    cache.get("other")
    assert len(calls) == 2


def test_keys_rotated_event_resets_jwks_cache():
    calls = []

    def fetch():
        calls.append(1)
        return _jwks()

    cache = JwksCache("x", fetch=fetch)
    assert cache.get(KID) is not None and len(calls) == 1
    # Новый ключ: перечитать JWKS сразу, не дожидаясь 30 с.
    cache.rotated("new-key", [])
    cache.get("new-key")
    assert len(calls) == 2
    # Известный ключ без отзыва — кэш не трогаем.
    cache.rotated(KID, [])
    cache.get(KID)
    assert len(calls) == 2
    # Отозванный kid не принимается, даже если JWKS его ещё отдаёт.
    cache.rotated("new-key", [KID])
    assert cache.get(KID) is None and len(calls) == 3


def test_keys_rotated_webhook(monkeypatch):
    c = load("vm")
    monkeypatch.setenv("PLATFORM_EVENTS_SECRET", "s3cret")
    viewer = token({"vm": ["viewer"]})
    assert c.get("/me", headers=h(viewer)).status_code == 200
    ev = {
        "id": str(uuid.uuid4()),
        "type": "platform.keys.rotated",
        "source": "platform",
        "time": "2026-11-04T16:54:52Z",
        "project_id": None,
        "subject": "keys",
        "data": {"kid": "next-key", "revoked": [KID]},
    }
    body = json.dumps(ev).encode()
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert c.post("/events/platform", content=body, headers={"x-signature": sig}).status_code == 202
    assert c.get("/me", headers=h(viewer)).status_code == 401
