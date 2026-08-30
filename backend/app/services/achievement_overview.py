from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import text

from app.core.database import ReadonlySessionLocal
from app.core.models import User, UserRole
from app.core.schemas import (
    AchievementExam,
    AchievementSubject,
    StudentAchievementOverview,
)
from app.services.sql_security import SQLSafetyGate, execute_scoped_query


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def _resolve_visible_student(user: User, student_name: str) -> dict[str, Any] | None:
    validation = SQLSafetyGate().validate(
        "SELECT DISTINCT student_id, student_name, class_id, class_name, grade_level, "
        f"subject_id FROM score_facts WHERE student_name = {_quoted(student_name)}"
    )
    visible = await execute_scoped_query(user, validation)
    student_ids = {int(row["student_id"]) for row in visible}
    if len(student_ids) != 1:
        return None
    first = visible[0]
    return {
        "student_id": student_ids.pop(),
        "student_name": str(first["student_name"]),
        "class_id": int(first["class_id"]),
        "class_name": str(first["class_name"]),
        "grade_level": str(first["grade_level"]),
        "subject_ids": sorted({int(row["subject_id"]) for row in visible}),
    }


def _in_clause(prefix: str, values: list[int]) -> tuple[str, dict[str, int]]:
    params = {f"{prefix}_{index}": value for index, value in enumerate(values)}
    return ", ".join(f":{name}" for name in params), params


def _filter_details_to_result_exams(
    details: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    dated_keys = {
        (str(row["exam_name"]), str(row["exam_date"]))
        for row in rows
        if row.get("exam_name") and row.get("exam_date")
    }
    if dated_keys:
        return [
            row
            for row in details
            if (str(row["exam_name"]), str(row["exam_date"])) in dated_keys
        ]
    exam_names = {str(row["exam_name"]) for row in rows if row.get("exam_name")}
    if exam_names:
        return [row for row in details if str(row["exam_name"]) in exam_names]
    return details


async def build_student_achievement_overview(
    user: User, rows: list[dict[str, Any]]
) -> StudentAchievementOverview | None:
    names = {
        str(row["student_name"]).strip()
        for row in rows
        if row.get("student_name") and str(row["student_name"]).strip()
    }
    if len(names) != 1 or len(rows) < 2:
        return None
    target = await _resolve_visible_student(user, names.pop())
    if not target or not target["subject_ids"]:
        return None

    subject_clause, subject_params = _in_clause("subject", target["subject_ids"])
    common_params = {
        "school_id": user.school_id,
        "student_id": target["student_id"],
        **subject_params,
    }
    detail_sql = text(
        "SELECT exam_id, exam_date, exam_name, subject_name, score, max_score, "
        "pass_score, passed FROM score_facts "
        "WHERE school_id = :school_id AND student_id = :student_id "
        f"AND subject_id IN ({subject_clause}) "
        "ORDER BY exam_date, subject_name"
    )

    async with ReadonlySessionLocal() as session:
        detail_result = await session.execute(detail_sql, common_params)
        details = [dict(row) for row in detail_result.mappings().all()]
        details = _filter_details_to_result_exams(details, rows)
        if not details:
            return None
        exam_ids = sorted({int(row["exam_id"]) for row in details})
        exam_clause, exam_params = _in_clause("exam", exam_ids)
        rank_sql = text(
            "WITH totals AS ("
            " SELECT student_id, class_id, grade_level, exam_id,"
            " ROUND(SUM(score)::numeric, 2) AS total_score,"
            " ROUND(SUM(max_score)::numeric, 2) AS total_max_score,"
            " SUM(score) / NULLIF(SUM(max_score), 0) AS score_rate"
            " FROM score_facts"
            " WHERE school_id = :school_id"
            f" AND subject_id IN ({subject_clause}) AND exam_id IN ({exam_clause})"
            " GROUP BY student_id, class_id, grade_level, exam_id"
            "), ranked AS ("
            " SELECT *,"
            " RANK() OVER (PARTITION BY exam_id, class_id ORDER BY score_rate DESC)"
            " AS class_rank,"
            " COUNT(*) OVER (PARTITION BY exam_id, class_id) AS class_size,"
            " RANK() OVER (PARTITION BY exam_id, grade_level ORDER BY score_rate DESC)"
            " AS grade_rank,"
            " COUNT(*) OVER (PARTITION BY exam_id, grade_level) AS grade_size"
            " FROM totals"
            ") SELECT * FROM ranked WHERE student_id = :student_id"
        )
        rank_result = await session.execute(
            rank_sql, {**common_params, **exam_params}
        )
        ranks = {
            int(row["exam_id"]): dict(row) for row in rank_result.mappings().all()
        }

    by_exam: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        by_exam[int(row["exam_id"])].append(row)

    exams: list[AchievementExam] = []
    for exam_rows in by_exam.values():
        first = exam_rows[0]
        rank = ranks.get(int(first["exam_id"]), {})
        subjects = [
            AchievementSubject(
                subject_name=str(row["subject_name"]),
                score=round(float(row["score"]), 2),
                max_score=round(float(row["max_score"]), 2),
                pass_score=round(float(row["pass_score"]), 2),
                passed=bool(row["passed"]),
            )
            for row in exam_rows
        ]
        is_subject_teacher = user.role == UserRole.SUBJECT_TEACHER
        exams.append(
            AchievementExam(
                exam_name=str(first["exam_name"]),
                exam_date=str(first["exam_date"]),
                subjects=subjects,
                total_score=round(sum(item.score for item in subjects), 2),
                total_max_score=round(sum(item.max_score for item in subjects), 2),
                passed_subjects=sum(item.passed for item in subjects),
                subject_count=len(subjects),
                class_rank=int(rank["class_rank"]) if rank else None,
                class_size=int(rank["class_size"]) if rank else None,
                grade_rank=(int(rank["grade_rank"]) if rank and not is_subject_teacher else None),
                grade_size=(int(rank["grade_size"]) if rank and not is_subject_teacher else None),
            )
        )

    return StudentAchievementOverview(
        student_name=target["student_name"],
        class_name=target["class_name"],
        grade_level=target["grade_level"],
        scope_label="授课科目" if user.role == UserRole.SUBJECT_TEACHER else "全部科目",
        exams=exams,
    )
