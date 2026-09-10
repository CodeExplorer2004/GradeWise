from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.api import tasks as task_api
from app.core.models import UserRole
from app.core.schemas import AgentTaskRequest, AgentTaskResponse


def _admin() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        school_id=1,
        role=UserRole.ACADEMIC_ADMIN,
    )


def _response(status: str = "running") -> AgentTaskResponse:
    return AgentTaskResponse(
        task_id="task-1",
        run_id="run-1",
        task_type="batch_report",
        status=status,
        stage="agent_running" if status == "running" else "failed",
        status_message="Agent 正在生成报告" if status == "running" else "执行失败",
        scope={"class_name": "初一（1）班"},
        requested_scope={"class_name": "初一（1）班"},
        attempt_count=1,
        can_retry=status == "error",
    )


async def test_create_records_validated_scope_before_building_and_submitting(
    monkeypatch,
) -> None:
    calls: list[str] = []
    task = SimpleNamespace(id="task-1")

    async def validate(_user, _scope):
        calls.append("validate")
        return {"class_name": "初一（1）班"}

    async def create(*_args, **_kwargs):
        calls.append("record")
        return task

    async def build(*_args, **_kwargs):
        calls.append("evidence")
        return SimpleNamespace(description="redacted evidence", result_prefix=None)

    async def submit(*_args, **_kwargs):
        calls.append("submit")
        return _response()

    monkeypatch.setattr(task_api, "_validated_scope", validate)
    monkeypatch.setattr(task_api, "create_task_record", create, raising=False)
    monkeypatch.setattr(task_api, "_build_task_input", build, raising=False)
    monkeypatch.setattr(task_api, "submit_task", submit, raising=False)

    result = await task_api.create_agent_task(
        AgentTaskRequest(
            task_type="batch_report",
            scope={"class_name": "初一（1）班"},
        ),
        _admin(),
        AsyncMock(),
    )

    assert result.task_id == "task-1"
    assert calls == ["validate", "record", "evidence", "submit"]


async def test_create_returns_persisted_safe_error_when_submission_fails(
    monkeypatch,
) -> None:
    task = SimpleNamespace(id="task-1")
    safe_failure = _response("error").model_copy(
        update={
            "run_id": None,
            "error_code": "worker_unavailable",
            "status_message": "Agent 服务暂不可用，可稍后重新执行",
        }
    )
    fail_task = AsyncMock(return_value=safe_failure)
    monkeypatch.setattr(
        task_api,
        "_validated_scope",
        AsyncMock(return_value={"class_name": "初一（1）班"}),
    )
    monkeypatch.setattr(
        task_api,
        "create_task_record",
        AsyncMock(return_value=task),
    )
    monkeypatch.setattr(
        task_api,
        "_build_task_input",
        AsyncMock(
            return_value=SimpleNamespace(
                description="redacted evidence",
                result_prefix=None,
            )
        ),
    )
    monkeypatch.setattr(
        task_api,
        "submit_task",
        AsyncMock(side_effect=httpx.ConnectError("internal worker address")),
    )
    monkeypatch.setattr(task_api, "fail_task", fail_task, raising=False)

    result = await task_api.create_agent_task(
        AgentTaskRequest(task_type="batch_report"),
        _admin(),
        AsyncMock(),
    )

    assert result.task_id == "task-1"
    assert result.error_code == "worker_unavailable"
    assert result.can_retry is True
    assert "internal worker address" not in result.status_message
    fail_task.assert_awaited_once()


async def test_create_persists_safe_error_when_evidence_collection_fails(
    monkeypatch,
) -> None:
    task = SimpleNamespace(id="task-1")
    safe_failure = _response("error").model_copy(
        update={
            "run_id": None,
            "error_code": "evidence_collection_failed",
            "status_message": "任务数据准备失败，可稍后重新执行",
        }
    )
    fail_task = AsyncMock(return_value=safe_failure)
    submit_task = AsyncMock()
    monkeypatch.setattr(task_api, "_validated_scope", AsyncMock(return_value={}))
    monkeypatch.setattr(
        task_api,
        "create_task_record",
        AsyncMock(return_value=task),
    )
    monkeypatch.setattr(
        task_api,
        "_build_task_input",
        AsyncMock(side_effect=RuntimeError("raw student detail")),
    )
    monkeypatch.setattr(task_api, "submit_task", submit_task)
    monkeypatch.setattr(task_api, "fail_task", fail_task)

    result = await task_api.create_agent_task(
        AgentTaskRequest(task_type="batch_report"),
        _admin(),
        AsyncMock(),
    )

    assert result.error_code == "evidence_collection_failed"
    assert "raw student detail" not in result.status_message
    submit_task.assert_not_awaited()
    fail_task.assert_awaited_once()


async def test_retry_revalidates_saved_requested_scope(monkeypatch) -> None:
    observed: dict[str, object] = {}
    stored = SimpleNamespace(
        id="task-1",
        task_type="batch_report",
        requested_scope={"class_name": "初一（1）班"},
    )

    async def validate(_user, scope):
        observed["requested_scope"] = scope.model_dump(exclude_none=True)
        return {"class_name": "初一（1）班", "subject_name": "数学"}

    async def build(_user, _task_type, effective_scope):
        observed["effective_scope"] = effective_scope
        return SimpleNamespace(
            description="new redacted evidence",
            result_prefix=None,
        )

    async def retry(*args, **_kwargs):
        observed["description"] = args[3]
        observed["retry_scope"] = args[4]
        return _response()

    monkeypatch.setattr(
        task_api,
        "load_owned_task",
        AsyncMock(return_value=stored),
        raising=False,
    )
    monkeypatch.setattr(task_api, "_validated_scope", validate)
    monkeypatch.setattr(task_api, "_build_task_input", build)
    monkeypatch.setattr(task_api, "retry_task", retry, raising=False)

    result = await task_api.retry_agent_task(
        "task-1",
        _admin(),
        AsyncMock(),
    )

    assert result.status == "running"
    assert observed == {
        "requested_scope": {"class_name": "初一（1）班"},
        "effective_scope": {"class_name": "初一（1）班", "subject_name": "数学"},
        "description": "new redacted evidence",
        "retry_scope": {"class_name": "初一（1）班", "subject_name": "数学"},
    }


@pytest.mark.parametrize(
    ("role", "task_type"),
    [
        (UserRole.STUDENT, "batch_report"),
        (UserRole.SUBJECT_TEACHER, "batch_warning"),
    ],
)
async def test_retry_rechecks_current_role_before_building_evidence(
    monkeypatch,
    role,
    task_type,
) -> None:
    stored = SimpleNamespace(
        id="task-1",
        task_type=task_type,
        requested_scope={},
    )
    build = AsyncMock()
    monkeypatch.setattr(
        task_api,
        "load_owned_task",
        AsyncMock(return_value=stored),
    )
    monkeypatch.setattr(task_api, "_build_task_input", build)
    user = SimpleNamespace(id=7, school_id=1, role=role)

    with pytest.raises(HTTPException) as error:
        await task_api.retry_agent_task("task-1", user, AsyncMock())

    assert error.value.status_code == 403
    build.assert_not_awaited()


async def test_invalid_retry_transition_returns_conflict(monkeypatch) -> None:
    stored = SimpleNamespace(
        id="task-1",
        task_type="batch_report",
        requested_scope={},
    )
    monkeypatch.setattr(
        task_api,
        "load_owned_task",
        AsyncMock(return_value=stored),
    )
    monkeypatch.setattr(task_api, "_validated_scope", AsyncMock(return_value={}))
    monkeypatch.setattr(
        task_api,
        "_build_task_input",
        AsyncMock(
            return_value=SimpleNamespace(
                description="redacted evidence",
                result_prefix=None,
            )
        ),
    )
    monkeypatch.setattr(
        task_api,
        "retry_task",
        AsyncMock(side_effect=task_api.InvalidTaskTransition("任务当前不可重试")),
    )

    with pytest.raises(HTTPException) as error:
        await task_api.retry_agent_task("task-1", _admin(), AsyncMock())

    assert error.value.status_code == 409
    assert error.value.detail == "任务当前不可重试"
