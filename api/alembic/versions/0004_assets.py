"""Сводный реестр активов.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04 23:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("os_family", sa.String(length=50), nullable=False),
        sa.Column("os", sa.String(length=200), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("criticality", sa.String(length=20), nullable=False),
        sa.Column("tags", JSON, nullable=False),
        sa.Column("groups", JSON, nullable=False),
        sa.Column("sources", JSON, nullable=False),
        sa.Column("manual_fields", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "address"),
    )
    op.create_index(op.f("ix_assets_project_id"), "assets", ["project_id"])
    op.create_index(op.f("ix_assets_criticality"), "assets", ["criticality"])
    op.create_index(op.f("ix_assets_updated_at"), "assets", ["updated_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_assets_updated_at"), table_name="assets")
    op.drop_index(op.f("ix_assets_criticality"), table_name="assets")
    op.drop_index(op.f("ix_assets_project_id"), table_name="assets")
    op.drop_table("assets")
