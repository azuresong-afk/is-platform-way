"""Тестовые векторы для интеграции продуктов (docs/integration/vectors/).

Векторы детерминированы: ключи Ed25519 выводятся из фиксированных строк, подпись Ed25519
детерминирована, поэтому повторная генерация даёт те же файлы байт в байт. Тест
tests/test_integration_vectors.py проверяет и это, и сами векторы кодом платформы.

Перегенерировать после осознанного изменения:

    cd api && python -m tests.integration_vectors
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

VECTORS_DIR = Path(__file__).resolve().parents[2] / "docs" / "integration" / "vectors"

# 2026-11-04T16:00:00Z и 2100-01-01T00:00:00Z: действующие векторы не протухают,
# а просроченный — заведомо в прошлом. Продукт проверяет exp, а не «TTL ровно 15 минут».
IAT = 1793808000
EXP_FAR = 4102444800

USER_SUB = "6f1d2c3b-4a59-4e6f-8a7b-9c0d1e2f3a4b"
SVC_SUB = "svc:0b5e7a2c-91d4-4c3f-a8e6-2f7b9d1c4e50"
PROJECT_A = "3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61"
PROJECT_B = "9a7c5e3b-1d2f-4b6a-8c0e-4f6a8b0c2d93"
PRODUCTS = ["scanner", "vm", "grc"]

# Секреты HMAC событий — только для векторов, в установках не использовать.
EVENTS_SECRETS = {
    "scanner": "test-scanner-events-secret",
    "vm": "test-vm-events-secret",
    "grc": "test-grc-events-secret",
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _key(label: str) -> tuple[Ed25519PrivateKey, bytes]:
    seed = hashlib.sha256(f"platform-integration-vectors/{label}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed), seed


def _public_jwk(priv: Ed25519PrivateKey, kid: str) -> dict:
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw), "kid": kid, "alg": "EdDSA", "use": "sig"}


KEY_ACTIVE, SEED_ACTIVE = _key("active")
KEY_NEXT, SEED_NEXT = _key("next")
KEY_FOREIGN, _ = _key("foreign")  # не опубликован в JWKS
KID_ACTIVE = "20261104-vec00001"
KID_NEXT = "20261104-vec00002"


def jwks() -> dict:
    return {"keys": [_public_jwk(KEY_ACTIVE, KID_ACTIVE), _public_jwk(KEY_NEXT, KID_NEXT)]}


def _encode(claims: dict, key=KEY_ACTIVE, kid: str | None = KID_ACTIVE, alg: str = "EdDSA") -> str:
    headers = {"typ": "JWT"}
    if kid is not None:
        headers["kid"] = kid
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


def _seg(obj: dict) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode())


def _jti(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012x}"


def _user_claims(**over) -> dict:
    claims = {
        "iss": "platform",
        "sub": USER_SUB,
        "typ": "user",
        # Платформы в aud нет (контракт v1.1, п. 2.6).
        "aud": PRODUCTS,
        "preferred_username": "ivanov",
        "name": "Иванов И. И.",
        "auth_source": "local",
        "products": {"scanner": ["operator", "cred_audit"], "vm": ["engineer"]},
        "projects": [PROJECT_A],
        "platform_admin": False,
        "iat": IAT,
        "exp": EXP_FAR,
        "jti": _jti(1),
    }
    claims.update(over)
    return {k: v for k, v in claims.items() if v is not None}


def _ok(product: str, roles: list[str], project: str | None = None, typ: str = "user") -> dict:
    check = {"product": product, "status": 200, "roles": roles, "typ": typ}
    if project:
        check["project"] = project
    return check


def _deny(product: str, status: int, detail: str, project: str | None = None) -> dict:
    check = {"product": product, "status": status, "detail": detail}
    if project:
        check["project"] = project
    return check


def _invalid_everywhere() -> list[dict]:
    return [_deny(p, 401, "invalid_token") for p in PRODUCTS]


def jwt_cases() -> list[dict]:
    """Токены и ожидаемый ответ продукта. Порядок проверок продукта — docs/integration/README.md, п. 2."""
    valid = _encode(_user_claims())
    head, body, sig = valid.split(".")
    tampered_body = _seg({**_user_claims(), "products": {"scanner": ["admin"], "vm": ["engineer"]}})
    unsigned_head = _seg({"alg": "none", "typ": "JWT", "kid": KID_ACTIVE})
    public_x = jwks()["keys"][0]["x"].encode()
    # Подмена алгоритма: HS256 с открытым ключом в роли секрета. PyJWT такое не подпишет,
    # поэтому собираем вручную.
    hs_head = _seg({"alg": "HS256", "typ": "JWT", "kid": KID_ACTIVE})
    hs_input = f"{hs_head}.{body}".encode()
    hs_sig = _b64url(hmac.new(public_x, hs_input, hashlib.sha256).digest())

    return [
        {
            "name": "user_valid",
            "description": "Пользователь: роли в scanner и vm, один проект. В grc ролей нет — 403, не 401.",
            "token": valid,
            "checks": [
                _ok("scanner", ["operator", "cred_audit"], PROJECT_A),
                _deny("scanner", 403, "no_project_access", PROJECT_B),
                _ok("vm", ["engineer"], PROJECT_A),
                _deny("grc", 403, "no_product_roles"),
            ],
        },
        {
            "name": "user_all_projects",
            "description": 'projects = ["*"] — доступ к любому проекту.',
            "token": _encode(
                _user_claims(projects=["*"], products={"grc": ["methodologist"]}, jti=_jti(0x02))
            ),
            "checks": [
                _ok("grc", ["methodologist"], PROJECT_A),
                _ok("grc", ["methodologist"], PROJECT_B),
                _deny("scanner", 403, "no_product_roles"),
                _deny("vm", 403, "no_product_roles"),
            ],
        },
        {
            "name": "user_empty_roles",
            "description": "Продукт есть в products, но список ролей пуст — то же, что отсутствие ролей.",
            "token": _encode(_user_claims(products={"vm": []}, jti=_jti(0x03))),
            "checks": [_deny(p, 403, "no_product_roles") for p in PRODUCTS],
        },
        {
            "name": "user_without_typ",
            "description": 'Токен в духе контракта v1: нет typ и auth_source — считать typ = "user".',
            "token": _encode(_user_claims(typ=None, auth_source=None, jti=_jti(0x04))),
            "checks": [
                _ok("scanner", ["operator", "cred_audit"], PROJECT_A),
                _ok("vm", ["engineer"]),
                _deny("grc", 403, "no_product_roles"),
            ],
        },
        {
            "name": "user_next_key",
            "description": "Подписан ключом next (второй ключ в JWKS) — выбор ключа по kid.",
            "token": _encode(_user_claims(jti=_jti(0x05)), KEY_NEXT, KID_NEXT),
            "checks": [
                _ok("scanner", ["operator", "cred_audit"]),
                _ok("vm", ["engineer"], PROJECT_A),
                _deny("grc", 403, "no_product_roles"),
            ],
        },
        {
            "name": "service_vm_to_scanner",
            "description": "Сервисный токен (п. 2.2): aud — только scanner, sub вида svc:*.",
            "token": _encode(
                {
                    "iss": "platform",
                    "sub": SVC_SUB,
                    "typ": "service",
                    "aud": ["scanner"],
                    "client_id": "vm-to-scanner",
                    "preferred_username": "svc:vm-to-scanner",
                    "name": "Сервис: Устранение → Сканер",
                    "auth_source": "local",
                    "products": {"scanner": ["operator", "host_credentials"]},
                    "projects": ["*"],
                    "iat": IAT,
                    "exp": EXP_FAR,
                    "jti": _jti(6),
                }
            ),
            "checks": [
                _ok("scanner", ["operator", "host_credentials"], PROJECT_B, typ="service"),
                _deny("vm", 401, "invalid_token"),
                _deny("grc", 401, "invalid_token"),
            ],
        },
        {
            "name": "expired",
            "description": "exp = iat + 900 в прошлом (больше допуска 60 с).",
            "token": _encode(_user_claims(exp=IAT + 900, jti=_jti(0x07))),
            "checks": _invalid_everywhere(),
        },
        {
            "name": "wrong_aud",
            "description": 'aud = ["platform"] (токен оболочки, п. 2.6): своего id в aud нет — 401.',
            "token": _encode(_user_claims(aud=["platform"], jti=_jti(0x08))),
            "checks": _invalid_everywhere(),
        },
        {
            "name": "wrong_iss",
            "description": 'iss не "platform".',
            "token": _encode(_user_claims(iss="scanner", jti=_jti(0x09))),
            "checks": _invalid_everywhere(),
        },
        {
            "name": "missing_exp",
            "description": "Нет exp — токен без срока не принимать.",
            "token": _encode(_user_claims(exp=None, jti=_jti(0x0A))),
            "checks": _invalid_everywhere(),
        },
        {
            "name": "bad_signature",
            "description": "Подписан чужим ключом с kid опубликованного ключа.",
            "token": _encode(_user_claims(jti=_jti(0x0B)), KEY_FOREIGN, KID_ACTIVE),
            "checks": _invalid_everywhere(),
        },
        {
            "name": "tampered_payload",
            "description": "Тело user_valid заменено (scanner: admin), подпись прежняя.",
            "token": f"{head}.{tampered_body}.{sig}",
            "checks": _invalid_everywhere(),
        },
        {
            "name": "unknown_kid",
            "description": "kid нет в JWKS: продукт перечитывает JWKS (не чаще раза в 30 с) и отвечает 401.",
            "token": _encode(_user_claims(jti=_jti(0x0C)), KEY_FOREIGN, "unknown-kid"),
            "checks": _invalid_everywhere(),
        },
        {
            "name": "no_kid",
            "description": "В заголовке нет kid (обязателен по п. 2.3).",
            "token": _encode(_user_claims(jti=_jti(0x0D)), kid=None),
            "checks": _invalid_everywhere(),
        },
        {
            "name": "alg_none",
            "description": "alg = none, подписи нет.",
            "token": f"{unsigned_head}.{body}.",
            "checks": _invalid_everywhere(),
        },
        {
            "name": "alg_hs256_confusion",
            "description": "alg = HS256, подписано HMAC с открытым ключом (x из JWKS) как секретом.",
            "token": f"{hs_head}.{body}.{hs_sig}",
            "checks": _invalid_everywhere(),
        },
    ]


# --- события ---------------------------------------------------------------------------------------

EVENT_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def sample_events() -> list[dict]:
    """По одному конверту на каждый тип из контракта v1.1, п. 6.2."""

    def env(n: int, type_: str, source: str, subject: str, data: dict, **extra) -> dict:
        return {
            "id": f"7c9e6679-7425-40de-944b-e07fc1f9{n:04x}",
            "type": type_,
            "source": source,
            "time": "2026-11-04T16:54:52Z",
            "project_id": PROJECT_A,
            "subject": subject,
            "data": data,
            **extra,
        }

    actor = {"sub": USER_SUB, "name": "Иванов И. И."}
    return [
        env(
            1,
            "scanner.run.finished",
            "scanner",
            "run/123",
            {
                "run_id": "123",
                "name": "Периметр, ноябрь",
                "status": "done",
                "started_at": "2026-11-04T15:10:00Z",
                "finished_at": "2026-11-04T16:54:50Z",
                "counts": {"critical": 2, "high": 7, "medium": 19, "low": 4, "info": 31},
                "initiated_by": actor,
            },
        ),
        env(
            2,
            "scanner.asset.upserted",
            "scanner",
            "asset/88",
            {
                "asset_id": "88",
                "address": "10.0.0.5",
                "hostname": "srv-db01",
                "os_family": "linux",
                "os": "Astra Linux 1.7",
                "owner": "Отдел ИТ",
                "criticality": "high",
                "tags": ["бд"],
                "groups": ["ЦОД-1"],
                "last_seen_at": "2026-11-04T16:50:00Z",
            },
        ),
        env(3, "scanner.asset.deleted", "scanner", "asset/88", {"asset_id": "88", "address": "10.0.0.5"}),
        env(
            4,
            "vm.ticket.created",
            "vm",
            "ticket/125",
            {
                "ticket_id": "125",
                "title": "Обновить OpenSSH на srv-db01",
                "severity": "critical",
                "assignee_sub": USER_SUB,
                "due_at": "2026-11-11T00:00:00Z",
                # dedup_key «Сканера»: sha256(host|port|vuln_id|module).
                "finding_keys": [hashlib.sha256(b"10.0.0.5|22|CVE-2024-6387|vuln").hexdigest()],
            },
            notify={
                "users": [USER_SUB],
                "title": "Вам назначена заявка №125",
                "link": f"/vm/tickets/125?project={PROJECT_A}",
            },
        ),
        env(
            5,
            "vm.ticket.status_changed",
            "vm",
            "ticket/125",
            {
                "ticket_id": "125",
                "from": "open",
                "to": "in_progress",
                "assignee_sub": USER_SUB,
            },
        ),
        env(
            6,
            "vm.remediation.verified",
            "vm",
            "ticket/125",
            {
                "ticket_id": "125",
                "run_id": "124",
                "result": "fixed",
            },
        ),
        env(
            7,
            "grc.assessment.updated",
            "grc",
            "system/7",
            {
                "system_id": "7",
                "title": "ГИС «Учёт»",
                "percent": 64,
                "status": "in_progress",
            },
        ),
        env(
            9,
            "grc.document.approval_requested",
            "grc",
            "document/31",
            {
                "document_id": "31",
                "title": "Акт классификации ГИС «Учёт»",
                "system_id": "7",
                "author_sub": USER_SUB,
            },
            notify={
                "users": ["c1b2a394-8576-4e3d-9c2b-1a0f9e8d7c6b"],
                "title": "Документ ждёт утверждения: Акт классификации",
                "link": f"/grc/documents/31?project={PROJECT_A}",
            },
        ),
        env(
            10,
            "platform.keys.rotated",
            "platform",
            f"key/{KID_NEXT}",
            # Срочная смена с отзывом: продукт сбрасывает кэш JWKS и не принимает revoked.
            {"kid": KID_NEXT, "revoked": [KID_ACTIVE]},
            project_id=None,
        ),
        env(
            11,
            "platform.project.updated",
            "platform",
            f"project/{PROJECT_A}",
            {"project_id": PROJECT_A, "name": "Аудит ООО «Ромашка», 2026", "status": "archived"},
        ),
        blocked_envelope(),
        env(
            8,
            "audit.recorded",
            "scanner",
            "audit/5012",
            {
                "time": "2026-11-04T16:54:51Z",
                "actor": actor,
                "action": "run.start",
                "object": "run/123",
                "result": "success",
                "ip": "10.0.0.17",
                "details": {"targets": 12},
            },
        ),
    ]


def hmac_cases() -> list[dict]:
    """Подпись X-Signature: HMAC-SHA256 от тела запроса байт в байт (п. 6.1, 6.4)."""
    event = sample_events()[0]
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    pretty = json.dumps(event, ensure_ascii=False, indent=2)
    vm_event = sample_events()[3]
    vm_body = json.dumps(vm_event, ensure_ascii=False, separators=(",", ":"))
    good = _sign(EVENTS_SECRETS["scanner"], body.encode())

    def case(name, description, direction, body_str, headers, secret_of, valid):
        return {
            "name": name,
            "description": description,
            "direction": direction,
            "secret": EVENTS_SECRETS[secret_of],
            "secret_of": secret_of,
            "body": body_str,
            "body_sha256": hashlib.sha256(body_str.encode()).hexdigest(),
            "headers": headers,
            "valid": valid,
        }

    def h(product: str, event_id: str, sig: str) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Platform-Product": product,
            "X-Event-Id": event_id,
            "X-Signature": sig,
        }

    sid = event["id"]
    return [
        case(
            "product_to_platform",
            "«Сканер» отправляет событие в POST /api/platform/events. Тело UTF-8, кириллица без \\u.",
            "scanner → platform",
            body,
            h("scanner", sid, good),
            "scanner",
            True,
        ),
        case(
            "product_to_platform_pretty",
            "То же событие с отступами: подпись считается от этих байтов, а не от «того же JSON».",
            "scanner → platform",
            pretty,
            h("scanner", sid, _sign(EVENTS_SECRETS["scanner"], pretty.encode())),
            "scanner",
            True,
        ),
        case(
            "reserialized_body",
            "Тело переформатировано после подписи (подпись от компактного варианта) — 401.",
            "scanner → platform",
            pretty,
            h("scanner", sid, good),
            "scanner",
            False,
        ),
        case(
            "wrong_secret",
            "Подписано секретом «Устранения», а X-Platform-Product: scanner — 401.",
            "scanner → platform",
            body,
            h("scanner", sid, _sign(EVENTS_SECRETS["vm"], body.encode())),
            "scanner",
            False,
        ),
        case(
            "missing_prefix",
            "Нет префикса sha256= — 401.",
            "scanner → platform",
            body,
            h("scanner", sid, good.removeprefix("sha256=")),
            "scanner",
            False,
        ),
        case(
            "platform_to_subscriber",
            "Платформа доставляет vm.ticket.created в webhook «Сканера» ; секрет — получателя.",
            "platform → scanner",
            vm_body,
            h("platform", vm_event["id"], _sign(EVENTS_SECRETS["scanner"], vm_body.encode())),
            "scanner",
            True,
        ),
    ]


# --- мгновенная блокировка (контракт v1.1, п. 6.5) ---------------------------------------------------

BLOCKED_AT = "2026-11-04T16:54:52Z"
BLOCKED_AT_TS = 1793811292
HOLD_UNTIL = "2026-11-04T17:10:52Z"  # blocked_at + 15 мин TTL + 60 с допуска
HOLD_UNTIL_TS = BLOCKED_AT_TS + 960
OTHER_SUB = "c1b2a394-8576-4e3d-9c2b-1a0f9e8d7c6b"


def blocked_envelope() -> dict:
    return {
        "id": "7c9e6679-7425-40de-944b-e07fc1f9000c",
        "type": "platform.user.blocked",
        "source": "platform",
        "time": BLOCKED_AT,
        "project_id": None,
        "subject": f"user/{USER_SUB}",
        "data": {"sub": USER_SUB, "blocked_at": BLOCKED_AT, "hold_until": HOLD_UNTIL},
    }


def blocked_cases() -> list[dict]:
    """Ответ продукта, получившего blocked_envelope(). now — часы продукта в момент запроса."""
    blocked = [_deny(p, 401, "user_blocked") for p in PRODUCTS]
    as_valid = [
        _ok("scanner", ["operator", "cred_audit"], PROJECT_A),
        _ok("vm", ["engineer"], PROJECT_A),
        _deny("grc", 403, "no_product_roles"),
    ]
    return [
        {
            "name": "issued_before_block",
            "description": "Токен выдан за 5 минут до блокировки, вкладка ещё открыта — 401 сразу, "
            "во всех продуктах (в grc ролей нет, но 401 раньше 403).",
            "now": BLOCKED_AT_TS + 3,
            "token": _encode(_user_claims(iat=BLOCKED_AT_TS - 300, jti=_jti(0x21))),
            "checks": blocked,
        },
        {
            "name": "issued_same_second",
            "description": "iat = blocked_at: граница включительно (платформа округляет blocked_at вверх).",
            "now": BLOCKED_AT_TS + 3,
            "token": _encode(_user_claims(iat=BLOCKED_AT_TS, jti=_jti(0x22))),
            "checks": blocked,
        },
        {
            "name": "issued_after_unblock",
            "description": "Пользователя разблокировали, он вошёл снова: iat > blocked_at — как обычно.",
            "now": BLOCKED_AT_TS + 120,
            "token": _encode(_user_claims(iat=BLOCKED_AT_TS + 60, jti=_jti(0x23))),
            "checks": as_valid,
        },
        {
            "name": "other_user",
            "description": "Другой sub с тем же iat — блокировка его не касается.",
            "now": BLOCKED_AT_TS + 3,
            "token": _encode(_user_claims(sub=OTHER_SUB, iat=BLOCKED_AT_TS - 300, jti=_jti(0x24))),
            "checks": as_valid,
        },
        {
            "name": "after_hold_until",
            "description": "Позже hold_until запись удалена. Настоящий токен, выданный до блокировки, "
            "к этому времени истёк; здесь exp далеко, чтобы показать: списка больше нет.",
            "now": HOLD_UNTIL_TS + 1,
            "token": _encode(_user_claims(iat=BLOCKED_AT_TS - 300, jti=_jti(0x25))),
            "checks": as_valid,
        },
    ]


# --- запись файлов ---------------------------------------------------------------------------------


def files() -> dict[str, str]:
    def dump(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"

    return {
        "jwks.json": dump(jwks()),
        "signing-keys.TEST-ONLY.json": dump(
            {
                "warning": "Только для тестов. Эти ключи опубликованы — не использовать в установках.",
                "keys": [
                    {"kid": KID_ACTIVE, "seed_b64url": _b64url(SEED_ACTIVE)},
                    {"kid": KID_NEXT, "seed_b64url": _b64url(SEED_NEXT)},
                ],
            }
        ),
        "jwt.json": dump(
            {
                "issuer": "platform",
                "leeway_seconds": 60,
                "jwks": "jwks.json",
                "projects": {"A": PROJECT_A, "B": PROJECT_B},
                "cases": jwt_cases(),
            }
        ),
        "events.json": dump({"envelopes": sample_events()}),
        "blocked.json": dump(
            {
                "rule": "sub из события и iat <= blocked_at — 401 user_blocked; запись живёт до hold_until",
                "jwks": "jwks.json",
                "event": blocked_envelope(),
                "cases": blocked_cases(),
            }
        ),
        "hmac.json": dump({"algorithm": "HMAC-SHA256", "header": "X-Signature", "cases": hmac_cases()}),
    }


def write(directory: Path = VECTORS_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files().items():
        (directory / name).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    write()
    print(f"векторы записаны в {VECTORS_DIR}")
