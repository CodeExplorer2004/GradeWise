from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from langgraph_sdk import get_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.models import AgentTask
from app.core.schemas import AgentTaskResponse

settings = get_settings()
GRAPH_IDS = {"batch_report": "batch-report", "batch_warning": "batch-warning"}
TERMINAL_STATUSES = {"success", "error", "cancelled", "interrupted"}
RETRYABLE_STATUSES = {"error", "interrupted"}
WORKER_STATUS_MAP = {
    "pending": ("running", "agent_running"),
    "running": ("running", "agent_running"),
    "success": ("success", "completed"),
    "error": ("error", "failed"),
    "timeout": ("error", "failed"),
    "cancelled": ("cancelled", "cancelled"),
    "interrupted": ("interrupted", "interrupted"),
}


class InvalidTaskTransition(ValueError):
    pass


def normalize_worker_status(status: str) -> tuple[str, str]:
    return WORKER_STATUS_MAP.get(status, ("running", "agent_running"))


def task_response(task: AgentTask) -> AgentTaskResponse:
    return AgentTaskResponse(
        task_id=task.id,
        run_id=task.worker_run_id,
        task_type=task.task_type,
        status=task.status,
        stage=task.stage,
        status_message=task.status_message,
        result=task.result,
        scope=task.effective_scope or task.requested_scope or {},
        requested_scope=task.requested_scope or {},
        error_code=task.error_code,
        attempt_count=task.attempt_count,
        can_retry=task.status in RETRYABLE_STATUSES,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        updated_at=task.updated_at,
    )


async def create_task_record(
    session: AsyncSession,
    user: Any,
    task_type: str,
    requested_scope: dict[str, Any],
    effective_scope: dict[str, Any],
    result_prefix: str | None = None,
) -> AgentTask:
    task = AgentTask(
        id=str(uuid4()),
        school_id=user.school_id,
        user_id=user.id,
        task_type=task_type,
        requested_scope=requested_scope,
        effective_scope=effective_scope,
        status="queued",
        stage="collecting_evidence",
        status_message="正在准备任务",
        result_prefix=result_prefix,
        attempt_count=0,
    )
    session.add(task)
    await session.commit()
    return task


async def submit_task(
    session: AsyncSession,
    task: AgentTask,
    description: str,
    result_prefix: str | None = None,
) -> AgentTaskResponse:
    task.status = "queued"
    task.stage = "submitting"
    task.status_message = "正在提交 Agent"
    task.result_prefix = result_prefix
    task.result = None
    task.error_code = None
    task.finished_at = None
    task.started_at = datetime.now(UTC)
    task.attempt_count += 1
    await session.commit()

    client = get_client(url=settings.agent_protocol_url)
    thread = await client.threads.create()
    run = await client.runs.create(
        thread_id=thread["thread_id"],
        assistant_id=GRAPH_IDS[task.task_type],
        input={"messages": [{"role": "user", "content": description}]},
    )
    task.worker_thread_id = thread["thread_id"]
    task.worker_run_id = run["run_id"]
    task.status, task.stage = normalize_worker_status(run["status"])
    task.status_message = (
        "Agent 正在生成报告" if task.status == "running" else "Agent 任务已完成"
    )
    await session.commit()
    return task_response(task)


async def load_owned_task(
    session: AsyncSession,
    user: Any,
    task_id: str,
    *,
    for_update: bool = False,
) -> AgentTask:
    statement = select(AgentTask).where(
        AgentTask.id == task_id,
        AgentTask.user_id == user.id,
        AgentTask.school_id == user.school_id,
    )
    if for_update:
        statement = statement.with_for_update()
    task = await session.scalar(statement)
    if task is None:
        raise KeyError(task_id)
    return task


async def get_task(
    session: AsyncSession,
    user: Any,
    task_id: str,
) -> AgentTaskResponse:
    task = await load_owned_task(session, user, task_id)
    if task.status in TERMINAL_STATUSES or task.status == "queued":
        return task_response(task)
    client = get_client(url=settings.agent_protocol_url)
    try:
        run = await client.runs.get(
            thread_id=task.worker_thread_id,
            run_id=task.worker_run_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        task.status = "interrupted"
        task.stage = "interrupted"
        task.status_message = "Agent 运行环境已重启，可重新执行"
        task.error_code = "worker_state_missing"
        task.finished_at = datetime.now(UTC)
        await session.commit()
        return task_response(task)
    result_text: str | None = None
    if run["status"] == "success":
        task.stage = "saving_result"
        task.status_message = "正在保存 Agent 结果"
        thread = await client.threads.get(thread_id=task.worker_thread_id)
        messages = (thread.get("values") or {}).get("messages", [])
        if messages:
            last = messages[-1]
            result_text = last.get("content", "") if isinstance(last, dict) else str(last)
            if task.result_prefix:
                result_text = f"{task.result_prefix}\n\n{result_text}"
    task.status, task.stage = normalize_worker_status(run["status"])
    task.result = result_text
    if task.status == "success":
        task.status_message = "任务已完成"
        task.finished_at = datetime.now(UTC)
    elif task.status == "running":
        task.status_message = "Agent 正在生成报告"
    else:
        task.status_message = "Agent 任务执行失败"
        task.error_code = "worker_run_failed"
        task.finished_at = datetime.now(UTC)
    await session.commit()
    return task_response(task)


async def list_tasks(
    session: AsyncSession,
    user: Any,
) -> list[AgentTaskResponse]:
    statement = (
        select(AgentTask)
        .where(
            AgentTask.user_id == user.id,
            AgentTask.school_id == user.school_id,
        )
        .order_by(AgentTask.created_at.desc())
    )
    rows = await session.scalars(statement)
    return [task_response(task) for task in rows.all()]


async def retry_task(
    session: AsyncSession,
    user: Any,
    task_id: str,
    description: str,
    effective_scope: dict[str, Any],
    result_prefix: str | None = None,
) -> AgentTaskResponse:
    task = await load_owned_task(session, user, task_id, for_update=True)
    if task.status not in RETRYABLE_STATUSES:
        raise InvalidTaskTransition("任务当前不可重试")
    task.effective_scope = effective_scope
    task.worker_thread_id = None
    task.worker_run_id = None
    task.result = None
    task.error_code = None
    task.status = "queued"
    task.stage = "collecting_evidence"
    task.status_message = "正在重新准备任务"
    task.finished_at = None
    return await submit_task(session, task, description, result_prefix)


async def fail_task(
    session: AsyncSession,
    task: AgentTask,
    error_code: str,
    status_message: str,
) -> AgentTaskResponse:
    task.status = "error"
    task.stage = "failed"
    task.status_message = status_message
    task.error_code = error_code
    task.finished_at = datetime.now(UTC)
    await session.commit()
    return task_response(task)


async def update_task(
    session: AsyncSession,
    user: Any,
    task_id: str,
    message: str,
) -> AgentTaskResponse:
    task = await load_owned_task(session, user, task_id, for_update=True)
    if task.status != "running" or not task.worker_thread_id:
        raise InvalidTaskTransition("任务当前不能追加要求")
    client = get_client(url=settings.agent_protocol_url)
    run = await client.runs.create(
        thread_id=task.worker_thread_id,
        assistant_id=GRAPH_IDS[task.task_type],
        input={"messages": [{"role": "user", "content": message}]},
        multitask_strategy="interrupt",
    )
    task.worker_run_id = run["run_id"]
    task.status, task.stage = normalize_worker_status(run["status"])
    task.status_message = "Agent 正在处理补充要求"
    task.result = None
    task.error_code = None
    task.attempt_count += 1
    task.started_at = datetime.now(UTC)
    task.finished_at = None
    await session.commit()
    return task_response(task)


async def cancel_task(
    session: AsyncSession,
    user: Any,
    task_id: str,
) -> AgentTaskResponse:
    task = await load_owned_task(session, user, task_id, for_update=True)
    if task.status in TERMINAL_STATUSES:
        raise InvalidTaskTransition("任务当前不可取消")
    if task.worker_thread_id and task.worker_run_id:
        client = get_client(url=settings.agent_protocol_url)
        await client.runs.cancel(
            thread_id=task.worker_thread_id,
            run_id=task.worker_run_id,
        )
    task.status = "cancelled"
    task.stage = "cancelled"
    task.status_message = "任务已取消"
    task.finished_at = datetime.now(UTC)
    await session.commit()
    return task_response(task)
