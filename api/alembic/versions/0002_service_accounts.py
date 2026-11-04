"""Сервисные учётные записи (client credentials).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04 21:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "service_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("secret_hash", sa.String(length=300), nullable=False),
        sa.Column("target_product", sa.String(length=20), nullable=False),
        sa.Column("roles", JSON, nullable=False),
        sa.Column("all_projects", sa.Boolean(), nullable=False),
        sa.Column("projects", JSON, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secret_rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_service_accounts_client_id"), "service_accounts", ["client_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_service_accounts_client_id"), table_name="service_accounts")
    op.drop_table("service_accounts")
