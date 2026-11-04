"""Одноразовый перенос пользователей, ролей и проектов «Сканера» в платформу.

Читает БД «Сканера» только на чтение (для PostgreSQL сессия открывается с
default_transaction_read_only). Схема «Сканера» в этом репозитории не описана
до столбцов, поэтому таблицы и столбцы находятся по распространённым именам;
любое имя можно задать явно (`--map users.username=login`).

Повторный запуск идемпотентен:
- пользователь ищется по имени входа (без учёта регистра); новый создаётся
  с хэшем пароля «Сканера» как есть (формат scrypt$N$r$p$salt$dk совпадает),
  у существующего меняются только роли продукта «Сканер», пароль и профиль
  не трогаются;
- проект ищется по связи (scanner, id engagement); найденный не меняется.

Права в «Сканере» глобальные (роль действует во всех проектах), поэтому
новые пользователи получают «все проекты», а существующим без этого флага
добавляется участие в перенесённых проектах — доступ не сужается.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import Session

from .. import audit
from ..models import Project, ProjectLink, ProjectMember, User, UserProductRole
from ..products import DEFAULT_MANIFESTS
from ..security.passwords import _parse

PRODUCT = "scanner"
SCANNER_ROLES = frozenset(DEFAULT_MANIFESTS[PRODUCT]["roles"])
ADDON_ROLES = ("cred_audit", "host_credentials")

# Имена-кандидаты: первое найденное в таблице побеждает.
CANDIDATES: dict[str, tuple[str, ...]] = {
    "users.table": ("users", "user", "accounts"),
    "users.id": ("id", "user_id"),
    "users.username": ("username", "login", "user_name"),
    "users.password": ("password_hash", "hashed_password", "password"),
    "users.display_name": ("display_name", "full_name", "fullname", "name"),
    "users.email": ("email", "mail"),
    "users.active": ("is_active", "active", "enabled"),
    "users.disabled": ("disabled", "is_disabled", "blocked", "is_blocked"),
    "users.roles": ("roles", "role"),
    "users.permissions": ("permissions", "extra_permissions", "grants"),
    "roles.table": ("user_roles", "user_role", "role_assignments", "user_permissions"),
    "roles.user_id": ("user_id",),
    "roles.role": ("role", "role_name", "name", "permission"),
    "engagements.table": ("engagements", "engagement", "projects"),
    "engagements.id": ("id",),
    "engagements.name": ("name", "title"),
    "engagements.client": ("client", "customer", "client_name"),
    "engagements.contract_ref": ("contract_ref", "contract", "contract_number"),
    "engagements.period_from": ("period_from", "starts_at", "start_date"),
    "engagements.period_to": ("period_to", "ends_at", "end_date"),
    "engagements.archived": ("archived", "is_archived"),
    "engagements.status": ("status",),
}


class ImportError_(Exception):
    """Ошибка конфигурации импорта (нет таблицы, нет обязательного столбца)."""


@dataclass
class Report:
    users_created: list[str] = field(default_factory=list)
    users_updated: list[str] = field(default_factory=list)
    users_unchanged: list[str] = field(default_factory=list)
    users_without_password: list[str] = field(default_factory=list)
    scanner_admins: list[str] = field(default_factory=list)
    projects_created: list[str] = field(default_factory=list)
    projects_existing: list[str] = field(default_factory=list)
    unknown_roles: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    mapping: dict[str, dict[str, str]] = field(default_factory=lambda: {"users": {}, "engagements": {}})
    columns: dict[str, str | None] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "users_created": len(self.users_created),
            "users_updated": len(self.users_updated),
            "users_unchanged": len(self.users_unchanged),
            "users_without_password": len(self.users_without_password),
            "projects_created": len(self.projects_created),
            "projects_existing": len(self.projects_existing),
        }


@dataclass
class SourceUser:
    source_id: str
    username: str
    display_name: str
    email: str | None
    password_hash: str | None
    is_active: bool
    roles: set[str]


@dataclass
class SourceEngagement:
    source_id: str
    raw_id: Any
    name: str
    client: str
    contract_ref: str
    period_from: date | None
    period_to: date | None
    archived: bool


# --- чтение источника ---------------------------------------------------------


def open_source(url: str) -> Engine:
    kwargs: dict[str, Any] = {}
    if url.startswith("postgresql"):
        kwargs["connect_args"] = {"options": "-c default_transaction_read_only=on"}
    return create_engine(url, **kwargs)


def _pick(
    table: Table | None, key: str, overrides: dict[str, str], *, exclude: Iterable[str] = ()
) -> str | None:
    if table is None:
        return None
    if key in overrides:
        name = overrides[key]
        if name not in table.c:
            raise ImportError_(f"В таблице {table.name} нет столбца {name} (--map {key}={name})")
        return name
    skip = set(exclude)
    for name in CANDIDATES[key]:
        if name in table.c and name not in skip:
            return name
    return None


def _table(
    meta: MetaData, conn: Connection, key: str, overrides: dict[str, str], schema: str | None
) -> Table | None:
    names = (overrides[key],) if key in overrides else CANDIDATES[key]
    for name in names:
        try:
            return Table(name, meta, autoload_with=conn, schema=schema)
        except NoSuchTableError:
            continue
    if key in overrides:
        raise ImportError_(f"Таблица {overrides[key]} не найдена (--map {key}=...)")
    return None


def _split_roles(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        items: Iterable[Any] = value
    elif isinstance(value, dict):
        items = [k for k, v in value.items() if v]
    else:
        text = str(value).strip()
        if text.startswith("[") or (text.startswith("{") and ":" in text):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if parsed is not None:
                return _split_roles(parsed)
        if text.startswith("{") and text.endswith("}"):  # массив PostgreSQL в текстовом виде
            text = text[1:-1]
        items = text.replace(";", ",").replace(" ", ",").split(",")
    return {str(i).strip().strip('"').lower() for i in items if str(i).strip().strip('"')}


def _to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def read_source(
    conn: Connection, overrides: dict[str, str], report: Report, schema: str | None = None
) -> tuple[list[SourceUser], list[SourceEngagement]]:
    meta = MetaData()
    users_t = _table(meta, conn, "users.table", overrides, schema)
    if users_t is None:
        raise ImportError_("Не найдена таблица пользователей «Сканера»; укажите --map users.table=<имя>")
    cols: dict[str, str | None] = {"users.table": users_t.name}
    for key in ("users.id", "users.username", "users.password"):
        cols[key] = _pick(users_t, key, overrides)
    if not cols["users.id"] or not cols["users.username"]:
        raise ImportError_(f"В таблице {users_t.name} не найдены id и имя входа; укажите --map")
    cols["users.display_name"] = _pick(
        users_t, "users.display_name", overrides, exclude=[cols["users.username"]]
    )
    for key in ("users.email", "users.active", "users.disabled", "users.roles", "users.permissions"):
        cols[key] = _pick(users_t, key, overrides)

    roles_t = _table(meta, conn, "roles.table", overrides, schema)
    if roles_t is not None:
        cols["roles.table"] = roles_t.name
        cols["roles.user_id"] = _pick(roles_t, "roles.user_id", overrides)
        cols["roles.role"] = _pick(roles_t, "roles.role", overrides)
        if not cols["roles.user_id"] or not cols["roles.role"]:
            report.warnings.append(f"Таблица {roles_t.name} пропущена: нет столбцов user_id/role")
            roles_t = None

    extra_roles: dict[str, set[str]] = {}
    if roles_t is not None:
        for row in conn.execute(select(roles_t.c[cols["roles.user_id"]], roles_t.c[cols["roles.role"]])):
            extra_roles.setdefault(str(row[0]), set()).update(_split_roles(row[1]))

    users: list[SourceUser] = []
    for row in conn.execute(select(users_t)).mappings():
        sid = str(row[cols["users.id"]])
        username = str(row[cols["users.username"]] or "").strip().lower()
        if not username:
            report.warnings.append(f"Пользователь id={sid} без имени входа пропущен")
            continue
        roles: set[str] = set()
        if cols["users.roles"]:
            roles |= _split_roles(row[cols["users.roles"]])
        if cols["users.permissions"]:
            roles |= _split_roles(row[cols["users.permissions"]])
        for addon in ADDON_ROLES:  # надбавки отдельными булевыми столбцами
            if addon in users_t.c and row[addon] is True:
                roles.add(addon)
        roles |= extra_roles.get(sid, set())
        active = True
        if cols["users.active"]:
            active = bool(row[cols["users.active"]])
        elif cols["users.disabled"]:
            active = not bool(row[cols["users.disabled"]])
        users.append(
            SourceUser(
                source_id=sid,
                username=username,
                display_name=str(row[cols["users.display_name"]] or "") if cols["users.display_name"] else "",
                email=(str(row[cols["users.email"]]) or None)
                if cols["users.email"] and row[cols["users.email"]]
                else None,
                password_hash=str(row[cols["users.password"]])
                if cols["users.password"] and row[cols["users.password"]]
                else None,
                is_active=active,
                roles=roles,
            )
        )

    engagements: list[SourceEngagement] = []
    eng_t = _table(meta, conn, "engagements.table", overrides, schema)
    if eng_t is None:
        report.warnings.append("Таблица проектов (engagement) не найдена — проекты не переносятся")
    else:
        cols["engagements.table"] = eng_t.name
        for key in CANDIDATES:
            if key.startswith("engagements.") and key != "engagements.table":
                cols[key] = _pick(eng_t, key, overrides)
        if not cols["engagements.id"] or not cols["engagements.name"]:
            raise ImportError_(f"В таблице {eng_t.name} не найдены id и name; укажите --map")
        for row in conn.execute(select(eng_t)).mappings():

            def val(key: str, row: Any = row) -> Any:
                return row[cols[key]] if cols.get(key) else None

            archived = bool(val("engagements.archived"))
            if not cols.get("engagements.archived") and val("engagements.status"):
                archived = str(val("engagements.status")).lower() in {"archived", "closed", "archive"}
            engagements.append(
                SourceEngagement(
                    source_id=str(val("engagements.id")),
                    raw_id=val("engagements.id"),
                    name=str(val("engagements.name") or "").strip() or f"Проект {val('engagements.id')}",
                    client=str(val("engagements.client") or ""),
                    contract_ref=str(val("engagements.contract_ref") or ""),
                    period_from=_to_date(val("engagements.period_from")),
                    period_to=_to_date(val("engagements.period_to")),
                    archived=archived,
                )
            )
    report.columns = cols
    return users, engagements


# --- запись в платформу -----------------------------------------------------


def _set_scanner_roles(db: Session, user: User, roles: set[str]) -> bool:
    current = {r.role for r in user.roles if r.product_id == PRODUCT}
    if current == roles:
        return False
    for r in list(user.roles):
        if r.product_id == PRODUCT and r.role not in roles:
            user.roles.remove(r)
    for role in sorted(roles - current):
        user.roles.append(UserProductRole(product_id=PRODUCT, role=role))
    return True


def apply_import(
    db: Session,
    users: list[SourceUser],
    engagements: list[SourceEngagement],
    report: Report,
    *,
    grant_platform_admin: bool = False,
) -> None:
    """Пишет в сессию платформы; коммит — на стороне вызывающего."""
    project_ids: list[uuid.UUID] = []
    for eng in engagements:
        link = db.scalar(
            select(ProjectLink).where(
                ProjectLink.product_id == PRODUCT, ProjectLink.external_id == eng.source_id
            )
        )
        if link is not None:
            report.projects_existing.append(eng.name)
            project_ids.append(link.project_id)
            report.mapping["engagements"][eng.source_id] = str(link.project_id)
            continue
        project = Project(
            name=eng.name[:300],
            client=eng.client[:300],
            contract_ref=eng.contract_ref[:200],
            period_from=eng.period_from,
            period_to=eng.period_to,
            status="archived" if eng.archived else "active",
        )
        db.add(project)
        db.flush()
        db.add(ProjectLink(project_id=project.id, product_id=PRODUCT, external_id=eng.source_id))
        project_ids.append(project.id)
        report.projects_created.append(eng.name)
        report.mapping["engagements"][eng.source_id] = str(project.id)

    for su in users:
        unknown = sorted(su.roles - SCANNER_ROLES)
        if unknown:
            report.unknown_roles[su.username] = unknown
        roles = su.roles & SCANNER_ROLES
        if "admin" in roles:
            report.scanner_admins.append(su.username)
        password_hash = su.password_hash if su.password_hash and _parse(su.password_hash) else None
        if su.password_hash and password_hash is None:
            report.warnings.append(f"{su.username}: хэш пароля не в формате scrypt — нужен новый пароль")

        user = db.scalar(select(User).where(func.lower(User.username) == su.username))
        if user is None:
            user = User(
                username=su.username,
                display_name=su.display_name[:200] or su.username,
                email=su.email,
                is_active=su.is_active,
                password_hash=password_hash,
                all_projects=bool(roles),
                is_platform_admin=grant_platform_admin and "admin" in roles,
            )
            db.add(user)
            db.flush()
            _set_scanner_roles(db, user, roles)
            report.users_created.append(su.username)
            if password_hash is None:
                report.users_without_password.append(su.username)
        else:
            changed = _set_scanner_roles(db, user, roles)
            if roles and not user.all_projects:
                have = set(
                    db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all()
                )
                for pid in project_ids:
                    if pid not in have:
                        db.add(ProjectMember(project_id=pid, user_id=user.id))
                        changed = True
            if grant_platform_admin and "admin" in roles and not user.is_platform_admin:
                user.is_platform_admin = True
                changed = True
            (report.users_updated if changed else report.users_unchanged).append(su.username)
        report.mapping["users"][su.source_id] = str(user.id)

    audit.record(
        db,
        action="import.scanner",
        actor_sub=None,
        actor_name="Импорт «Сканера»",
        object=PRODUCT,
        details=report.summary(),
    )


def scanner_sql(report: Report, engagements: list[SourceEngagement]) -> str:
    """SQL для БД «Сканера»: проставить engagement.platform_project_id (контракт v1.1, п. 3)."""
    table = report.columns.get("engagements.table") or "engagements"
    id_col = report.columns.get("engagements.id") or "id"
    lines = [
        "-- Привязка проектов «Сканера» к проектам платформы. Выполнить в БД «Сканера»",
        "-- после миграции, добавившей engagement.platform_project_id.",
        "BEGIN;",
    ]
    for eng in engagements:
        pid = report.mapping["engagements"].get(eng.source_id)
        if pid is None:
            continue
        ident = (
            str(eng.raw_id) if isinstance(eng.raw_id, int) else "'" + str(eng.raw_id).replace("'", "''") + "'"
        )
        # Имена — из схемы источника, значения экранированы; файл читает и выполняет оператор.
        stmt = f'UPDATE "{table}" SET platform_project_id = \'{pid}\' WHERE "{id_col}" = {ident};'  # noqa: S608
        lines.append(stmt)
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"
