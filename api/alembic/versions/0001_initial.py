"""Начальная схема: пользователи, продукты, роли, команды, проекты, refresh-токены, ключи, журнал аудита.

Revision ID: 0001
Revises:
Create Date: 2026-11-04 18:02:36.427113
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Журнал аудита — только добавление: триггер запрещает UPDATE и DELETE (только PostgreSQL).
AUDIT_APPEND_ONLY = """
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log: изменение и удаление записей запрещены';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column(
            "id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False
        ),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product", sa.String(length=20), nullable=False),
        sa.Column("actor_sub", sa.String(length=100), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("object", sa.String(length=300), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_actor_sub"), "audit_log", ["actor_sub"], unique=False)
    op.create_index(op.f("ix_audit_log_product"), "audit_log", ["product"], unique=False)
    op.create_index(op.f("ix_audit_log_project_id"), "audit_log", ["project_id"], unique=False)
    op.create_index(op.f("ix_audit_log_time"), "audit_log", ["time"], unique=False)
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column(
            "manifest",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("internal_url", sa.String(length=300), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("health", sa.String(length=20), nullable=False),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manifest_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("client", sa.String(length=300), nullable=False),
        sa.Column("contract_ref", sa.String(length=200), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_status"), "projects", ["status"], unique=False)
    op.create_table(
        "signing_keys",
        sa.Column("kid", sa.String(length=64), nullable=False),
        sa.Column("private_key_enc", sa.Text(), nullable=False),
        sa.Column(
            "public_jwk",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("kid"),
    )
    op.create_index(op.f("ix_signing_keys_status"), "signing_keys", ["status"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("auth_source", sa.String(length=20), nullable=False),
        sa.Column("password_hash", sa.String(length=300), nullable=True),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("all_projects", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_table(
        "group_product_roles",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "product_id", "role"),
    )
    op.create_table(
        "group_projects",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "project_id"),
    )
    op.create_table(
        "project_links",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "product_id"),
        sa.UniqueConstraint("product_id", "external_id"),
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_role", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("family_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "user_product_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "product_id", "role"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(AUDIT_APPEND_ONLY)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
        op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")
    op.drop_table("user_product_roles")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("project_members")
    op.drop_table("project_links")
    op.drop_table("group_projects")
    op.drop_table("group_product_roles")
    op.drop_table("group_members")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_signing_keys_status"), table_name="signing_keys")
    op.drop_table("signing_keys")
    op.drop_index(op.f("ix_projects_status"), table_name="projects")
    op.drop_table("projects")
    op.drop_table("products")
    op.drop_table("groups")
    op.drop_index(op.f("ix_audit_log_time"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_project_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_product"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor_sub"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
