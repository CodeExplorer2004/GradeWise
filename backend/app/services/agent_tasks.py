from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from langgraph_sdk import get_client

from app.core.config import get_settings
from app.core.schemas import AgentTaskResponse
from app.services.conversation_memory import conversation_memory

settings = get_settings()
GRAPH_IDS = {"batch_report": "batch-report", "batch_warning": "batch-warning"}
TERMINAL_STATUSES = {"success", "error", "cancelled", "interrupted"}


def _key(user_id: int, task_id: str) -> str:
    return f"gradewise:agent-task:{user_id}:{task_id}"


async def _load(user_id: int, task_id: str) -> dict[str, Any]:
    raw = await conversation_memory.redis.get(_key(user_id, task_id))
    if not raw:
        raise KeyError(task_id)
    return json.loads(raw)


async def _save(user_id: int, task: dict[str, Any]) -> None:
    await conversation_memory.redis.setex(
        _key(user_id, str(task["task_id"])),
        settings.conversation_ttl_seconds,
        json.dumps(task, ensure_ascii=False),
    )


async def start_task(
    user_id: int,
    task_type: str,
    description: str,
    scope: dict[str, str | None] | None = None,
    result_prefix: str | None = None,
) -> AgentTaskResponse:
    client = get_client(url=settings.agent_protocol_url)
    thread = await client.threads.create()
    run = await client.runs.create(
        thread_id=thread["thread_id"],
        assistant_id=GRAPH_IDS[task_type],
        input={"messages": [{"role": "user", "content": description}]},
    )
    task = {
        "task_id": thread["thread_id"],
        "run_id": run["run_id"],
        "task_type": task_type,
        "scope": scope or {},
        "created_at": datetime.now(UTC).isoformat(),
        "status": run["status"],
        "result": None,
        "result_prefix": result_prefix,
    }
    await _save(user_id, task)
    return AgentTaskResponse(**task)


async def get_task(user_id: int, task_id: str) -> AgentTaskResponse:
    task = await _load(user_id, task_id)
    if task.get("status") in TERMINAL_STATUSES:
        return AgentTaskResponse(**task)
    client = get_client(url=settings.agent_protocol_url)
    run = await client.runs.get(thread_id=task_id, run_id=task["run_id"])
    result_text: str | None = None
    if run["status"] == "success":
        thread = await client.threads.get(thread_id=task_id)
        messages = (thread.get("values") or {}).get("messages", [])
        if messages:
            last = messages[-1]
            result_text = last.get("content", "") if isinstance(last, dict) else str(last)
            if task.get("result_prefix"):
                result_text = f"{task['result_prefix']}\n\n{result_text}"
    task["status"] = run["status"]
    task["result"] = result_text
    await _save(user_id, task)
    return AgentTaskResponse(**task)


async def list_tasks(user_id: int) -> list[AgentTaskResponse]:
    tasks: list[AgentTaskResponse] = []
    async for key in conversation_memory.redis.scan_iter(
        match=f"gradewise:agent-task:{user_id}:*", count=100
    ):
        task_id = str(key).rsplit(":", 1)[-1]
        try:
            tasks.append(await get_task(user_id, task_id))
        except Exception:
            continue
    return sorted(tasks, key=lambda item: item.created_at or "", reverse=True)


async def update_task(user_id: int, task_id: str, message: str) -> AgentTaskResponse:
    task = await _load(user_id, task_id)
    client = get_client(url=settings.agent_protocol_url)
    run = await client.runs.create(
        thread_id=task_id,
        assistant_id=GRAPH_IDS[task["task_type"]],
        input={"messages": [{"role": "user", "content": message}]},
        multitask_strategy="interrupt",
    )
    task["run_id"] = run["run_id"]
    task["status"] = run["status"]
    task["result"] = None
    await _save(user_id, task)
    return AgentTaskResponse(**task)


async def cancel_task(user_id: int, task_id: str) -> AgentTaskResponse:
    task = await _load(user_id, task_id)
    client = get_client(url=settings.agent_protocol_url)
    await client.runs.cancel(thread_id=task_id, run_id=task["run_id"])
    task["status"] = "cancelled"
    await _save(user_id, task)
    return AgentTaskResponse(**task)
