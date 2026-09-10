from datetime import UTC, datetime

from app.core.models import AgentTask
from app.core.schemas import AgentTaskResponse


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
