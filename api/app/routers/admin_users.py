"""Администрирование: пользователи и доступ.

Разделение обязанностей: администратор платформы управляет пользователями и доступом,
но не выдаёт себе роли продуктов, доступ к проектам и не включает себе «все проекты».
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import access, audit, products, sessions, users
from ..db import aware, get_db, utcnow
from ..deps import Principal, client_ip, require_admin
from ..models import GroupMember, Project, ProjectMember, User, UserProductRole
from ..pagination import Page
from ..security import passwords

router = APIRouter(prefix="/admin", tags=["admin: users"])

MIN_PASSWORD = 10
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    display_name: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_RE)
    password: str = Field(min_length=MIN_PASSWORD, max_length=1024)
    is_platform_admin: bool = False


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_RE)
    is_active: bool | None = None
    is_platform_admin: bool | None = None


class RolesIn(BaseModel):
    products: dict[str, list[str]]


class ProjectAccessItem(BaseModel):
    project_id: uuid.UUID
    project_role: str = Field(default="member", pattern="^(lead|member)$")


class ProjectsIn(BaseModel):
    all_projects: bool = False
    projects: list[ProjectAccessItem] = []


class PasswordIn(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD, max_length=1024)


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    is_active: bool
    locked: bool
    auth_source: str
    is_platform_admin: bool
    all_projects: bool
    last_login_at: str | None
    created_at: str
    roles: dict[str, list[str]]
    own_roles: dict[str, list[str]]
    projects: list[dict]
    groups: list[str]

    @field_validator("email", mode="before")
    @classmethod
    def _empty(cls, v):
        return v or None


def _own_roles(user: User) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in user.roles:
        out.setdefault(r.product_id, []).append(r.role)
    return {k: sorted(v) for k, v in out.items()}


def user_out(db: Session, user: User) -> UserOut:
    projects_rows = db.execute(
        select(ProjectMember.project_id, ProjectMember.project_role, Project.name)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.name)
    )
    group_ids = db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user.id))
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        is_active=user.is_active,
        locked=users.is_locked(user),
        auth_source=user.auth_source,
        is_platform_admin=user.is_platform_admin,
        all_projects=user.all_projects,
        last_login_at=aware(user.last_login_at).isoformat() if user.last_login_at else None,
        created_at=aware(user.created_at).isoformat(),
        roles=access.effective_roles(db, user),
        own_roles=_own_roles(user),
        projects=[
            {"project_id": str(pid), "project_role": role, "name": name} for pid, role, name in projects_rows
        ],
        groups=[str(g) for g in group_ids],
    )


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user


def forbid_self(p: Principal, user_id: uuid.UUID, what: str) -> None:
    if p.user.id == user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Разделение обязанностей: нельзя изменять {what} самому себе",
        )


def validate_roles(db: Session, roles: dict[str, list[str]]) -> dict[str, list[str]]:
    clean: dict[str, list[str]] = {}
    for pid, items in roles.items():
        allowed = products.product_roles(db, pid)
        if not allowed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Продукт {pid} не установлен")
        bad = sorted(set(items) - set(allowed))
        if bad:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Роли {', '.join(bad)} нет в манифесте продукта {pid}",
            )
        if items:
            clean[pid] = sorted(set(items))
    return clean


@router.get("/users", response_model=list[UserOut])
def list_users(
    response: Response,
    q: str | None = Query(None, max_length=100),
    active: bool | None = None,
    product: str | None = None,
    page: Page = Depends(),
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.username)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.username).like(like),
                func.lower(User.display_name).like(like),
                func.lower(func.coalesce(User.email, "")).like(like),
            )
        )
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    if product:
        stmt = stmt.where(
            User.id.in_(select(UserProductRole.user_id).where(UserProductRole.product_id == product))
        )
    return [user_out(db, u) for u in page.apply(db, stmt, response)]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    if users.get_by_username(db, body.username):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Пользователь с таким логином уже есть")
    user = users.create_user(
        db,
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        password=body.password,
        is_platform_admin=body.is_platform_admin,
    )
    audit.record(
        db,
        action="user.create",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"user/{user.username}",
        ip=client_ip(request),
        details={"is_platform_admin": body.is_platform_admin},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Пользователь с таким логином уже есть") from exc
    return user_out(db, user)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return user_out(db, _get_user(db, user_id))


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    changes = body.model_dump(exclude_unset=True)
    if "is_active" in changes or "is_platform_admin" in changes:
        forbid_self(p, user_id, "статус и права администратора")
    for field, value in changes.items():
        setattr(user, field, value)
    if changes.get("is_active") is False:
        sessions.revoke_user(db, user.id, "user_blocked")
    audit.record(
        db,
        action="user.update",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"user/{user.username}",
        ip=client_ip(request),
        details={k: v for k, v in changes.items()},
    )
    db.commit()
    return user_out(db, user)


@router.put("/users/{user_id}/roles", response_model=UserOut)
def set_roles(
    user_id: uuid.UUID,
    body: RolesIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Полностью заменяет собственные роли пользователя по перечисленным продуктам."""
    forbid_self(p, user_id, "роли продуктов")
    user = _get_user(db, user_id)
    clean = validate_roles(db, body.products)
    before = _own_roles(user)
    for pid in body.products:
        db.execute(
            delete(UserProductRole).where(
                UserProductRole.user_id == user.id, UserProductRole.product_id == pid
            )
        )
        for role in clean.get(pid, []):
            db.add(UserProductRole(user_id=user.id, product_id=pid, role=role))
    audit.record(
        db,
        action="user.roles",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"user/{user.username}",
        ip=client_ip(request),
        details={"before": {k: before.get(k, []) for k in body.products}, "after": clean},
    )
    db.commit()
    db.refresh(user)
    return user_out(db, user)


@router.put("/users/{user_id}/projects", response_model=UserOut)
def set_projects(
    user_id: uuid.UUID,
    body: ProjectsIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    forbid_self(p, user_id, "доступ к проектам")
    user = _get_user(db, user_id)
    ids = {item.project_id for item in body.projects}
    if ids:
        found = set(db.scalars(select(Project.id).where(Project.id.in_(ids))))
        if found != ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Проект не найден")
    user.all_projects = body.all_projects
    db.execute(delete(ProjectMember).where(ProjectMember.user_id == user.id))
    for item in body.projects:
        db.add(ProjectMember(project_id=item.project_id, user_id=user.id, project_role=item.project_role))
    audit.record(
        db,
        action="user.projects",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"user/{user.username}",
        ip=client_ip(request),
        details={"all_projects": body.all_projects, "projects": sorted(str(i) for i in ids)},
    )
    db.commit()
    return user_out(db, user)


@router.post("/users/{user_id}/unlock", response_model=UserOut)
def unlock(
    user_id: uuid.UUID, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    user = _get_user(db, user_id)
    user.locked_until = None
    user.failed_logins = 0
    audit.record(
        db,
        action="user.unlock",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"user/{user.username}",
        ip=client_ip(request),
    )
    db.commit()
    return user_out(db, user)


@router.post("/users/{user_id}/password", status_code=204)
def set_password(
    user_id: uuid.UUID,
    body: PasswordIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    user = _get_user(db, user_id)
    if user.auth_source != "local":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Пароль внешней учётной записи меняется в её источнике"
        )
    user.password_hash = passwords.hash_password(body.password)
    user.updated_at = utcnow()
    # Смена пароля закрывает все сессии пользователя.
    sessions.revoke_user(db, user.id, "password_changed")
    audit.record(
        db,
        action="user.password",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"user/{user.username}",
        ip=client_ip(request),
    )
    db.commit()
    return Response(status_code=204)
