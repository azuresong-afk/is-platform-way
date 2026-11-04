"""Эталонная проверка токена (fakeproduct/auth.py) проходит векторы docs/integration/vectors/."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from fakeproduct.auth import JwksCache, require_project, verify_request

VECTORS = Path(__file__).resolve().parents[2] / "docs" / "integration" / "vectors"
JWKS = json.loads((VECTORS / "jwks.json").read_text(encoding="utf-8"))
JWT = json.loads((VECTORS / "jwt.json").read_text(encoding="utf-8"))
HMAC = json.loads((VECTORS / "hmac.json").read_text(encoding="utf-8"))


def _request(token: str) -> Request:
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


def _answer(token: str, product: str, project: str | None) -> dict:
    try:
        caller = verify_request(_request(token), product, JwksCache("x", fetch=lambda: JWKS))
        if project:
            require_project(caller, project)
    except HTTPException as exc:
        return {"status": exc.status_code, "detail": exc.detail}
    return {"status": 200, "roles": caller.roles, "typ": caller.typ}


@pytest.mark.parametrize("case", JWT["cases"], ids=[c["name"] for c in JWT["cases"]])
def test_jwt_vectors(case):
    for check in case["checks"]:
        expected = {k: v for k, v in check.items() if k not in ("product", "project")}
        assert _answer(case["token"], check["product"], check.get("project")) == expected, check


@pytest.mark.parametrize("case", HMAC["cases"], ids=[c["name"] for c in HMAC["cases"]])
def test_hmac_vectors(case):
    mac = hmac.new(case["secret"].encode(), case["body"].encode(), hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    assert hmac.compare_digest(expected, case["headers"]["X-Signature"]) is case["valid"]
