"""Сводный реестр активов: чтение для продуктов и пользователей, правка и импорт — администратор."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import access, assets, audit, events
from ..db import get_db
from ..deps import Principal, client_ip, current_principal, require_admin
from ..models import Asset, Project
from ..pagination import Page

router = APIRouter(tags=["assets"])


class AssetOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    address: str
    hostname: str
    os_family: str
    os: str
    owner: str
    criticality: str | None
    tags: list[str]
    groups: list[str]
    sources: list[dict[str, Any]]
    manual_fields: list[str]
    created_at: str
    updated_at: str


class AssetPatch(BaseModel):
    """Поля из тела становятся ручными; reset — вернуть полям значения из продуктов."""

    hostname: str | None = Field(default=None, max_length=255)
    os_family: str | None = Field(default=None, max_length=50)
    os: str | None = Field(default=None, max_length=200)
    owner: str | None = Field(default=None, max_length=200)
    criticality: str | None = None
    tags: list[str] | None = Field(default=None, max_length=assets.MAX_LIST)
    groups: list[str] | None = Field(default=None, max_length=assets.MAX_LIST)
    reset: list[str] = Field(default_factory=list)

    @field_validator("reset")
    @classmethod
    def _reset(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if f not in assets.FIELDS]
        if bad:
            raise ValueError(f"Неизвестные поля: {', '.join(bad)}")
        return v

    def manual_values(self) -> dict[str, Any]:
        raw = self.model_dump(exclude_unset=True, exclude={"reset", "address"})
        try:
            return {k: assets.clean_value(k, v) for k, v in raw.items()}
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


class AssetIn(AssetPatch):
    address: str = Field(min_length=1, max_length=255)


class Facets(BaseModel):
    tags: list[str]
    groups: list[str]
    sources: list[str]
    os_families: list[str]


class ImportReport(BaseModel):
    dry_run: bool
    rows: int
    created: int
    updated: int
    unchanged: int
    error_count: int
    errors: list[dict[str, Any]]


def _project(db: Session, project_id: uuid.UUID, p: Principal) -> Project:
    proj = db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    # Читать реестр может участник проекта (продукты ходят с токеном пользователя) и администратор.
    if not (p.admin or access.can_access_project(access.effective_projects(db, p.user), proj.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="no_project_access")
    return proj


def _asset(db: Session, asset_id: uuid.UUID) -> Asset:
    a = db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Актив не найден")
    return a


def _writable(proj: Project) -> None:
    if proj.status == "archived":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="project_archived")


# --- чтение ---


@router.get("/projects/{project_id}/assets", response_model=list[AssetOut])
def list_assets(
    project_id: uuid.UUID,
    response: Response,
    q: str | None = Query(None, max_length=100, description="Адрес, имя хоста, владелец, ОС"),
    criticality: list[str] = Query(default=[], description="low|medium|high|critical|none; можно несколько"),
    os_family: str | None = Query(None, max_length=50),
    owner: str | None = Query(None, max_length=200),
    tag: str | None = Query(None, max_length=100),
    group: str | None = Query(None, max_length=100),
    source: str | None = Query(None, max_length=20, description="Продукт, который знает об активе"),
    manual: bool | None = Query(None, description="true — есть ручные поля"),
    updated_since: datetime | None = Query(None),
    sort: str = Query("address", pattern=r"^-?(address|hostname|owner|criticality|updated_at)$"),
    page: Page = Depends(),
    p: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    bad = [c for c in criticality if c not in (*assets.CRITICALITY, "none")]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="criticality: low|medium|high|critical|none"
        )
    _project(db, project_id, p)
    stmt = assets.query(
        db,
        project_id,
        q=q,
        criticality=criticality,
        os_family=os_family,
        owner=owner,
        tag=tag,
        group=group,
        source=source,
        manual=manual,
        updated_since=updated_since,
        sort=sort,
    )
    return [assets.asset_out(a) for a in page.apply(db, stmt, response)]


@router.get("/projects/{project_id}/assets/facets", response_model=Facets)
def asset_facets(
    project_id: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    _project(db, project_id, p)
    return assets.facets(db, project_id)


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    a = _asset(db, asset_id)
    _project(db, a.project_id, p)
    return assets.asset_out(a)


# --- изменение (администратор платформы) ---


def _publish(db: Session, a: Asset) -> None:
    events.publish(
        db, "platform.asset.upserted", assets.asset_out(a), project_id=a.project_id, subject=f"asset/{a.id}"
    )


@router.post("/projects/{project_id}/assets", response_model=AssetOut, status_code=201)
def create_asset(
    project_id: uuid.UUID,
    body: AssetIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    proj = _project(db, project_id, p)
    _writable(proj)
    try:
        address = assets.normalize_address(body.address)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if assets.find(db, project_id, address) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Актив с таким адресом уже есть в проекте")
    values = body.manual_values()
    a = Asset(project_id=project_id, address=address, tags=[], groups=[], sources=[], manual_fields=[])
    db.add(a)
    db.flush()
    assets.apply_manual(a, values)
    audit.record(
        db,
        action="asset.create",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"asset/{a.id}",
        project_id=project_id,
        ip=client_ip(request),
        details={"address": address, "fields": sorted(values)},
    )
    _publish(db, a)
    db.commit()
    return assets.asset_out(a)


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def patch_asset(
    asset_id: uuid.UUID,
    body: AssetPatch,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    a = _asset(db, asset_id)
    _writable(_project(db, a.project_id, p))
    changes = assets.apply_manual(a, body.manual_values(), body.reset)
    audit.record(
        db,
        action="asset.update",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"asset/{a.id}",
        project_id=a.project_id,
        ip=client_ip(request),
        details={"address": a.address, "changes": changes, "reset": body.reset},
    )
    _publish(db, a)
    db.commit()
    return assets.asset_out(a)


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(
    asset_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    a = _asset(db, asset_id)
    _writable(_project(db, a.project_id, p))
    audit.record(
        db,
        action="asset.delete",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"asset/{a.id}",
        project_id=a.project_id,
        ip=client_ip(request),
        details={"address": a.address, "sources": [s.get("product") for s in a.sources or []]},
    )
    events.publish(
        db,
        "platform.asset.deleted",
        {"asset_id": str(a.id), "address": a.address},
        project_id=a.project_id,
        subject=f"asset/{a.id}",
    )
    db.delete(a)
    db.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/assets/import", response_model=ImportReport)
async def import_assets(
    project_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Только проверить: ничего не сохранять"),
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    proj = _project(db, project_id, p)
    _writable(proj)
    raw = await file.read(assets.CSV_MAX_BYTES + 1)
    try:
        report = assets.import_csv(db, project_id, raw)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if dry_run:
        db.rollback()
        return {"dry_run": True, **report}
    filename = (file.filename or "")[:200]
    audit.record(
        db,
        action="asset.import",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"project/{project_id}",
        project_id=project_id,
        ip=client_ip(request),
        details={"file": filename, **{k: report[k] for k in ("rows", "created", "updated", "error_count")}},
    )
    events.publish(
        db,
        "platform.asset.imported",
        {"project_id": str(project_id), **{k: report[k] for k in ("created", "updated", "unchanged")}},
        project_id=project_id,
        subject=f"project/{project_id}",
    )
    db.commit()
    return {"dry_run": False, **report}
