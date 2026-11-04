"""Администрирование: сервисные учётные записи (контракт v1.1, п. 2.2).

Секрет показывается один раз — в ответе на создание и на перевыпуск; в списках,
журналах и аудите его нет.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, products, service_accounts
from ..db import aware, get_db
from ..deps import Principal, client_ip, require_admin
from ..models import Project, ServiceAccount

router = APIRouter(prefix="/admin/service-accounts", tags=["admin: service accounts"])

CLIENT_ID_RE = r"^[a-z0-9][a-z0-9._-]{1,98}[a-z0-9]$"


class ServiceAccountIn(BaseModel):
    client_id: str = Field(pattern=CLIENT_ID_RE)
    name: str = Field(min_length=1, max_length=200)
    target_product: str = Field(min_length=1, max_length=20)
    roles: list[str] = Field(min_length=1)
    all_projects: bool = True
    projects: list[uuid.UUID] = []


class ServiceAccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[str] | None = Field(default=None, min_length=1)
    all_projects: bool | None = None
    projects: list[uuid.UUID] | None = None
    is_active: bool | None = None


class ServiceAccountOut(BaseModel):
    id: uuid.UUID
    client_id: str
    name: str
    target_product: str
    roles: list[str]
    all_projects: bool
    projects: list[uuid.UUID]
    is_active: bool
    created_at: str
    secret_rotated_at: str
    last_used_at: str | None


class ServiceAccountWithSecret(ServiceAccountOut):
    client_secret: str


def _out(sa: ServiceAccount) -> dict:
    return ServiceAccountOut(
        id=sa.id,
        client_id=sa.client_id,
        name=sa.name,
        target_product=sa.target_product,
        roles=sorted(sa.roles or []),
        all_projects=sa.all_projects,
        projects=[uuid.UUID(str(p)) for p in sa.projects or []],
        is_active=sa.is_active,
        created_at=aware(sa.created_at).isoformat(),
        secret_rotated_at=aware(sa.secret_rotated_at).isoformat(),
        last_used_at=aware(sa.last_used_at).isoformat() if sa.last_used_at else None,
    ).model_dump(mode="json")


def _get(db: Session, sid: uuid.UUID) -> ServiceAccount:
    sa = db.get(ServiceAccount, sid)
    if sa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Сервисная учётная запись не найдена")
    return sa


def _check_roles(db: Session, product: str, roles: list[str]) -> list[str]:
    allowed = products.product_roles(db, product)
    if not allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Продукт {product} не установлен")
    bad = sorted(set(roles) - set(allowed))
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Роли {', '.join(bad)} нет в манифесте продукта {product}",
        )
    return sorted(set(roles))


def _check_projects(db: Session, all_projects: bool, ids: list[uuid.UUID]) -> list[str]:
    if all_projects:
        return []
    if not ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Укажите проекты или включите «все проекты»"
        )
    found = set(db.scalars(select(Project.id).where(Project.id.in_(ids))))
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Проекты не найдены: {', '.join(missing)}"
        )
    return sorted({str(i) for i in ids})


def _audit(
    db: Session, p: Principal, request: Request, action: str, sa: ServiceAccount, details: dict | None = None
):
    audit.record(
        db,
        action=action,
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"service_account/{sa.client_id}",
        ip=client_ip(request),
        details=details or {},
    )


@router.get("", response_model=list[ServiceAccountOut])
def list_accounts(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return [_out(sa) for sa in db.scalars(select(ServiceAccount).order_by(ServiceAccount.client_id))]


@router.post("", response_model=ServiceAccountWithSecret, status_code=201)
def create_account(
    body: ServiceAccountIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    roles = _check_roles(db, body.target_product, body.roles)
    projects = _check_projects(db, body.all_projects, body.projects)
    if db.scalar(select(ServiceAccount.id).where(ServiceAccount.client_id == body.client_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Запись с таким client_id уже есть")
    sa = ServiceAccount(
        client_id=body.client_id,
        name=body.name,
        target_product=body.target_product,
        roles=roles,
        all_projects=body.all_projects,
        projects=projects,
        created_by=p.user.id,
        secret_hash="",
    )
    secret = service_accounts.set_secret(sa)
    db.add(sa)
    _audit(
        db,
        p,
        request,
        "service_account.create",
        sa,
        {"target_product": sa.target_product, "roles": roles, "all_projects": sa.all_projects},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Запись с таким client_id уже есть") from exc
    return {**_out(sa), "client_secret": secret}


@router.patch("/{sid}", response_model=ServiceAccountOut)
def patch_account(
    sid: uuid.UUID,
    body: ServiceAccountPatch,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    sa = _get(db, sid)
    changes: dict = {}
    if body.name is not None:
        sa.name = body.name
        changes["name"] = body.name
    if body.roles is not None:
        sa.roles = _check_roles(db, sa.target_product, body.roles)
        changes["roles"] = sa.roles
    if body.all_projects is not None or body.projects is not None:
        all_projects = sa.all_projects if body.all_projects is None else body.all_projects
        ids = body.projects if body.projects is not None else [uuid.UUID(str(x)) for x in sa.projects or []]
        sa.projects = _check_projects(db, all_projects, ids)
        sa.all_projects = all_projects
        changes["all_projects"] = all_projects
        changes["projects"] = len(sa.projects)
    if body.is_active is not None:
        sa.is_active = body.is_active
        changes["is_active"] = body.is_active
    _audit(db, p, request, "service_account.update", sa, changes)
    db.commit()
    return _out(sa)


@router.post("/{sid}/secret", response_model=ServiceAccountWithSecret)
def rotate_secret(
    sid: uuid.UUID, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    sa = _get(db, sid)
    secret = service_accounts.set_secret(sa)
    _audit(db, p, request, "service_account.secret_rotate", sa)
    db.commit()
    return {**_out(sa), "client_secret": secret}


@router.delete("/{sid}", status_code=204)
def delete_account(
    sid: uuid.UUID, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    sa = _get(db, sid)
    _audit(db, p, request, "service_account.delete", sa, {"target_product": sa.target_product})
    db.delete(sa)
    db.commit()
    return Response(status_code=204)
