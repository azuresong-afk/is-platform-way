"""Сервисные учётные записи: выпуск секрета, проверка client credentials, утверждения токена."""

from __future__ import annotations

import secrets
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import products
from .db import utcnow
from .models import ServiceAccount
from .security import passwords

SECRET_PREFIX = "psk_"


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def set_secret(sa: ServiceAccount) -> str:
    """Выпускает новый секрет; старый перестаёт действовать сразу. Секрет возвращается один раз."""
    secret = new_secret()
    sa.secret_hash = passwords.hash_password(secret)
    sa.secret_rotated_at = utcnow()
    return secret


class ClientError(StrEnum):
    INVALID_CLIENT = "invalid_client"
    INACTIVE = "inactive_client"
    TARGET_UNAVAILABLE = "target_unavailable"


def authenticate(
    db: Session, client_id: str, client_secret: str
) -> tuple[ServiceAccount | None, ClientError | None]:
    sa = db.scalar(select(ServiceAccount).where(ServiceAccount.client_id == client_id))
    # verify_password выравнивает время и для несуществующей записи
    if not passwords.verify_password(client_secret, sa.secret_hash if sa else None) or sa is None:
        return sa, ClientError.INVALID_CLIENT
    if not sa.is_active:
        return sa, ClientError.INACTIVE
    if not products.product_roles(db, sa.target_product):
        return sa, ClientError.TARGET_UNAVAILABLE
    return sa, None


def effective_roles(db: Session, sa: ServiceAccount) -> list[str]:
    """Роли из записи, отфильтрованные по текущему манифесту целевого продукта."""
    allowed = products.product_roles(db, sa.target_product)
    return sorted(set(sa.roles or []) & set(allowed))


def claims(db: Session, sa: ServiceAccount) -> dict:
    """Утверждения сервисного токена (контракт v1.1, п. 2.2): aud — ровно один продукт."""
    return {
        "sub": f"svc:{sa.id}",
        "typ": "service",
        "aud": [sa.target_product],
        "client_id": sa.client_id,
        "preferred_username": f"svc:{sa.client_id}",
        "name": f"Сервис: {sa.name}",
        "auth_source": "local",
        "products": {sa.target_product: effective_roles(db, sa)},
        "projects": ["*"] if sa.all_projects else sorted(str(p) for p in sa.projects or []),
    }
