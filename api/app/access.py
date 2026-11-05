"""Эффективные права пользователя: роли по продуктам и проекты (свои ∪ команд)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import products
from .models import GroupMember, GroupProductRole, GroupProject, ProjectMember, User, UserProductRole


def effective_roles(db: Session, user: User) -> dict[str, list[str]]:
    # Роль, исчезнувшая из манифеста продукта, в токен не попадает.
    # Порядок словаря — порядок вкладок.
    allowed = {p.id: set((p.manifest or {}).get("roles") or {}) for p in products.enabled_products(db)}
    out: dict[str, set[str]] = {}
    own = db.execute(
        select(UserProductRole.product_id, UserProductRole.role).where(UserProductRole.user_id == user.id)
    )
    via_groups = db.execute(
        select(GroupProductRole.product_id, GroupProductRole.role)
        .join(GroupMember, GroupMember.group_id == GroupProductRole.group_id)
        .where(GroupMember.user_id == user.id)
    )
    for pid, role in [*own, *via_groups]:
        if role in allowed.get(pid, ()):
            out.setdefault(pid, set()).add(role)
    return {pid: sorted(out[pid]) for pid in allowed if pid in out}


def effective_projects(db: Session, user: User) -> list[str]:
    """["*"] — все проекты; иначе uuid проектов (прямое участие и через команды)."""
    if user.all_projects:
        return ["*"]
    ids: set[uuid.UUID] = set(
        db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
    )
    ids |= set(
        db.scalars(
            select(GroupProject.project_id)
            .join(GroupMember, GroupMember.group_id == GroupProject.group_id)
            .where(GroupMember.user_id == user.id)
        )
    )
    return sorted(str(i) for i in ids)


def user_claims(db: Session, user: User) -> dict:
    """Утверждения access-токена пользователя (контракт v1, п. 2; v1.1, п. 2.1, 2.3, 2.6)."""
    return {
        "sub": str(user.id),
        "typ": "user",
        # Все продукты установки: отсутствие ролей продукт превращает в 403. Платформы в aud нет —
        # этот токен уходит в бэкенды продуктов и не должен открывать администрирование (п. 11 SECURITY.md).
        "aud": products.enabled_ids(db),
        "preferred_username": user.username,
        "name": user.display_name,
        "auth_source": user.auth_source,
        "products": effective_roles(db, user),
        "projects": effective_projects(db, user),
        "platform_admin": user.is_platform_admin,
    }


def platform_claims(user: User) -> dict:
    """Короткий токен оболочки для API платформы (контракт v1.1, п. 2.6): только в памяти вкладки."""
    return {
        "sub": str(user.id),
        "typ": "user",
        "aud": ["platform"],
        "preferred_username": user.username,
        "name": user.display_name,
        "auth_source": user.auth_source,
        "platform_admin": user.is_platform_admin,
    }


def can_access_project(projects_claim: list[str], project_id: uuid.UUID | str) -> bool:
    return "*" in projects_claim or str(project_id) in projects_claim
