"""Администрирование: команды (группы пользователей) с наборами ролей и проектов."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import Principal, client_ip, require_admin
from ..models import Group, GroupMember, GroupProductRole, GroupProject, Project, User
from .admin_users import RolesIn, forbid_self, validate_roles

router = APIRouter(prefix="/admin/groups", tags=["admin: groups"])


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    members: list[uuid.UUID]
    roles: dict[str, list[str]]
    projects: list[uuid.UUID]


class IdsIn(BaseModel):
    ids: list[uuid.UUID]


def group_out(db: Session, g: Group) -> GroupOut:
    roles: dict[str, list[str]] = {}
    for pid, role in db.execute(
        select(GroupProductRole.product_id, GroupProductRole.role).where(GroupProductRole.group_id == g.id)
    ):
        roles.setdefault(pid, []).append(role)
    return GroupOut(
        id=g.id,
        name=g.name,
        description=g.description,
        members=list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == g.id))),
        roles={k: sorted(v) for k, v in roles.items()},
        projects=list(db.scalars(select(GroupProject.project_id).where(GroupProject.group_id == g.id))),
    )


def _get(db: Session, gid: uuid.UUID) -> Group:
    g = db.get(Group, gid)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Команда не найдена")
    return g


def _is_member(db: Session, gid: uuid.UUID, uid: uuid.UUID) -> bool:
    return db.get(GroupMember, (gid, uid)) is not None


def _grants_something(db: Session, gid: uuid.UUID) -> bool:
    return bool(
        db.scalar(select(GroupProductRole.role).where(GroupProductRole.group_id == gid).limit(1))
        or db.scalar(select(GroupProject.project_id).where(GroupProject.group_id == gid).limit(1))
    )


def _audit(db, p: Principal, request: Request, action: str, g: Group, details: dict | None = None) -> None:
    audit.record(
        db,
        action=action,
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"group/{g.name}",
        ip=client_ip(request),
        details=details or {},
    )


@router.get("", response_model=list[GroupOut])
def list_groups(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return [group_out(db, g) for g in db.scalars(select(Group).order_by(Group.name))]


@router.post("", response_model=GroupOut, status_code=201)
def create_group(
    body: GroupIn, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    g = Group(name=body.name, description=body.description)
    db.add(g)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Команда с таким названием уже есть") from exc
    _audit(db, p, request, "group.create", g)
    db.commit()
    return group_out(db, g)


@router.patch("/{gid}", response_model=GroupOut)
def patch_group(
    gid: uuid.UUID,
    body: GroupIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = _get(db, gid)
    g.name, g.description = body.name, body.description
    _audit(db, p, request, "group.update", g)
    db.commit()
    return group_out(db, g)


@router.delete("/{gid}", status_code=204)
def delete_group(
    gid: uuid.UUID, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    g = _get(db, gid)
    _audit(db, p, request, "group.delete", g)
    db.delete(g)
    db.commit()
    return Response(status_code=204)


@router.put("/{gid}/members", response_model=GroupOut)
def set_members(
    gid: uuid.UUID,
    body: IdsIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = _get(db, gid)
    wanted = set(body.ids)
    current = set(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == gid)))
    # Вступить в команду, которая даёт роли или проекты, — то же, что выдать их себе.
    if p.user.id in wanted - current and _grants_something(db, gid):
        forbid_self(p, p.user.id, "состав команды с ролями")
    found = set(db.scalars(select(User.id).where(User.id.in_(wanted)))) if wanted else set()
    if found != wanted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Пользователь не найден")
    db.execute(delete(GroupMember).where(GroupMember.group_id == gid))
    db.add_all(GroupMember(group_id=gid, user_id=u) for u in wanted)
    _audit(
        db,
        p,
        request,
        "group.members",
        g,
        {
            "added": sorted(str(x) for x in wanted - current),
            "removed": sorted(str(x) for x in current - wanted),
        },
    )
    db.commit()
    return group_out(db, g)


@router.put("/{gid}/roles", response_model=GroupOut)
def set_roles(
    gid: uuid.UUID,
    body: RolesIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = _get(db, gid)
    if _is_member(db, gid, p.user.id):
        forbid_self(p, p.user.id, "роли команды, в которой вы состоите,")
    clean = validate_roles(db, body.products)
    for pid in body.products:
        db.execute(
            delete(GroupProductRole).where(
                GroupProductRole.group_id == gid, GroupProductRole.product_id == pid
            )
        )
        db.add_all(GroupProductRole(group_id=gid, product_id=pid, role=r) for r in clean.get(pid, []))
    _audit(db, p, request, "group.roles", g, {"after": clean})
    db.commit()
    return group_out(db, g)


@router.put("/{gid}/projects", response_model=GroupOut)
def set_projects(
    gid: uuid.UUID,
    body: IdsIn,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    g = _get(db, gid)
    if _is_member(db, gid, p.user.id):
        forbid_self(p, p.user.id, "проекты команды, в которой вы состоите,")
    wanted = set(body.ids)
    found = set(db.scalars(select(Project.id).where(Project.id.in_(wanted)))) if wanted else set()
    if found != wanted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Проект не найден")
    db.execute(delete(GroupProject).where(GroupProject.group_id == gid))
    db.add_all(GroupProject(group_id=gid, project_id=x) for x in wanted)
    _audit(db, p, request, "group.projects", g, {"projects": sorted(str(x) for x in wanted)})
    db.commit()
    return group_out(db, g)
