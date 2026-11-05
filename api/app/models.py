"""Модель данных платформы (см. docs/roadmap.md, раздел 2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, JsonType, utcnow


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # local | ldap (зарезервировано, LDAP не реализуется без запроса владельца)
    auth_source: Mapped[str] = mapped_column(String(20), default="local")
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Пароль задал администратор (docs/SECURITY.md, п. 6): токен без ролей, пока пользователь
    # не сменит его сам (POST /auth/password).
    password_temporary: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    all_projects: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    roles: Mapped[list[UserProductRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    manifest: Mapped[dict] = mapped_column(JsonType, default=dict)
    internal_url: Mapped[str] = mapped_column(String(300), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # ok | down | unknown
    health: Mapped[str] = mapped_column(String(20), default="unknown")
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manifest_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[str] = mapped_column(String(50), default="")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserProductRole(Base):
    __tablename__ = "user_product_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    role: Mapped[str] = mapped_column(String(50), primary_key=True)

    user: Mapped[User] = relationship(back_populates="roles")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class GroupProductRole(Base):
    __tablename__ = "group_product_roles"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    role: Mapped[str] = mapped_column(String(50), primary_key=True)


class GroupProject(Base):
    __tablename__ = "group_projects"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(300))
    client: Mapped[str] = mapped_column(String(300), default="")
    contract_ref: Mapped[str] = mapped_column(String(200), default="")
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    # active | archived
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # lead | member — информационно; права дают роли продуктов
    project_role: Mapped[str] = mapped_column(String(20), default="member")


class ProjectLink(Base):
    """Связь проекта платформы с записью продукта (например, engagement «Сканера»)."""

    __tablename__ = "project_links"
    __table_args__ = (UniqueConstraint("product_id", "external_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    family_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class SigningKey(Base):
    __tablename__ = "signing_keys"

    kid: Mapped[str] = mapped_column(String(64), primary_key=True)
    private_key_enc: Mapped[str] = mapped_column(Text)
    public_jwk: Mapped[dict] = mapped_column(JsonType)
    # next | active | retired | revoked (выведен при компрометации, в JWKS не публикуется)
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Сводный журнал аудита. Append-only: в PostgreSQL UPDATE/DELETE запрещены триггером."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    product: Mapped[str] = mapped_column(String(20), index=True)
    actor_sub: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    actor_name: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(100), index=True)
    object: Mapped[str] = mapped_column(String(300), default="")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    # success | failure | denied
    result: Mapped[str] = mapped_column(String(20), default="success")
    ip: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, unique=True)
    # Действие, которым администратор платформы мог бы обойти разделение обязанностей
    # (docs/SECURITY.md, п. 6): фильтр «Разделение обязанностей» на экране журнала.
    sod: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), index=True)


class ServiceAccount(Base):
    """Сервисная учётная запись: client credentials для вызовов продукт → продукт (контракт v1.1, п. 2.2)."""

    __tablename__ = "service_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    # scrypt, как у паролей; сам секрет показывается один раз при выпуске
    secret_hash: Mapped[str] = mapped_column(String(300))
    target_product: Mapped[str] = mapped_column(String(20))
    roles: Mapped[list] = mapped_column(JsonType, default=list)
    all_projects: Mapped[bool] = mapped_column(Boolean, default=True)
    projects: Mapped[list] = mapped_column(JsonType, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    secret_rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    """Принятое событие шины (контракт v1.1, п. 6). id из конверта — ключ идемпотентности."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    data: Mapped[dict] = mapped_column(JsonType, default=dict)
    notify: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Subscription(Base):
    """Подписка продукта на события: из манифеста (events.webhook, events.subscribe)."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(String(20), unique=True)
    # путь внутри API продукта (без /api/<id>)
    webhook_path: Mapped[str] = mapped_column(String(300), default="")
    types: Mapped[list] = mapped_column(JsonType, default=list)
    # выключает администратор; опрос манифеста флаг не трогает
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Delivery(Base):
    """Доставка события подписчику: повторы через 1, 5, 15, 60 мин, затем dead."""

    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("event_id", "subscription_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"))
    # pending | ok | failed (ждёт повтора) | dead (не доставлено)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    """Сводный реестр активов (контракт v1.1, п. 4). Ключ сопоставления — (project_id, address).

    sources — кто что знает об активе: [{product, external_id, seen_at, event_time}];
    manual_fields — поля, заданные вручную (правка или CSV): события их не перетирают.
    """

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("project_id", "address"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    address: Mapped[str] = mapped_column(String(255))
    hostname: Mapped[str] = mapped_column(String(255), default="")
    os_family: Mapped[str] = mapped_column(String(50), default="")
    os: Mapped[str] = mapped_column(String(200), default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    # low | medium | high | critical | "" (не задана)
    criticality: Mapped[str] = mapped_column(String(20), default="", index=True)
    tags: Mapped[list] = mapped_column(JsonType, default=list)
    groups: Mapped[list] = mapped_column(JsonType, default=list)
    sources: Mapped[list] = mapped_column(JsonType, default=list)
    manual_fields: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Notification(Base):
    """Уведомление пользователю из поля `notify` события (контракт v1.1, п. 6.3)."""

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    # продукт-источник события (любой id из установки или platform)
    product: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(100))
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
