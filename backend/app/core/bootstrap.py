from sqlalchemy import text

from app.core.database import engine
from app.core.models import Base

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

SCORE_INCREMENT_NORMALIZE = """
UPDATE exam_scores
SET score = ROUND(score * 2) / 2
WHERE score * 2 <> ROUND(score * 2)
"""

SCORE_INCREMENT_CONSTRAINT = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_exam_scores_half_point'
          AND conrelid = 'exam_scores'::regclass
    ) THEN
        ALTER TABLE exam_scores
        ADD CONSTRAINT ck_exam_scores_half_point
        CHECK (score * 2 = ROUND(score * 2));
    END IF;
END
$$
"""

ANALYSIS_DIMENSION_MIGRATIONS = (
    "ALTER TABLE classes ADD COLUMN IF NOT EXISTS cohort_year INTEGER",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS exam_type VARCHAR(30) NOT NULL DEFAULT '其他'",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS grade_level VARCHAR(40)",
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
    """,
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
    """,
    """
    UPDATE exams
    SET grade_level = CASE
        WHEN name LIKE '%初一%' THEN '初一'
        WHEN name LIKE '%初二%' THEN '初二'
        WHEN name LIKE '%初三%' THEN '初三'
        ELSE grade_level
    END
    WHERE grade_level IS NULL
    """,
)


async def initialize_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for statement in ANALYSIS_DIMENSION_MIGRATIONS:
            await connection.execute(text(statement))
        await connection.execute(text(SCORE_INCREMENT_NORMALIZE))
        await connection.execute(text(SCORE_INCREMENT_CONSTRAINT))
        await connection.execute(text(SCORE_FACTS_VIEW))
