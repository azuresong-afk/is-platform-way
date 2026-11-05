"""Разделение обязанностей без обходов (шаг 5.8): временный пароль и пометка в аудите.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05 13:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Пароль задан администратором: до смены самим пользователем токен без ролей.
    op.add_column(
        "users",
        sa.Column("password_temporary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Действие, которым администратор мог бы обойти разделение обязанностей (фильтр журнала).
    # ADD COLUMN с постоянным значением по умолчанию не переписывает строки: триггер append-only не мешает.
    op.add_column("audit_log", sa.Column("sod", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(op.f("ix_audit_log_sod"), "audit_log", ["sod"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_log_sod"), table_name="audit_log")
    op.drop_column("audit_log", "sod")
    op.drop_column("users", "password_temporary")
