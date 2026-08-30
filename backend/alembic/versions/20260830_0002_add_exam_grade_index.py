"""补齐历史数据库的考试年级索引。

Revision ID: 20260830_0002
Revises: 20260830_0001
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0002"
down_revision: str | None = "20260830_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_exams_grade_level ON exams (grade_level)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_exams_grade_level")
