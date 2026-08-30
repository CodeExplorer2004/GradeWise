"""移除与唯一索引重复的历史唯一约束。

Revision ID: 20260830_0003
Revises: 20260830_0002
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0003"
down_revision: str | None = "20260830_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_student_no_key")
    op.execute("ALTER TABLE teachers DROP CONSTRAINT IF EXISTS teachers_teacher_no_key")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_key")


def downgrade() -> None:
    op.execute("ALTER TABLE students ADD CONSTRAINT students_student_no_key UNIQUE (student_no)")
    op.execute("ALTER TABLE teachers ADD CONSTRAINT teachers_teacher_no_key UNIQUE (teacher_no)")
    op.execute("ALTER TABLE users ADD CONSTRAINT users_username_key UNIQUE (username)")
