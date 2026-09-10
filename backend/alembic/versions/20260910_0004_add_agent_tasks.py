"""增加可持久化的 Agent 任务台账。

Revision ID: 20260910_0004
Revises: 20260830_0003
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_0004"
down_revision: str | None = "20260830_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("requested_scope", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("effective_scope", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("worker_thread_id", sa.String(length=64), nullable=True),
        sa.Column("worker_run_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column(
            "stage", sa.String(length=32), server_default="collecting_evidence", nullable=False
        ),
        sa.Column(
            "status_message", sa.String(length=255), server_default="正在准备任务", nullable=False
        ),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("result_prefix", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'error', 'cancelled', 'interrupted')",
            name="ck_agent_tasks_status",
        ),
        sa.CheckConstraint(
            "task_type IN ('batch_report', 'batch_warning')", name="ck_agent_tasks_type"
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_tasks_school_id", "agent_tasks", ["school_id"])
    op.create_index("ix_agent_tasks_status", "agent_tasks", ["status"])
    op.create_index("ix_agent_tasks_user_id", "agent_tasks", ["user_id"])
    op.create_index(
        "ix_agent_tasks_user_created", "agent_tasks", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("agent_tasks")
