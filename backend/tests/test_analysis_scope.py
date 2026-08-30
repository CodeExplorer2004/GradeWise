from app.core.schemas import AnalysisScope, ChatRequest
from app.services.analysis_scope import apply_scope_to_sql, filter_where, scope_filters
from app.services.sql_security import SQLSafetyGate


def test_analysis_scope_filters_only_supported_non_empty_fields() -> None:
    filters = scope_filters(
        AnalysisScope(
            academic_year="2026-2027",
            grade_level="初三",
            cohort_year=2024,
            term=None,
        )
    )

    assert filters == {
        "academic_year": "2026-2027",
        "grade_level": "初三",
        "cohort_year": 2024,
    }
    assert filter_where(filters).startswith(" WHERE ")


def test_analysis_scope_is_appended_to_existing_chat_sql_before_validation() -> None:
    sql = apply_scope_to_sql(
        "SELECT subject_name, AVG(score) AS average_score FROM score_facts "
        "WHERE passed = true GROUP BY subject_name",
        {"academic_year": "2026-2027", "grade_level": "初三"},
    )
    validation = SQLSafetyGate().validate(sql)

    assert validation.allowed
    assert "academic_year" in sql
    assert "grade_level" in sql
    assert "passed = TRUE" in sql


def test_chat_request_accepts_empty_or_explicit_analysis_scope() -> None:
    empty = ChatRequest(message="查询各科成绩")
    scoped = ChatRequest(
        message="查询各科成绩",
        scope={"academic_year": "2026-2027", "exam_type": "期末"},
    )

    assert empty.scope.model_dump(exclude_none=True) == {}
    assert scoped.scope.academic_year == "2026-2027"
    assert scoped.scope.exam_type == "期末"
