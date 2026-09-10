from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.agents.query_graph as query_graph
from app.agents.contracts import SchemaResolution
from app.core.models import User, UserRole
from app.services.sql_security import SQLSafetyGate, ValidationResult


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("最近3次考试语文平均分", 3),
        ("近三次考试语文平均分", 3),
        ("近两次考试各科成绩趋势", 2),
        ("最近 12 次考试数学成绩", 12),
        ("最近二十三场考试不及格记录", 23),
        ("查询我的历史五次考试各科成绩", None),
        ("查看我近几次考试成绩", None),
    ],
)
def test_recent_exam_limit_parses_only_explicit_recent_counts(
    question: str, expected: int | None
) -> None:
    assert query_graph._recent_exam_limit(question) == expected


def _state(question: str, *, filters: dict[str, str] | None = None) -> dict:
    return {
        "question": question,
        "user": User(role=UserRole.STUDENT),
        "catalog": {
            "classes": ["初二1班"],
            "exams": [],
            "subjects": ["语文", "数学", "英语"],
        },
        "schema_resolution": SchemaResolution(
            intent="成绩查询",
            resolved_filters=filters or {},
        ),
    }


def _block_orchestrator(monkeypatch) -> None:
    monkeypatch.setattr(
        query_graph.registry,
        "orchestrator",
        SimpleNamespace(
            ainvoke=AsyncMock(side_effect=AssertionError("model must not be called"))
        ),
    )


@pytest.mark.asyncio
async def test_recent_detail_sql_limits_the_exam_set_before_returning_subject_rows() -> None:
    result = await query_graph.sql_node(_state("最近3次考试各科成绩"))
    sql = result["sql_draft"].sql

    assert SQLSafetyGate().validate(sql).allowed is True
    assert "exam_id IN (SELECT exam_id FROM score_facts" in sql
    assert "ORDER BY exam_date DESC, exam_id DESC LIMIT 3" in sql
    assert "ORDER BY exam_date DESC, subject_name" in sql


@pytest.mark.asyncio
async def test_recent_subject_average_sql_combines_all_selected_exams_into_one_row(
    monkeypatch,
) -> None:
    monkeypatch.setattr(query_graph.registry, "enabled", False)

    result = await query_graph.sql_node(
        _state("最近2次考试数学平均分", filters={"subject_name": "数学"})
    )
    sql = result["sql_draft"].sql

    assert SQLSafetyGate().validate(sql).allowed is True
    assert "ROUND(AVG(score)::numeric, 2) AS average_score" in sql
    assert "COUNT(DISTINCT exam_id) AS exam_count" in sql
    assert "GROUP BY subject_name" in sql
    assert "GROUP BY exam_name" not in sql
    assert "ORDER BY exam_date DESC, exam_id DESC LIMIT 2" in sql


@pytest.mark.asyncio
async def test_recent_trend_sql_uses_the_requested_exam_limit() -> None:
    result = await query_graph.sql_node(_state("近两次考试各科成绩趋势"))
    sql = result["sql_draft"].sql

    assert SQLSafetyGate().validate(sql).allowed is True
    assert "ORDER BY exam_date DESC, exam_id DESC LIMIT 2" in sql
    assert "GROUP BY exam_date, exam_name, subject_name" in sql


@pytest.mark.asyncio
async def test_recent_failure_sql_uses_the_requested_exam_limit() -> None:
    result = await query_graph.sql_node(_state("最近3次考试不及格记录"))
    sql = result["sql_draft"].sql

    assert SQLSafetyGate().validate(sql).allowed is True
    assert "passed = false" in sql
    assert "ORDER BY exam_date DESC, exam_id DESC LIMIT 3" in sql


@pytest.mark.asyncio
async def test_recent_failure_chart_counts_use_the_same_exam_limit(monkeypatch) -> None:
    observed: dict[str, ValidationResult] = {}

    async def capture_validation(_user, validation):
        observed["validation"] = validation
        return []

    monkeypatch.setattr(query_graph, "execute_scoped_query", capture_validation)

    await query_graph._failure_subject_counts(_state("最近3次考试不及格记录"))

    validation = observed["validation"]
    assert validation.allowed is True
    assert 3 in validation.params.values()
    assert "ORDER BY exam_date DESC, exam_id DESC LIMIT :value_" in (
        validation.display_sql or ""
    )


@pytest.mark.asyncio
async def test_recent_schema_resolution_does_not_call_the_model(monkeypatch) -> None:
    monkeypatch.setattr(query_graph.registry, "enabled", True)
    blocked_model = AsyncMock(side_effect=AssertionError("model must not be called"))
    monkeypatch.setattr(query_graph, "_structured", blocked_model)

    result = await query_graph.schema_node(_state("最近2次考试数学平均分"))

    assert result["schema_resolution"].resolved_filters == {"subject_name": "数学"}
    blocked_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_audit_does_not_call_the_model(monkeypatch) -> None:
    monkeypatch.setattr(query_graph.registry, "enabled", True)
    blocked_model = AsyncMock(side_effect=AssertionError("model must not be called"))
    monkeypatch.setattr(query_graph, "_structured", blocked_model)

    result = await query_graph.audit_node(
        {
            **_state("最近2次考试数学平均分"),
            "sql_draft": query_graph.SQLDraft(sql="SELECT score FROM score_facts"),
            "validation": ValidationResult(
                allowed=True,
                normalized_sql="SELECT score FROM score_facts",
            ),
        }
    )

    assert result["audit"].risk_level == "low"
    blocked_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_average_visualization_does_not_call_the_model(monkeypatch) -> None:
    monkeypatch.setattr(query_graph.registry, "enabled", True)
    blocked_model = AsyncMock(side_effect=AssertionError("model must not be called"))
    monkeypatch.setattr(query_graph, "_structured", blocked_model)

    result = await query_graph.visualization_node(
        {
            **_state("最近2次考试数学平均分"),
            "rows": [
                {
                    "subject_name": "数学",
                    "average_score": "73.50",
                    "max_score": 150,
                    "exam_count": 2,
                }
            ],
        }
    )

    assert result["chart"].type == "bar"
    blocked_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_subject_average_answer_is_derived_from_the_aggregate_row(
    monkeypatch,
) -> None:
    _block_orchestrator(monkeypatch)

    result = await query_graph.final_node(
        {
            **_state("最近2次考试数学平均分"),
            "rows": [
                {
                    "subject_name": "数学",
                    "average_score": "73.50",
                    "max_score": 150,
                    "exam_count": 2,
                }
            ],
        }
    )

    assert result["answer"] == "最近2次考试数学平均分为73.50分。"


@pytest.mark.asyncio
async def test_recent_average_answer_reports_when_fewer_exams_exist(monkeypatch) -> None:
    _block_orchestrator(monkeypatch)

    result = await query_graph.final_node(
        {
            **_state("最近10次考试语文平均分"),
            "rows": [
                {
                    "subject_name": "语文",
                    "average_score": "113.00",
                    "max_score": 150,
                    "exam_count": 5,
                }
            ],
        }
    )

    assert result["answer"] == "查询最近10次考试，实际找到5次；语文平均分为113.00分。"


@pytest.mark.asyncio
async def test_recent_single_score_answer_is_deterministic(monkeypatch) -> None:
    _block_orchestrator(monkeypatch)

    result = await query_graph.final_node(
        {
            **_state("最近1次考试英语成绩"),
            "rows": [
                {
                    "exam_date": "2027-06-25",
                    "exam_name": "初二下学期期末考试",
                    "subject_name": "英语",
                    "score": 101.0,
                    "passed": True,
                }
            ],
        }
    )

    assert result["answer"] == "最近一次初二下学期期末考试中，英语成绩为101.0分。"


@pytest.mark.asyncio
async def test_recent_trend_answer_reports_exact_exam_and_subject_counts(monkeypatch) -> None:
    _block_orchestrator(monkeypatch)
    rows = [
        {
            "exam_date": exam_date,
            "exam_name": exam_name,
            "subject_name": subject_name,
            "score_rate": score_rate,
        }
        for exam_date, exam_name, subject_name, score_rate in [
            ("2027-04-25", "期中考试", "语文", 77.33),
            ("2027-04-25", "期中考试", "数学", 52.0),
            ("2027-06-25", "期末考试", "语文", 73.33),
            ("2027-06-25", "期末考试", "数学", 46.0),
        ]
    ]

    result = await query_graph.final_node(
        {**_state("近两次考试各科成绩趋势"), "rows": rows}
    )

    assert result["answer"] == "已汇总最近2次考试、2个科目的成绩趋势，详见下方图表和数据。"
