"""Шина событий: события, подписки, доставки.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04 22:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("data", JSON, nullable=False),
        sa.Column("notify", JSON, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_type"), "events", ["type"])
    op.create_index(op.f("ix_events_source"), "events", ["source"])
    op.create_index(op.f("ix_events_project_id"), "events", ["project_id"])
    op.create_index(op.f("ix_events_received_at"), "events", ["received_at"])
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
        sa.Column("webhook_path", sa.String(length=300), nullable=False),
        sa.Column("types", JSON, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id"),
    )
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "subscription_id"),
    )
    op.create_index(op.f("ix_deliveries_event_id"), "deliveries", ["event_id"])
    op.create_index(op.f("ix_deliveries_status"), "deliveries", ["status"])
    op.create_index(op.f("ix_deliveries_next_attempt_at"), "deliveries", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_table("deliveries")
    op.drop_table("subscriptions")
    op.drop_index(op.f("ix_events_received_at"), table_name="events")
    op.drop_index(op.f("ix_events_project_id"), table_name="events")
    op.drop_index(op.f("ix_events_source"), table_name="events")
    op.drop_index(op.f("ix_events_type"), table_name="events")
    op.drop_table("events")
