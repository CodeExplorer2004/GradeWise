import pytest
from sqlalchemy import Float

from app.agents.contracts import SchemaResolution
from app.agents.query_graph import (
    _is_broad_history_question,
    _is_failure_query,
    _is_personal_history_query,
    _is_subject_rate_history_query,
    _resolved_filters,
    _strip_history_subject_filter,
    final_node,
    prepare_sql_retry,
    schema_node,
    sql_node,
    validation_route,
)
from app.core.models import User, UserRole
from app.services.learning_insights import (
    ANOMALY_SOURCE,
    CURRENT_RISK_SOURCE,
    FLUCTUATION_SOURCE,
    _alert_query,
)
from app.services.sql_security import SQLSafetyGate, ValidationResult, _bind_type


@pytest.fixture
def gate() -> SQLSafetyGate:
    return SQLSafetyGate()


def test_allows_single_select_and_parameterizes_literals(gate: SQLSafetyGate) -> None:
    result = gate.validate(
        "SELECT subject_name, ROUND(AVG(score)::numeric, 2) AS average_score "
        "FROM score_facts WHERE exam_name = '期中考试' GROUP BY subject_name"
    )

    assert result.allowed is True
    assert result.params == {"value_0": 2, "value_1": "期中考试"}
    assert "期中考试" not in (result.normalized_sql or "")
    assert "LIMIT 500" in (result.normalized_sql or "")
    assert ":value_1" in (result.display_sql or "")
    assert "%(value_1)s" not in (result.display_sql or "")


@pytest.mark.parametrize(
    ("sql", "violation"),
    [
        ("DELETE FROM score_facts", "ONLY_SELECT_ALLOWED"),
        ("SELECT * FROM users", "TABLE_NOT_ALLOWED:users"),
        ("SELECT pg_sleep(1) FROM score_facts", "FUNCTION_NOT_ALLOWED:pg_sleep"),
        ("SELECT * FROM score_facts; SELECT * FROM score_facts", "STACKED_STATEMENT_NOT_ALLOWED"),
        ("SELECT * FROM score_facts -- bypass", "SQL_COMMENT_NOT_ALLOWED"),
        (
            "WITH x AS (SELECT * FROM score_facts) SELECT * FROM x",
            "DANGEROUS_STATEMENT",
        ),
    ],
)
def test_rejects_unsafe_sql(gate: SQLSafetyGate, sql: str, violation: str) -> None:
    result = gate.validate(sql)

    assert result.allowed is False
    assert violation in result.violations


def test_rejects_select_without_allowed_data_source(gate: SQLSafetyGate) -> None:
    result = gate.validate("SELECT current_user")

    assert result.allowed is False
    assert "DATA_SOURCE_REQUIRED" in result.violations


def test_rejects_model_generated_current_user_id_function(gate: SQLSafetyGate) -> None:
    result = gate.validate(
        "SELECT exam_name, subject_name, score FROM score_facts "
        "WHERE student_id = current_user_id() ORDER BY exam_date"
    )

    assert result.allowed is False
    assert result.violations == ["FUNCTION_NOT_ALLOWED:current_user_id"]


def test_identity_function_violation_gets_exactly_one_sql_retry(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.query_graph.registry.enabled", True)
    rejected = ValidationResult(
        allowed=False, violations=["FUNCTION_NOT_ALLOWED:current_user_id"]
    )

    assert validation_route({"validation": rejected, "sql_retry_count": 0}) == "prepare_retry"
    assert prepare_sql_retry({}) == {"sql_retry_count": 1}
    assert validation_route({"validation": rejected, "sql_retry_count": 1}) == "audit"


def test_other_disallowed_function_does_not_get_sql_retry(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.query_graph.registry.enabled", True)
    rejected = ValidationResult(allowed=False, violations=["FUNCTION_NOT_ALLOWED:pg_sleep"])

    assert validation_route({"validation": rejected, "sql_retry_count": 0}) == "audit"


def test_historical_all_subjects_does_not_resolve_history_as_subject() -> None:
    catalog = {"classes": [], "exams": [], "subjects": ["语文", "历史", "数学"]}

    filters = _resolved_filters("查询我的历史考试各科成绩", catalog)

    assert "subject_name" not in filters


def test_explicit_history_subject_still_resolves_subject_filter() -> None:
    catalog = {"classes": [], "exams": [], "subjects": ["语文", "历史", "数学"]}

    filters = _resolved_filters("查询我的历史学科成绩", catalog)

    assert filters["subject_name"] == "历史"


def test_historical_all_subjects_strips_only_ambiguous_subject_predicate() -> None:
    sql = (
        "SELECT student_name, exam_name, subject_name, score FROM score_facts "
        "WHERE student_name = '程楠' AND subject_name = '历史' ORDER BY exam_date"
    )

    corrected = _strip_history_subject_filter(sql)
    result = SQLSafetyGate().validate(corrected)

    assert result.allowed is True
    assert "subject_name =" not in corrected
    assert "student_name = '程楠'" in corrected


def test_history_only_predicate_can_be_removed_without_invalid_where() -> None:
    corrected = _strip_history_subject_filter(
        "SELECT exam_name, subject_name, score FROM score_facts WHERE subject_name = '历史'"
    )

    assert " WHERE " not in corrected
    assert SQLSafetyGate().validate(corrected).allowed is True


@pytest.mark.parametrize(
    "question",
    [
        "查询我的历史考试各科成绩",
        "查询我的历史五次考试的各科成绩",
        "查看本人历次考试成绩",
        "查看我近几次考试成绩",
    ],
)
def test_personal_multi_exam_questions_use_deterministic_intent(question: str) -> None:
    state = {"question": question, "user": User(role=UserRole.STUDENT)}

    assert _is_broad_history_question(question) is True
    assert _is_personal_history_query(state) is True


def test_history_subject_query_is_not_treated_as_multi_exam_history() -> None:
    question = "查询我的历史学科成绩"
    state = {"question": question, "user": User(role=UserRole.STUDENT)}

    assert _is_broad_history_question(question) is False
    assert _is_personal_history_query(state) is False


@pytest.mark.parametrize(
    "question",
    [
        "查看我的历次考试各科目得分率趋势",
        "历次考试各科成绩折线图",
        "查看过往考试所有科目的趋势",
    ],
)
def test_subject_rate_history_questions_use_deterministic_intent(question: str) -> None:
    assert _is_subject_rate_history_query(question) is True


@pytest.mark.parametrize("question", ["查看不及格记录", "查询挂科学生"])
def test_failure_questions_use_deterministic_intent(question: str) -> None:
    assert _is_failure_query(question) is True


@pytest.mark.asyncio
async def test_failure_query_preserves_specific_exam_filter() -> None:
    state = {
        "question": "查看初三下学期二模不及格记录",
        "user": User(role=UserRole.HEAD_TEACHER),
        "catalog": {
            "classes": ["初三1班"],
            "exams": ["初三下学期二模"],
            "subjects": ["语文", "数学"],
        },
        "schema_resolution": SchemaResolution(intent="不及格记录"),
    }

    result = await sql_node(state)
    sql = result["sql_draft"].sql
    validation = SQLSafetyGate().validate(sql)

    assert validation.allowed is True
    assert "passed = false" in sql
    assert "exam_name = '初三下学期二模'" in sql
    assert "LIMIT" not in sql


@pytest.mark.asyncio
async def test_failure_schema_resolves_specific_exam_without_model() -> None:
    state = {
        "question": "查看初三下学期二模不及格记录",
        "catalog": {
            "classes": ["初三1班"],
            "exams": ["初三下学期二模"],
            "subjects": ["语文", "数学"],
        },
    }

    result = await schema_node(state)

    assert result["schema_resolution"].resolved_filters == {
        "exam_name": "初三下学期二模"
    }


@pytest.mark.asyncio
async def test_subject_rate_history_query_uses_numeric_safe_template() -> None:
    state = {
        "question": "查看我的历次考试各科目得分率趋势",
        "user": User(role=UserRole.STUDENT),
        "schema_resolution": SchemaResolution(
            intent="多科得分率趋势",
            relevant_columns=["exam_date", "subject_name", "score_rate"],
        ),
    }

    result = await sql_node(state)
    sql = result["sql_draft"].sql
    validation = SQLSafetyGate().validate(sql)

    assert validation.allowed is True
    assert "score::numeric" in sql
    assert "max_score::numeric" in sql
    assert "GROUP BY exam_date, exam_name, subject_name" in sql


@pytest.mark.asyncio
async def test_personal_history_query_uses_safe_unfiltered_exam_template() -> None:
    state = {
        "question": "查询我的历史五次考试的各科成绩",
        "user": User(role=UserRole.STUDENT),
    }

    result = await sql_node(state)
    validation = SQLSafetyGate().validate(result["sql_draft"].sql)

    assert validation.allowed is True
    assert "exam_name" in result["sql_draft"].sql
    assert " WHERE " not in result["sql_draft"].sql


@pytest.mark.asyncio
async def test_multi_exam_final_answer_reports_full_scope() -> None:
    rows = [
        {
            "student_name": "测试学生",
            "exam_date": "2026-11-01",
            "exam_name": "期中考试",
            "subject_name": "语文",
            "passed": True,
        },
        {
            "student_name": "测试学生",
            "exam_date": "2027-01-10",
            "exam_name": "期末考试",
            "subject_name": "语文",
            "passed": False,
        },
    ]

    result = await final_node({"question": "查询我的历史考试各科成绩", "rows": rows})

    assert "2次考试" in result["answer"]
    assert "详细分数" in result["answer"]


def test_allows_safe_conditional_aggregate(gate: SQLSafetyGate) -> None:
    result = gate.validate(
        "SELECT AVG(CASE WHEN passed THEN 1 ELSE 0 END) AS pass_rate FROM score_facts"
    )

    assert result.allowed is True


def test_allows_boolean_operators_without_treating_them_as_functions(
    gate: SQLSafetyGate,
) -> None:
    result = gate.validate(
        "SELECT score FROM score_facts WHERE student_id = 1 "
        "AND score IS NOT NULL AND NOT passed"
    )

    assert result.allowed is True


def test_allows_normalized_score_rate_aggregates(gate: SQLSafetyGate) -> None:
    result = gate.validate(
        "SELECT exam_name, "
        "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) AS score_rate "
        "FROM score_facts GROUP BY exam_name ORDER BY exam_name"
    )

    assert result.allowed is True


def test_decimal_literals_bind_as_floats(gate: SQLSafetyGate) -> None:
    result = gate.validate(
        "SELECT score FROM score_facts WHERE score / NULLIF(max_score, 0) >= 0.15"
    )

    decimal_value = next(value for value in result.params.values() if str(value) == "0.15")
    assert isinstance(_bind_type(decimal_value), Float)


@pytest.mark.parametrize(
    ("alert_type", "source"),
    [
        ("anomaly", ANOMALY_SOURCE),
        ("fluctuation", FLUCTUATION_SOURCE),
        ("current_risk", CURRENT_RISK_SOURCE),
    ],
)
def test_learning_alert_queries_pass_the_sql_gate(alert_type: str, source: str) -> None:
    assert SQLSafetyGate().validate(f"SELECT COUNT(*) AS total {source}").allowed
    assert SQLSafetyGate().validate(_alert_query(alert_type)).allowed


def test_converts_iso_date_literal_to_typed_date(gate: SQLSafetyGate) -> None:
    result = gate.validate("SELECT score FROM score_facts WHERE exam_date = '2026-11-15'")

    assert result.allowed is True
    assert str(result.params["value_0"]) == "2026-11-15"
    assert result.params["value_0"].__class__.__name__ == "date"
