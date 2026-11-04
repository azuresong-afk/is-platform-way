"""Проекты (= договоры на работы): справочник, участники, архивирование (контракт v1, п. 3)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .. import access, audit, events
from ..db import aware, get_db, utcnow
from ..deps import Principal, client_ip, current_principal, require_admin
from ..models import Project, ProjectMember, User
from ..pagination import Page
from .admin_users import forbid_self

router = APIRouter(tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    client: str = Field(default="", max_length=300)
    contract_ref: str = Field(default="", max_length=200)
    period_from: date | None = None
    period_to: date | None = None

    @model_validator(mode="after")
    def _period(self):
        if self.period_from and self.period_to and self.period_from > self.period_to:
            raise ValueError("Начало периода позже окончания")
        return self


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    client: str | None = Field(default=None, max_length=300)
    contract_ref: str | None = Field(default=None, max_length=200)
    period_from: date | None = None
    period_to: date | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    client: str
    contract_ref: str
    period_from: date | None
    period_to: date | None
    status: str
    created_at: str
    archived_at: str | None


class MemberIn(BaseModel):
    user_id: uuid.UUID
    project_role: str = Field(default="member", pattern="^(lead|member)$")


class MemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str
    project_role: str


def project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        client=p.client,
        contract_ref=p.contract_ref,
        period_from=p.period_from,
        period_to=p.period_to,
        status=p.status,
        created_at=aware(p.created_at).isoformat(),
        archived_at=aware(p.archived_at).isoformat() if p.archived_at else None,
    )


def _filtered(stmt, q: str | None, status_: str | None):
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Project.name).like(like),
                func.lower(Project.client).like(like),
                func.lower(Project.contract_ref).like(like),
            )
        )
    if status_:
        stmt = stmt.where(Project.status == status_)
    return stmt


def _get(db: Session, project_id: uuid.UUID) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return p


# --- для всех пользователей: только доступные проекты ---


@router.get("/projects", response_model=list[ProjectOut])
def my_projects(
    response: Response,
    q: str | None = Query(None, max_length=100),
    status_: str | None = Query(None, alias="status", pattern="^(active|archived)$"),
    page: Page = Depends(),
    p: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    stmt = _filtered(select(Project).order_by(Project.status, Project.name), q, status_)
    allowed = access.effective_projects(db, p.user)
    if "*" not in allowed:
        stmt = stmt.where(Project.id.in_([uuid.UUID(x) for x in allowed]))
    return [project_out(x) for x in page.apply(db, stmt, response)]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    if not (
        p.user.is_platform_admin
        or access.can_access_project(access.effective_projects(db, p.user), project_id)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="no_project_access")
    return project_out(_get(db, project_id))


# --- администрирование ---


@router.get("/admin/projects", response_model=list[ProjectOut])
def admin_projects(
    response: Response,
    q: str | None = Query(None, max_length=100),
    status_: str | None = Query(None, alias="status", pattern="^(active|archived)$"),
    page: Page = Depends(),
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = _filtered(select(Project).order_by(Project.status, Project.name), q, status_)
    return [project_out(x) for x in page.apply(db, stmt, response)]


def _publish(db: Session, proj: Project) -> None:
    events.publish(
        db,
        "platform.project.updated",
        {"project_id": str(proj.id), "name": proj.name, "status": proj.status},
        project_id=proj.id,
        subject=f"project/{proj.id}",
    )


@router.post("/admin/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectIn, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    proj = Project(**body.model_dump(), created_by=p.user.id)
    db.add(proj)
    db.flush()
    audit.record(
        db,
        action="project.create",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"project/{proj.id}",
        project_id=proj.id,
        ip=client_ip(request),
        details={"name": proj.name},
    )
    _publish(db, proj)
    db.commit()
    return project_out(proj)


@router.patch("/admin/projects/{project_id}", response_model=ProjectOut)
def patch_project(
    project_id: uuid.UUID,
    body: ProjectPatch,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    proj = _get(db, project_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(proj, k, v)
    if proj.period_from and proj.period_to and proj.period_from > proj.period_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Начало периода позже окончания")
    audit.record(
        db,
        action="project.update",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"project/{proj.id}",
        project_id=proj.id,
        ip=client_ip(request),
        details={k: str(v) for k, v in changes.items()},
    )
    _publish(db, proj)
    db.commit()
    return project_out(proj)


@router.post("/admin/projects/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    proj = _get(db, project_id)
    proj.status = "archived"
    proj.archived_at = utcnow()
    audit.record(
        db,
        action="project.archive",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"project/{proj.id}",
        project_id=proj.id,
        ip=client_ip(request),
    )
    _publish(db, proj)
    db.commit()
    return project_out(proj)


@router.post("/admin/projects/{project_id}/restore", response_model=ProjectOut)
def restore_project(
    project_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    proj = _get(db, project_id)
    proj.status = "active"
    proj.archived_at = None
    audit.record(
        db,
        action="project.restore",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"project/{proj.id}",
        project_id=proj.id,
        ip=client_ip(request),
    )
    _publish(db, proj)
    db.commit()
    return project_out(proj)


@router.get("/admin/projects/{project_id}/members", response_model=list[MemberOut])
def members(project_id: uuid.UUID, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    _get(db, project_id)
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.username)
    )
    return [
        MemberOut(user_id=u.id, username=u.username, display_name=u.display_name, project_role=m.project_role)
        for m, u in rows
    ]


@router.put("/admin/projects/{project_id}/members", response_model=list[MemberOut])
def set_members(
    project_id: uuid.UUID,
    body: list[MemberIn],
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _get(db, project_id)
    current = set(db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)))
    wanted = {m.user_id for m in body}
    # Себя добавить нельзя; если администратор уже участник (его добавил другой), оставляем как есть.
    if p.user.id in wanted ^ current:
        forbid_self(p, p.user.id, "доступ к проектам")
    found = set(db.scalars(select(User.id).where(User.id.in_(wanted)))) if wanted else set()
    if found != wanted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Пользователь не найден")
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    for m in body:
        db.add(ProjectMember(project_id=project_id, user_id=m.user_id, project_role=m.project_role))
    audit.record(
        db,
        action="project.members",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"project/{project_id}",
        project_id=project_id,
        ip=client_ip(request),
        details={
            "added": sorted(str(x) for x in wanted - current),
            "removed": sorted(str(x) for x in current - wanted),
        },
    )
    db.commit()
    return members(project_id, p, db)
