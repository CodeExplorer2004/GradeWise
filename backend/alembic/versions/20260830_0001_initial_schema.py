"""建立 GradeWise 初始数据库结构。

Revision ID: 20260830_0001
Revises:
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260830_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPECTED_LEGACY_TABLES = {
    "schools",
    "students",
    "teachers",
    "classes",
    "users",
    "subjects",
    "grade_subject_configs",
    "exams",
    "class_memberships",
    "teaching_assignments",
    "exam_scores",
    "conversations",
    "risk_snapshots",
    "import_batches",
}

SCORE_FACTS_VIEW = """
CREATE OR REPLACE VIEW score_facts WITH (security_invoker = true) AS
SELECT
    es.id AS score_id,
    s.school_id,
    s.id AS student_id,
    s.student_no,
    s.display_name AS student_name,
    c.id AS class_id,
    c.name AS class_name,
    c.grade_level,
    sub.id AS subject_id,
    sub.code AS subject_code,
    sub.name AS subject_name,
    e.id AS exam_id,
    e.name AS exam_name,
    e.academic_year,
    e.term,
    e.exam_date,
    es.score,
    COALESCE(gsc.max_score, sub.max_score) AS max_score,
    COALESCE(gsc.pass_score, sub.pass_score) AS pass_score,
    CASE WHEN es.score >= COALESCE(gsc.pass_score, sub.pass_score)
        THEN true ELSE false END AS passed,
    c.cohort_year,
    e.exam_type
FROM exam_scores es
JOIN students s ON s.id = es.student_id
JOIN classes c ON c.id = es.class_id
JOIN subjects sub ON sub.id = es.subject_id
JOIN exams e ON e.id = es.exam_id
LEFT JOIN grade_subject_configs gsc
    ON gsc.school_id = s.school_id
    AND gsc.academic_year = e.academic_year
    AND gsc.grade_level = c.grade_level
    AND gsc.subject_id = sub.id
"""


def _create_schema() -> None:
    op.create_table(
        "schools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("student_no", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("student_no"),
    )
    op.create_index("ix_students_school_id", "students", ["school_id"])
    op.create_index("ix_students_student_no", "students", ["student_no"], unique=True)
    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("teacher_no", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.UniqueConstraint("teacher_no"),
    )
    op.create_index("ix_teachers_school_id", "teachers", ["school_id"])
    op.create_index("ix_teachers_teacher_no", "teachers", ["teacher_no"], unique=True)
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("grade_level", sa.String(40), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.Column("cohort_year", sa.Integer(), nullable=True),
        sa.Column("head_teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=True),
        sa.UniqueConstraint("school_id", "name", "academic_year"),
    )
    op.create_index("ix_classes_school_id", "classes", ["school_id"])
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=True),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_school_id", "users", ["school_id"])
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("pass_score", sa.Float(), nullable=False),
        sa.UniqueConstraint("school_id", "code"),
    )
    op.create_index("ix_subjects_school_id", "subjects", ["school_id"])
    op.create_table(
        "grade_subject_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.Column("grade_level", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("pass_score", sa.Float(), nullable=False),
        sa.Column("included_in_total", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("max_score > 0", name="ck_grade_subject_max_positive"),
        sa.CheckConstraint(
            "pass_score >= 0 AND pass_score <= max_score",
            name="ck_grade_subject_pass_range",
        ),
        sa.UniqueConstraint("school_id", "academic_year", "grade_level", "subject_id"),
    )
    op.create_index(
        "ix_grade_subject_configs_academic_year", "grade_subject_configs", ["academic_year"]
    )
    op.create_index(
        "ix_grade_subject_configs_grade_level", "grade_subject_configs", ["grade_level"]
    )
    op.create_index("ix_grade_subject_configs_school_id", "grade_subject_configs", ["school_id"])
    op.create_index("ix_grade_subject_configs_subject_id", "grade_subject_configs", ["subject_id"])
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.Column("grade_level", sa.String(40), nullable=True),
        sa.Column("term", sa.String(20), nullable=False),
        sa.Column("exam_type", sa.String(30), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.UniqueConstraint("school_id", "name", "academic_year", "term"),
    )
    op.create_index("ix_exams_grade_level", "exams", ["grade_level"])
    op.create_index("ix_exams_school_id", "exams", ["school_id"])
    op.create_table(
        "class_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.UniqueConstraint("student_id", "class_id", "academic_year"),
    )
    op.create_index("ix_class_memberships_class_id", "class_memberships", ["class_id"])
    op.create_index("ix_class_memberships_student_id", "class_memberships", ["student_id"])
    op.create_table(
        "teaching_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.UniqueConstraint("teacher_id", "class_id", "subject_id", "academic_year"),
    )
    op.create_index("ix_teaching_assignments_class_id", "teaching_assignments", ["class_id"])
    op.create_index("ix_teaching_assignments_subject_id", "teaching_assignments", ["subject_id"])
    op.create_index("ix_teaching_assignments_teacher_id", "teaching_assignments", ["teacher_id"])
    op.create_table(
        "exam_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("score >= 0", name="ck_exam_scores_nonnegative"),
        sa.CheckConstraint("score * 2 = ROUND(score * 2)", name="ck_exam_scores_half_point"),
        sa.UniqueConstraint("student_id", "exam_id", "subject_id"),
    )
    op.create_index("ix_exam_scores_class_id", "exam_scores", ["class_id"])
    op.create_index("ix_exam_scores_exam_id", "exam_scores", ["exam_id"])
    op.create_index("ix_exam_scores_student_id", "exam_scores", ["student_id"])
    op.create_index("ix_exam_scores_subject_id", "exam_scores", ["subject_id"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("summary", sa.String(2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("latest_score", sa.Float(), nullable=False),
        sa.Column("trend", sa.Float(), nullable=False),
        sa.Column("volatility", sa.Float(), nullable=False),
        sa.Column("failure_ratio", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("student_id", "subject_id"),
    )
    op.create_index("ix_risk_snapshots_class_id", "risk_snapshots", ["class_id"])
    op.create_index("ix_risk_snapshots_risk_level", "risk_snapshots", ["risk_level"])
    op.create_index("ix_risk_snapshots_school_id", "risk_snapshots", ["school_id"])
    op.create_index("ix_risk_snapshots_student_id", "risk_snapshots", ["student_id"])
    op.create_index("ix_risk_snapshots_subject_id", "risk_snapshots", ["subject_id"])
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_import_batches_school_id", "import_batches", ["school_id"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])
    op.create_index("ix_import_batches_user_id", "import_batches", ["user_id"])


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names()) - {"alembic_version"}
    legacy_tables = existing & EXPECTED_LEGACY_TABLES
    if not legacy_tables:
        _create_schema()
    elif not EXPECTED_LEGACY_TABLES.issubset(existing):
        missing = ", ".join(sorted(EXPECTED_LEGACY_TABLES - existing))
        raise RuntimeError(f"旧数据库结构不完整，无法自动建立 Alembic 基线；缺少表：{missing}")

    op.execute("ALTER TABLE classes ADD COLUMN IF NOT EXISTS cohort_year INTEGER")
    op.execute(
        "ALTER TABLE exams ADD COLUMN IF NOT EXISTS exam_type VARCHAR(30) NOT NULL DEFAULT '其他'"
    )
    op.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS grade_level VARCHAR(40)")
    op.execute(
        """
        UPDATE classes
        SET cohort_year = CASE
            WHEN academic_year ~ '^\\d{4}-\\d{4}$' THEN
                split_part(academic_year, '-', 1)::integer - CASE grade_level
                    WHEN '初一' THEN 0 WHEN '初二' THEN 1 WHEN '初三' THEN 2
                    WHEN '高一' THEN 0 WHEN '高二' THEN 1 WHEN '高三' THEN 2
                    ELSE 0
                END
            ELSE NULL
        END
        WHERE cohort_year IS NULL
        """
    )
    op.execute(
        """
        UPDATE exams
        SET exam_type = CASE
            WHEN name LIKE '%期中%' THEN '期中'
            WHEN name LIKE '%期末%' THEN '期末'
            WHEN name LIKE '%一模%' THEN '一模'
            WHEN name LIKE '%二模%' THEN '二模'
            WHEN name LIKE '%三模%' THEN '三模'
            WHEN name LIKE '%模拟%' THEN '模拟考'
            ELSE '其他'
        END
        WHERE exam_type = '其他'
        """
    )
    op.execute(
        """
        UPDATE exam_scores
        SET score = ROUND(score * 2) / 2
        WHERE score * 2 <> ROUND(score * 2)
        """
    )
    op.execute(SCORE_FACTS_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS score_facts")
    for table in (
        "import_batches",
        "risk_snapshots",
        "conversations",
        "exam_scores",
        "teaching_assignments",
        "class_memberships",
        "exams",
        "grade_subject_configs",
        "subjects",
        "users",
        "classes",
        "teachers",
        "students",
        "schools",
    ):
        op.drop_table(table)
