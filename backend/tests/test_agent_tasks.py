from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx

import app.services.agent_tasks as task_service
from app.core.models import AgentTask
from app.core.schemas import AgentTaskResponse
from app.services.agent_tasks import normalize_worker_status, task_response


def test_agent_task_model_contains_persistent_worker_and_lifecycle_fields() -> None:
    columns = AgentTask.__table__.columns

    assert {
        "id",
        "school_id",
        "user_id",
        "task_type",
        "requested_scope",
        "effective_scope",
        "worker_thread_id",
        "worker_run_id",
        "status",
        "stage",
        "status_message",
        "result",
        "result_prefix",
        "error_code",
        "attempt_count",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    } <= set(columns.keys())
    assert columns["result"].nullable
    assert columns["worker_run_id"].nullable
    assert AgentTask.__mapper__.eager_defaults is True


def test_agent_task_response_preserves_compatible_scope_and_retry_metadata() -> None:
    now = datetime.now(UTC)

    response = AgentTaskResponse(
        task_id="task-1",
        run_id=None,
        task_type="batch_report",
        status="interrupted",
        stage="interrupted",
        status_message="Agent 运行环境已重启，可重新执行",
        scope={"class_name": "初一（1）班"},
        requested_scope={"class_name": "初一（1）班"},
        error_code="worker_state_missing",
        attempt_count=1,
        can_retry=True,
        created_at=now,
        updated_at=now,
    )

    assert response.scope.class_name == "初一（1）班"
    assert response.run_id is None
    assert response.can_retry is True


def test_worker_statuses_are_normalized_to_application_states() -> None:
    assert normalize_worker_status("pending") == ("running", "agent_running")
    assert normalize_worker_status("running") == ("running", "agent_running")
    assert normalize_worker_status("success") == ("success", "completed")
    assert normalize_worker_status("timeout") == ("error", "failed")
    assert normalize_worker_status("interrupted") == ("interrupted", "interrupted")


def test_task_response_hides_internal_prefix_and_derives_retryability() -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={"class_name": "初一（1）班"},
        effective_scope={"class_name": "初一（1）班"},
        worker_thread_id=None,
        worker_run_id=None,
        status="error",
        stage="failed",
        status_message="Agent 服务暂不可用",
        result=None,
        result_prefix="内部确定性摘要",
        error_code="worker_unavailable",
        attempt_count=1,
        created_at=None,
        started_at=None,
        finished_at=None,
        updated_at=None,
    )

    response = task_response(task)

    assert response.scope.class_name == "初一（1）班"
    assert response.error_code == "worker_unavailable"
    assert response.can_retry is True
    assert "result_prefix" not in response.model_dump()


async def test_create_task_record_commits_owner_scopes_and_queued_state() -> None:
    session = SimpleNamespace(add=Mock(), commit=AsyncMock())
    user = SimpleNamespace(id=7, school_id=1)

    task = await task_service.create_task_record(
        session,
        user,
        "batch_report",
        {"class_name": "初一（1）班"},
        {"class_name": "初一（1）班", "subject_name": "数学"},
    )

    assert task.id
    assert task.user_id == 7
    assert task.school_id == 1
    assert task.requested_scope == {"class_name": "初一（1）班"}
    assert task.effective_scope == {
        "class_name": "初一（1）班",
        "subject_name": "数学",
    }
    assert task.status == "queued"
    assert task.stage == "collecting_evidence"
    assert task.attempt_count == 0
    session.add.assert_called_once_with(task)
    session.commit.assert_awaited_once()


async def test_submit_task_persists_worker_ids_and_first_attempt(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        status="queued",
        stage="collecting_evidence",
        status_message="正在准备任务",
        result=None,
        result_prefix=None,
        error_code=None,
        attempt_count=0,
    )
    session = SimpleNamespace(commit=AsyncMock())
    client = SimpleNamespace(
        threads=SimpleNamespace(
            create=AsyncMock(return_value={"thread_id": "thread-2"}),
        ),
        runs=SimpleNamespace(
            create=AsyncMock(return_value={"run_id": "run-2", "status": "pending"}),
        ),
    )
    monkeypatch.setattr(task_service, "get_client", lambda **_kwargs: client)

    response = await task_service.submit_task(
        session,
        task,
        "redacted evidence",
        result_prefix="确定性摘要",
    )

    assert response.task_id == "task-1"
    assert task.worker_thread_id == "thread-2"
    assert task.worker_run_id == "run-2"
    assert task.attempt_count == 1
    assert task.status == "running"
    assert task.stage == "agent_running"
    assert task.result_prefix == "确定性摘要"
    assert task.started_at is not None
    session.commit.assert_awaited()


async def test_successful_poll_persists_prefixed_redacted_result(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        worker_thread_id="thread-2",
        worker_run_id="run-2",
        status="running",
        stage="agent_running",
        status_message="Agent 正在生成报告",
        result=None,
        result_prefix="确定性摘要",
        error_code=None,
        attempt_count=1,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=task),
        commit=AsyncMock(),
    )
    client = SimpleNamespace(
        runs=SimpleNamespace(
            get=AsyncMock(return_value={"status": "success"}),
        ),
        threads=SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "values": {"messages": [{"role": "assistant", "content": "模型结果"}]}
                }
            ),
        ),
    )
    monkeypatch.setattr(task_service, "get_client", lambda **_kwargs: client)

    response = await task_service.get_task(
        session,
        SimpleNamespace(id=7, school_id=1),
        "task-1",
    )

    assert response.status == "success"
    assert response.stage == "completed"
    assert response.result == "确定性摘要\n\n模型结果"
    assert task.result == "确定性摘要\n\n模型结果"
    assert task.finished_at is not None
    session.commit.assert_awaited()


async def test_worker_404_marks_running_task_interrupted(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        worker_thread_id="missing-thread",
        worker_run_id="missing-run",
        status="running",
        stage="agent_running",
        status_message="Agent 正在生成报告",
        result=None,
        result_prefix=None,
        error_code=None,
        attempt_count=1,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=task),
        commit=AsyncMock(),
    )
    request = httpx.Request("GET", "http://agent-worker/runs/missing-run")
    response = httpx.Response(404, request=request)
    client = SimpleNamespace(
        runs=SimpleNamespace(
            get=AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "missing",
                    request=request,
                    response=response,
                )
            )
        )
    )
    monkeypatch.setattr(task_service, "get_client", lambda **_kwargs: client)

    result = await task_service.get_task(
        session,
        SimpleNamespace(id=7, school_id=1),
        "task-1",
    )

    assert result.status == "interrupted"
    assert result.stage == "interrupted"
    assert result.error_code == "worker_state_missing"
    assert result.can_retry is True
    assert task.finished_at is not None
    session.commit.assert_awaited_once()


async def test_temporary_worker_failure_preserves_running_state(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        worker_thread_id="thread-2",
        worker_run_id="run-2",
        status="running",
        stage="agent_running",
        status_message="Agent 正在生成报告",
        result=None,
        result_prefix=None,
        error_code=None,
        attempt_count=1,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=task),
        commit=AsyncMock(),
    )
    client = SimpleNamespace(
        runs=SimpleNamespace(get=AsyncMock(side_effect=httpx.ConnectError("offline")))
    )
    monkeypatch.setattr(task_service, "get_client", lambda **_kwargs: client)

    try:
        await task_service.get_task(
            session,
            SimpleNamespace(id=7, school_id=1),
            "task-1",
        )
    except httpx.ConnectError:
        pass
    else:
        raise AssertionError("temporary worker failure must propagate")

    assert task.status == "running"
    assert task.error_code is None
    session.commit.assert_not_awaited()


async def test_user_cannot_load_another_users_task() -> None:
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))

    try:
        await task_service.load_owned_task(
            session,
            SimpleNamespace(id=8, school_id=1),
            "task-1",
        )
    except KeyError as exc:
        assert exc.args == ("task-1",)
    else:
        raise AssertionError("another user's task must not be returned")


async def test_list_tasks_returns_owned_rows_in_database_order() -> None:
    older = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        status="success",
        stage="completed",
        status_message="任务已完成",
        result="older",
        result_prefix=None,
        error_code=None,
        attempt_count=1,
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    newer = AgentTask(
        id="task-2",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        status="success",
        stage="completed",
        status_message="任务已完成",
        result="newer",
        result_prefix=None,
        error_code=None,
        attempt_count=1,
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    rows = SimpleNamespace(all=lambda: [newer, older])
    session = SimpleNamespace(scalars=AsyncMock(return_value=rows))

    result = await task_service.list_tasks(
        session,
        SimpleNamespace(id=7, school_id=1),
    )

    assert [item.task_id for item in result] == ["task-2", "task-1"]
    assert [item.result for item in result] == ["newer", "older"]


async def test_retry_rejects_running_task_before_worker_submission(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        worker_thread_id="thread-1",
        worker_run_id="run-1",
        status="running",
        stage="agent_running",
        status_message="Agent 正在生成报告",
        result=None,
        result_prefix=None,
        error_code=None,
        attempt_count=1,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=task),
        commit=AsyncMock(),
    )
    create_thread = AsyncMock(return_value={"thread_id": "thread-2"})
    monkeypatch.setattr(
        task_service,
        "get_client",
        lambda **_kwargs: SimpleNamespace(
            threads=SimpleNamespace(create=create_thread),
        ),
    )

    try:
        await task_service.retry_task(
            session,
            SimpleNamespace(id=7, school_id=1),
            "task-1",
            "redacted evidence",
            {},
        )
    except task_service.InvalidTaskTransition as exc:
        assert str(exc) == "任务当前不可重试"
    else:
        raise AssertionError("running task must not be retried")

    create_thread.assert_not_awaited()
    assert task.attempt_count == 1
    session.commit.assert_not_awaited()


async def test_retry_reuses_application_id_and_increments_attempt(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={"class_name": "初一（1）班"},
        effective_scope={"class_name": "初一（1）班"},
        worker_thread_id="missing-thread",
        worker_run_id="missing-run",
        status="interrupted",
        stage="interrupted",
        status_message="Agent 运行环境已重启，可重新执行",
        result=None,
        result_prefix=None,
        error_code="worker_state_missing",
        attempt_count=1,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=task),
        commit=AsyncMock(),
    )
    client = SimpleNamespace(
        threads=SimpleNamespace(
            create=AsyncMock(return_value={"thread_id": "thread-2"}),
        ),
        runs=SimpleNamespace(
            create=AsyncMock(return_value={"run_id": "run-2", "status": "pending"}),
        ),
    )
    monkeypatch.setattr(task_service, "get_client", lambda **_kwargs: client)

    result = await task_service.retry_task(
        session,
        SimpleNamespace(id=7, school_id=1),
        "task-1",
        "new redacted evidence",
        {"class_name": "初一（1）班", "subject_name": "数学"},
    )

    assert result.task_id == "task-1"
    assert result.attempt_count == 2
    assert result.run_id == "run-2"
    assert result.status == "running"
    assert result.scope.subject_name == "数学"
    assert task.worker_thread_id == "thread-2"
    assert task.error_code is None


async def test_fail_task_persists_only_safe_error_details() -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        status="queued",
        stage="submitting",
        status_message="正在提交 Agent",
        result=None,
        result_prefix=None,
        error_code=None,
        attempt_count=1,
    )
    session = SimpleNamespace(commit=AsyncMock())

    result = await task_service.fail_task(
        session,
        task,
        "worker_unavailable",
        "Agent 服务暂不可用，可稍后重新执行",
    )

    assert result.status == "error"
    assert result.stage == "failed"
    assert result.error_code == "worker_unavailable"
    assert result.status_message == "Agent 服务暂不可用，可稍后重新执行"
    assert result.can_retry is True
    assert task.finished_at is not None
    session.commit.assert_awaited_once()


async def test_cancel_task_persists_cancelled_state_after_worker_accepts(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        worker_thread_id="thread-1",
        worker_run_id="run-1",
        status="running",
        stage="agent_running",
        status_message="Agent 正在生成报告",
        result=None,
        result_prefix=None,
        error_code=None,
        attempt_count=1,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=task),
        commit=AsyncMock(),
    )
    cancel = AsyncMock()
    monkeypatch.setattr(
        task_service,
        "get_client",
        lambda **_kwargs: SimpleNamespace(runs=SimpleNamespace(cancel=cancel)),
    )

    result = await task_service.cancel_task(
        session,
        SimpleNamespace(id=7, school_id=1),
        "task-1",
    )

    assert result.status == "cancelled"
    assert result.stage == "cancelled"
    assert task.finished_at is not None
    cancel.assert_awaited_once_with(thread_id="thread-1", run_id="run-1")
    session.commit.assert_awaited_once()


async def test_update_task_reuses_thread_and_replaces_running_attempt(monkeypatch) -> None:
    task = AgentTask(
        id="task-1",
        school_id=1,
        user_id=7,
        task_type="batch_report",
        requested_scope={},
        effective_scope={},
        worker_thread_id="thread-1",
        worker_run_id="run-1",
        status="running",
        stage="agent_running",
        status_message="Agent 正在生成报告",
        result="stale result",
        result_prefix=None,
        error_code=None,
        attempt_count=1,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=task),
        commit=AsyncMock(),
    )
    create_run = AsyncMock(return_value={"run_id": "run-2", "status": "pending"})
    monkeypatch.setattr(
        task_service,
        "get_client",
        lambda **_kwargs: SimpleNamespace(runs=SimpleNamespace(create=create_run)),
    )

    result = await task_service.update_task(
        session,
        SimpleNamespace(id=7, school_id=1),
        "task-1",
        "按班级分组",
    )

    assert result.task_id == "task-1"
    assert result.run_id == "run-2"
    assert result.status == "running"
    assert result.attempt_count == 2
    assert result.result is None
    create_run.assert_awaited_once_with(
        thread_id="thread-1",
        assistant_id="batch-report",
        input={"messages": [{"role": "user", "content": "按班级分组"}]},
        multitask_strategy="interrupt",
    )
    session.commit.assert_awaited_once()
