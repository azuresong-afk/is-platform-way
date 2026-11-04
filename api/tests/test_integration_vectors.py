"""Тестовые векторы docs/integration/vectors/ проверяются кодом платформы (шаг 2.6)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests import integration_vectors as iv


def _load(name: str):
    return json.loads((iv.VECTORS_DIR / name).read_text(encoding="utf-8"))


def test_files_match_generator():
    """Файлы в docs совпадают с генератором байт в байт (никто не правил их руками)."""
    for name, content in iv.files().items():
        assert (iv.VECTORS_DIR / name).read_text(encoding="utf-8") == content, (
            f"{name} устарел: cd api && python -m tests.integration_vectors"
        )


def test_jwks_shape_and_seeds():
    data = _load("jwks.json")
    seeds = {k["kid"]: k["seed_b64url"] for k in _load("signing-keys.TEST-ONLY.json")["keys"]}
    assert [k["kid"] for k in data["keys"]] == [iv.KID_ACTIVE, iv.KID_NEXT]
    for k in data["keys"]:
        assert {"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig"}.items() <= k.items()
        # Открытый ключ в JWKS соответствует опубликованному тестовому seed.
        seed = base64.urlsafe_b64decode(seeds[k["kid"]] + "==")
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        assert iv._public_jwk(priv, k["kid"]) == k


@pytest.fixture
def vector_keys(db):
    """Ключи из jwks.json — в таблице signing_keys, как будто их выпустила платформа."""
    from app.models import SigningKey

    statuses = {iv.KID_ACTIVE: "active", iv.KID_NEXT: "next"}
    for k in _load("jwks.json")["keys"]:
        db.add(SigningKey(kid=k["kid"], private_key_enc="v1:unused", public_jwk=k, status=statuses[k["kid"]]))
    db.commit()
    return db


def _product_answer(db, token: str, product: str, project: str | None) -> dict:
    """Решение продукта по контракту v1.1, п. 2.1–2.3, 3.1, на проверке подписи платформы."""
    from app.access import can_access_project
    from app.security import keys

    try:
        claims = keys.verify(db, token, audience=product)
    except jwt.PyJWTError:
        return {"status": 401, "detail": "invalid_token"}
    roles = list((claims.get("products") or {}).get(product) or [])
    if not roles:
        return {"status": 403, "detail": "no_product_roles"}
    if project and not can_access_project(claims.get("projects") or [], project):
        return {"status": 403, "detail": "no_project_access"}
    return {"status": 200, "roles": roles, "typ": claims.get("typ", "user")}


JWT_CASES = _load("jwt.json")["cases"]


@pytest.mark.parametrize("case", JWT_CASES, ids=[c["name"] for c in JWT_CASES])
def test_jwt_vectors(vector_keys, case):
    for check in case["checks"]:
        expected = {k: v for k, v in check.items() if k not in ("product", "project")}
        got = _product_answer(vector_keys, case["token"], check["product"], check.get("project"))
        assert got == expected, (case["name"], check)


def test_jwt_cases_cover_contract():
    names = {c["name"] for c in JWT_CASES}
    assert {
        "user_valid",
        "service_vm_to_scanner",
        "expired",
        "wrong_aud",
        "bad_signature",
        "unknown_kid",
        "alg_none",
        "alg_hs256_confusion",
    } <= names
    for c in JWT_CASES:
        # Каждый продукт находит в каждом случае свою проверку.
        assert {ch["product"] for ch in c["checks"]} == {"scanner", "vm", "grc"}, c["name"]
    statuses = {ch["status"] for c in JWT_CASES for ch in c["checks"]}
    assert statuses == {200, 401, 403}


def test_platform_tokens_follow_vector_shape(client, db):
    """Настоящий токен платформы содержит те же утверждения, что и векторы."""
    from tests.helpers import claims, login

    access, _ = login(client)
    got = claims(access)
    header = jwt.get_unverified_header(access)
    assert header["alg"] == "EdDSA" and header["kid"]
    sample = jwt.decode(JWT_CASES[0]["token"], options={"verify_signature": False})
    assert set(sample) <= set(got)


@pytest.mark.parametrize("case", _load("hmac.json")["cases"], ids=lambda c: c["name"])
def test_hmac_vectors(case):
    body = case["body"].encode()
    assert hashlib.sha256(body).hexdigest() == case["body_sha256"]
    expected = "sha256=" + hmac.new(case["secret"].encode(), body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, case["headers"]["X-Signature"]) is case["valid"]
    envelope = json.loads(body)
    assert case["headers"]["X-Event-Id"] == envelope["id"]
    if case["direction"].endswith("→ platform"):
        # п. 6.1: source совпадает с X-Platform-Product.
        assert envelope["source"] == case["headers"]["X-Platform-Product"]
    else:
        assert case["headers"]["X-Platform-Product"] == "platform"


# Обязательные поля data по контракту v1.1, п. 6.2.
DATA_FIELDS = {
    "scanner.run.finished": {
        "run_id", "name", "status", "started_at", "finished_at", "counts", "initiated_by",
    },
    "scanner.asset.upserted": {
        "asset_id", "address", "hostname", "os_family", "os", "owner",
        "criticality", "tags", "groups", "last_seen_at",
    },
    "scanner.asset.deleted": {"asset_id", "address"},
    "vm.ticket.created": {"ticket_id", "title", "severity", "assignee_sub", "due_at", "finding_keys"},
    "vm.ticket.status_changed": {"ticket_id", "from", "to", "assignee_sub"},
    "vm.remediation.verified": {"ticket_id", "run_id", "result"},
    "grc.document.approval_requested": {"document_id", "title", "system_id", "author_sub"},
    "grc.assessment.updated": {"system_id", "title", "percent", "status"},
    "audit.recorded": {"time", "actor", "action", "object", "result", "ip", "details"},
}  # fmt: skip


def test_event_envelopes():
    envelopes = _load("events.json")["envelopes"]
    assert {e["type"] for e in envelopes} == set(DATA_FIELDS)
    ids = set()
    for e in envelopes:
        assert {"id", "type", "source", "time", "project_id", "subject", "data"} <= set(e)
        assert e["type"].startswith(e["source"] + ".") or e["type"] == "audit.recorded"
        assert DATA_FIELDS[e["type"]] <= set(e["data"]), e["type"]
        if "notify" in e:
            assert e["notify"]["link"].startswith("/") and not e["notify"]["link"].startswith("//")
        ids.add(e["id"])
    assert len(ids) == len(envelopes)
