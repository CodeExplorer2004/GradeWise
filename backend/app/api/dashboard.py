from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_analysis_scope, get_current_user
from app.core.database import get_db
from app.core.models import SchoolClass, Subject, TeachingAssignment, User, UserRole
from app.core.schemas import AnalysisFilterOptions, AnalysisScope, DashboardResponse
from app.services.analysis_scope import (
    collect_filter_options,
    filter_where,
    grade_sort_key,
    subject_sort_key,
    validate_scope,
)
from app.services.sql_security import SQLSafetyGate, execute_scoped_query

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _safe_query(user: User, sql: str) -> list[dict]:
    validation = SQLSafetyGate().validate(sql)
    if not validation.allowed:
        raise RuntimeError(f"Internal dashboard query rejected: {validation.violations}")
    return await execute_scoped_query(user, validation)


async def _scope_description(
    session: AsyncSession, user: User, filters: dict[str, str | int]
) -> str:
    if user.role == UserRole.STUDENT:
        base = "权限范围：仅本人全部科目"
    if user.role == UserRole.SUBJECT_TEACHER and user.teacher_id:
        rows = (
            await session.execute(
                select(SchoolClass.name, Subject.name)
                .select_from(TeachingAssignment)
                .join(SchoolClass, SchoolClass.id == TeachingAssignment.class_id)
                .join(Subject, Subject.id == TeachingAssignment.subject_id)
                .where(TeachingAssignment.teacher_id == user.teacher_id)
                .order_by(SchoolClass.name, Subject.name)
            )
        ).all()
        assignments = "、".join(f"{class_name}·{subject_name}" for class_name, subject_name in rows)
        base = f"权限范围：{assignments or '暂无授课安排'}"
    if user.role == UserRole.HEAD_TEACHER and user.teacher_id:
        class_names = list(
            (
                await session.scalars(
                    select(SchoolClass.name)
                    .where(SchoolClass.head_teacher_id == user.teacher_id)
                    .order_by(SchoolClass.name)
                )
            ).all()
        )
        base = f"权限范围：{'、'.join(class_names) or '暂无管理班级'}·全部科目"
    if user.role == UserRole.ACADEMIC_ADMIN:
        base = "权限范围：当前学校全部班级、全部科目"
    labels = [
        filters.get("academic_year"),
        filters.get("grade_level"),
        f"{filters['cohort_year']}届" if filters.get("cohort_year") else None,
        filters.get("term"),
        filters.get("exam_type"),
        filters.get("class_name"),
        filters.get("subject_name"),
        filters.get("exam_name"),
    ]
    selected = " · ".join(label for label in labels if label)
    return f"{base}{f'；当前筛选：{selected}' if selected else ''}"


@router.get("/options", response_model=AnalysisFilterOptions)
async def dashboard_options(
    scope: AnalysisScope = Depends(get_analysis_scope),
    current_user: User = Depends(get_current_user),
) -> AnalysisFilterOptions:
    return await collect_filter_options(current_user, scope)


@router.get("/summary", response_model=DashboardResponse)
async def dashboard_summary(
    scope: AnalysisScope = Depends(get_analysis_scope),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    filters = await validate_scope(current_user, scope)
    where = filter_where(filters)
    summary = await _safe_query(
        current_user,
        "SELECT ROUND(AVG(score)::numeric, 2) AS average_score, "
        "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) "
        "AS overall_score_rate, "
        "ROUND(AVG(CASE WHEN passed THEN 1 ELSE 0 END)::numeric * 100, 2) AS pass_rate, "
        "COUNT(DISTINCT student_id) AS student_count, COUNT(DISTINCT exam_id) AS exam_count "
        f"FROM score_facts{where}",
    )
    grade_counts = await _safe_query(
        current_user,
        f"SELECT COUNT(DISTINCT grade_level) AS total FROM score_facts{where}",
    )
    mixed_grade_scope = int(grade_counts[0]["total"] if grade_counts else 0) > 1
    year_counts = await _safe_query(
        current_user,
        f"SELECT COUNT(DISTINCT academic_year) AS total FROM score_facts{where}",
    )
    mixed_academic_year_scope = int(year_counts[0]["total"] if year_counts else 0) > 1
    comparable_detail_scope = not mixed_grade_scope and not mixed_academic_year_scope
    subject_averages = await _safe_query(
        current_user,
        "SELECT subject_name, ROUND(AVG(score)::numeric, 2) AS average_score, "
        "ROUND(MAX(max_score)::numeric, 2) AS max_score "
        f"FROM score_facts{where} GROUP BY subject_name ORDER BY subject_name",
    ) if comparable_detail_scope else []
    exam_trend = await _safe_query(
        current_user,
        "SELECT exam_date, exam_name, ROUND(AVG(score)::numeric, 2) AS average_score, "
        "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) AS score_rate "
        f"FROM score_facts{where} GROUP BY exam_date, exam_name ORDER BY exam_date",
    ) if comparable_detail_scope else []
    grade_comparison = [] if mixed_academic_year_scope else await _safe_query(
        current_user,
        "SELECT grade_level, "
        "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) AS score_rate, "
        "ROUND(AVG(CASE WHEN passed THEN 1 ELSE 0 END)::numeric * 100, 2) AS pass_rate, "
        "COUNT(DISTINCT student_id) AS student_count "
        f"FROM score_facts{where} GROUP BY grade_level ORDER BY grade_level",
    )
    year_comparison = await _safe_query(
        current_user,
        "SELECT academic_year, "
        "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) AS score_rate, "
        "ROUND(AVG(CASE WHEN passed THEN 1 ELSE 0 END)::numeric * 100, 2) AS pass_rate, "
        "COUNT(DISTINCT student_id) AS student_count "
        f"FROM score_facts{where} GROUP BY academic_year ORDER BY academic_year",
    )
    grade_comparison.sort(key=lambda item: grade_sort_key(item["grade_level"]))
    subject_averages.sort(key=lambda item: subject_sort_key(item["subject_name"]))
    metrics = summary[0] if summary else {}
    return DashboardResponse(
        average_score=float(metrics.get("average_score") or 0),
        overall_score_rate=float(metrics.get("overall_score_rate") or 0),
        pass_rate=float(metrics.get("pass_rate") or 0),
        student_count=int(metrics.get("student_count") or 0),
        exam_count=int(metrics.get("exam_count") or 0),
        scope_description=await _scope_description(session, current_user, filters),
        applied_scope=AnalysisScope(**filters),
        mixed_grade_scope=mixed_grade_scope,
        mixed_academic_year_scope=mixed_academic_year_scope,
        comparison_note=(
            "当前包含多个学年，已隐藏不可直接比较的原始学科均分与考试趋势；"
            "请查看学年得分率对比。选择届别表示同一届纵向变化，选择年级表示跨届对比。"
            if mixed_academic_year_scope
            else (
                "当前包含多个年级，已隐藏不可直接比较的原始学科均分与考试趋势；"
                "请查看年级得分率对比或选择单一年级。"
                if mixed_grade_scope
                else "同一学年、同一年级内按得分率比较，避免满分差异造成误读。"
            )
        ),
        grade_comparison=grade_comparison,
        year_comparison=year_comparison,
        subject_averages=subject_averages,
        exam_trend=exam_trend,
    )
