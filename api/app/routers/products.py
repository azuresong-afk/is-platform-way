"""Продукты установки: вкладки для пользователя и администрирование (манифест, версия, состояние)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import access, audit, products
from ..db import aware, get_db
from ..deps import Principal, client_ip, current_principal, require_admin
from ..models import Product

router = APIRouter(tags=["products"])

# Поля манифеста, которые видит обычный пользователь (контракт v1, п. 5).
PUBLIC_FIELDS = (
    "id",
    "title",
    "subtitle",
    "icon",
    "base_path",
    "api_base",
    "version",
    "nav",
    "search_url",
    "summary_url",
    "health_url",
    "roles",
)


def _public(prod: Product) -> dict:
    m = prod.manifest or {}
    out = {k: m.get(k) for k in PUBLIC_FIELDS if k in m}
    out["id"] = prod.id
    out["title"] = m.get("title") or prod.title
    out["health"] = prod.health
    return out


@router.get("/products")
def my_products(p: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> list[dict]:
    """Продукты, на которые у пользователя есть роли: из них оболочка строит вкладки."""
    roles = access.effective_roles(db, p.user)
    out = []
    for prod in products.enabled_products(db):
        if roles.get(prod.id):
            item = _public(prod)
            item["my_roles"] = roles[prod.id]
            out.append(item)
    return out


def _admin_view(prod: Product) -> dict:
    return {
        **_public(prod),
        "manifest": prod.manifest,
        "internal_url": prod.internal_url,
        "enabled": prod.enabled,
        "version": prod.version or (prod.manifest or {}).get("version") or "",
        "health_checked_at": aware(prod.health_checked_at).isoformat() if prod.health_checked_at else None,
        "manifest_fetched_at": aware(prod.manifest_fetched_at).isoformat()
        if prod.manifest_fetched_at
        else None,
        "manifest_source": "product" if prod.manifest_fetched_at else "default",
        "last_error": prod.last_error,
    }


@router.get("/admin/products")
def admin_products(_: Principal = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return [_admin_view(p) for p in products.enabled_products(db)]


@router.post("/admin/products/{product_id}/refresh")
def refresh_product(
    product_id: str, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    prod = db.get(Product, product_id)
    if prod is None or not prod.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Продукт не установлен")
    products.refresh_product(db, prod)
    audit.record(
        db,
        action="product.refresh",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"product/{product_id}",
        ip=client_ip(request),
        details={"health": prod.health, "version": prod.version},
    )
    db.commit()
    return _admin_view(prod)
