from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlglot import exp, parse_one

from app.core.models import User
from app.core.schemas import AnalysisFilterOptions, AnalysisScope
from app.services.sql_security import SQLSafetyGate, execute_scoped_query

FILTER_COLUMNS = {
    "academic_year",
    "grade_level",
    "term",
    "exam_type",
    "cohort_year",
    "class_name",
    "subject_name",
    "exam_name",
}
GRADE_ORDER = {"初一": 1, "初二": 2, "初三": 3, "高一": 4, "高二": 5, "高三": 6}
SUBJECT_ORDER = {
    "语文": 1,
    "数学": 2,
    "英语": 3,
    "政治": 4,
    "历史": 5,
    "地理": 6,
    "生物": 7,
    "物理": 8,
    "化学": 9,
}


def grade_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    return GRADE_ORDER.get(text, 999), text


def subject_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    return SUBJECT_ORDER.get(text, 999), text


def quoted(value: str | int) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def scope_filters(scope: AnalysisScope | dict[str, Any] | None) -> dict[str, str | int]:
    if not scope:
        return {}
    values = scope if isinstance(scope, dict) else scope.model_dump(exclude_none=True)
    return {
        field: int(value) if field == "cohort_year" else str(value)
        for field, value in values.items()
        if field in FILTER_COLUMNS and value not in (None, "")
    }


def filter_predicate(scope: AnalysisScope | dict[str, Any] | None) -> str:
    return " AND ".join(
        f"{field} = {value if isinstance(value, int) else quoted(value)}"
        for field, value in scope_filters(scope).items()
    )


def filter_where(scope: AnalysisScope | dict[str, Any] | None) -> str:
    predicate = filter_predicate(scope)
    return f" WHERE {predicate}" if predicate else ""


def apply_scope_to_sql(sql: str, scope: AnalysisScope | dict[str, Any] | None) -> str:
    filters = scope_filters(scope)
    if not filters:
        return sql
    tree = parse_one(sql, read="postgres")
    predicate: exp.Expression | None = None
    for field, value in filters.items():
        literal = exp.Literal.number(value) if isinstance(value, int) else exp.Literal.string(value)
        condition = exp.column(field).eq(literal)
        predicate = condition if predicate is None else exp.and_(predicate, condition)
    if predicate is not None:
        tree = tree.where(predicate, append=True)
    return tree.sql(dialect="postgres")


async def safe_scope_query(user: User, sql: str) -> list[dict[str, Any]]:
    validation = SQLSafetyGate().validate(sql)
    if not validation.allowed:
        raise RuntimeError(f"Internal scope query rejected: {validation.violations}")
    return await execute_scoped_query(user, validation)


async def collect_filter_options(
    user: User, scope: AnalysisScope | dict[str, Any] | None = None
) -> AnalysisFilterOptions:
    selected_filters = scope_filters(scope)

    async def distinct(column: str, *, numeric: bool = False) -> list[Any]:
        facet_filters = {
            field: value for field, value in selected_filters.items() if field != column
        }
        predicate = filter_predicate(facet_filters)
        conditions = [f"{column} IS NOT NULL"]
        if predicate:
            conditions.append(predicate)
        rows = await safe_scope_query(
            user,
            f"SELECT DISTINCT {column} FROM score_facts WHERE "
            f"{' AND '.join(conditions)} ORDER BY {column}",
        )
        values = [row[column] for row in rows]
        return [int(value) for value in values] if numeric else [str(value) for value in values]

    academic_years = await distinct("academic_year")
    grade_levels = sorted(await distinct("grade_level"), key=grade_sort_key)
    cohort_years = await distinct("cohort_year", numeric=True)
    defaults = AnalysisScope(
        academic_year=academic_years[-1] if academic_years else None,
        grade_level=grade_levels[0] if len(grade_levels) == 1 else None,
        cohort_year=cohort_years[0] if len(cohort_years) == 1 else None,
    )
    return AnalysisFilterOptions(
        academic_years=academic_years,
        grade_levels=grade_levels,
        terms=await distinct("term"),
        exam_types=await distinct("exam_type"),
        cohort_years=cohort_years,
        classes=await distinct("class_name"),
        subjects=sorted(await distinct("subject_name"), key=subject_sort_key),
        exams=await distinct("exam_name"),
        defaults=defaults,
    )


async def validate_scope(user: User, scope: AnalysisScope) -> dict[str, str | int]:
    filters = scope_filters(scope)
    if not filters:
        return filters
    options = await collect_filter_options(user)
    allowed: dict[str, list[str] | list[int]] = {
        "academic_year": options.academic_years,
        "grade_level": options.grade_levels,
        "term": options.terms,
        "exam_type": options.exam_types,
        "cohort_year": options.cohort_years,
        "class_name": options.classes,
        "subject_name": options.subjects,
        "exam_name": options.exams,
    }
    for field, value in filters.items():
        if value not in allowed[field]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"所选{field}不在当前账号权限范围内",
            )
    rows = await safe_scope_query(
        user, f"SELECT COUNT(*) AS total FROM score_facts{filter_where(filters)}"
    )
    if not rows or int(rows[0]["total"]) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前筛选条件组合没有可用成绩数据",
        )
    return filters
