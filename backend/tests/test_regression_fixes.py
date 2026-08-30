import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.api.tasks as task_api
import app.services.risk_prediction as risk_service
from app.core.models import UserRole
from app.core.schemas import AgentTaskRequest, AgentTaskResponse
from app.services.privacy import risk_batch_evidence
from app.services.risk_prediction import prediction_from_row
from app.services.score_import import parse_score_file


def _risk_row(student_id: int, *, class_id: int = 1) -> dict:
    return {
        "student_id": student_id,
        "student_name": f"学生{student_id}",
        "class_id": class_id,
        "class_name": f"班级{class_id}",
        "subject_id": 2,
        "subject_name": "数学",
        "latest_score": 70,
        "first_score": 75,
        "pass_score": 60,
        "max_score": 100,
        "volatility": 4,
        "failure_ratio": 0,
        "exam_count": 3,
    }


def test_batch_risk_evidence_keeps_deterministic_counts_but_omits_low_details() -> None:
    low = prediction_from_row(_risk_row(1))
    high_row = _risk_row(2)
    high_row.update(latest_score=40, first_score=75, failure_ratio=0.6, volatility=15)
    high = prediction_from_row(high_row)

    evidence = risk_batch_evidence([high, low])

    assert evidence["deterministic_summary"]["total_predictions"] == 2
    assert evidence["deterministic_summary"]["high_count"] == 1
    assert evidence["deterministic_summary"]["low_count"] == 1
    assert evidence["deterministic_summary"]["evidence_items_count"] == 1
    assert [item["risk_level"] for item in evidence["items"]] == ["high"]


@pytest.mark.asyncio
async def test_risk_collection_reads_every_page_and_deduplicates(monkeypatch) -> None:
    pages = [
        [_risk_row(1, class_id=10), _risk_row(2)],
        [_risk_row(1, class_id=20)],
    ]
    validations = []

    async def fake_execute(_user, validation):
        validations.append(validation)
        return pages.pop(0)

    monkeypatch.setattr(risk_service, "RISK_PAGE_SIZE", 2)
    monkeypatch.setattr(risk_service, "execute_scoped_query", fake_execute)

    predictions = await risk_service.collect_risk_predictions(SimpleNamespace())

    assert len(predictions) == 2
    assert {item.student_id for item in predictions} == {1, 2}
    assert next(item for item in predictions if item.student_id == 1).class_id == 20
    assert len(validations) == 2
    assert all("FIRST_VALUE(class_id)" in item.normalized_sql for item in validations)


@pytest.mark.asyncio
async def test_risk_snapshots_are_deduplicated_and_written_in_batches(monkeypatch) -> None:
    predictions = [prediction_from_row(_risk_row(index)) for index in range(1, 4)]
    predictions.append(predictions[0])
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(risk_service, "SNAPSHOT_BATCH_SIZE", 2)

    await risk_service.persist_risk_snapshots(session, 1, predictions)

    assert session.execute.await_count == 2
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_warning_passes_the_complete_validated_scope(monkeypatch) -> None:
    validated_scope = {
        "academic_year": "2026-2027",
        "grade_level": "初二",
        "term": "第一学期",
        "cohort_year": 2025,
    }
    observed = {}

    async def fake_validate(_user, _scope):
        return validated_scope

    async def fake_collect(_user, filters):
        observed["filters"] = filters
        return []

    async def fake_start(user_id, task_type, description, scope=None, result_prefix=None):
        observed["description"] = json.loads(description)
        observed["result_prefix"] = result_prefix
        return AgentTaskResponse(
            task_id="task",
            run_id="run",
            task_type=task_type,
            status="pending",
            scope=scope or {},
        )

    monkeypatch.setattr(task_api, "_validated_scope", fake_validate)
    monkeypatch.setattr(task_api, "collect_risk_predictions", fake_collect)
    monkeypatch.setattr(task_api, "start_task", fake_start)
    user = SimpleNamespace(id=1, role=UserRole.ACADEMIC_ADMIN)
    payload = AgentTaskRequest(task_type="batch_warning", scope=validated_scope)

    await task_api.create_agent_task(payload, user)

    assert observed["filters"] == validated_scope
    assert observed["description"]["scope"] == validated_scope
    assert observed["description"]["evidence"]["deterministic_summary"] == {
        "total_predictions": 0,
        "high_count": 0,
        "medium_count": 0,
        "low_count": 0,
        "evidence_items_count": 0,
        "evidence_note": "仅提供中高风险明细，按风险分数排序，最多前100条",
    }
    assert "共 0 条学生-科目风险记录" in observed["result_prefix"]
    assert "AI 解释仅供人工复核" in observed["result_prefix"]


def test_malformed_xlsx_is_reported_as_a_validation_error() -> None:
    with pytest.raises(ValueError, match="文件解析失败"):
        parse_score_file("bad.xlsx", b"not-a-zip")


@pytest.mark.parametrize(
    ("filename", "content"),
    [("empty.csv", b""), ("empty.json", b"[]")],
)
def test_empty_score_import_is_rejected(filename: str, content: bytes) -> None:
    with pytest.raises(ValueError, match="没有可导入的数据行"):
        parse_score_file(filename, content)
