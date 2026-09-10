import json
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.models import User, UserRole
from app.core.schemas import (
    AgentTaskOptions,
    AgentTaskRequest,
    AgentTaskResponse,
    AgentTaskScope,
    AgentTaskUpdate,
)
from app.services.agent_tasks import (
    InvalidTaskTransition,
    cancel_task,
    create_task_record,
    fail_task,
    get_task,
    list_tasks,
    load_owned_task,
    retry_task,
    submit_task,
    update_task,
)
from app.services.analysis_scope import validate_scope
from app.services.learning_insights import collect_learning_insights, insights_for_llm
from app.services.privacy import redact_student_identifiers, risk_batch_evidence
from app.services.risk_prediction import collect_risk_predictions
from app.services.sql_security import SQLSafetyGate, execute_scoped_query

router = APIRouter(prefix="/tasks", tags=["agent-tasks"])


@dataclass(frozen=True)
class TaskInput:
    description: str
    result_prefix: str | None


def _authorize(user: User, task_type: str) -> None:
    if user.role == UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="学生账号不能启动批量任务",
        )
    if task_type == "batch_warning" and user.role != UserRole.ACADEMIC_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅教务管理员可启动批量预警",
        )


async def _task_options(user: User) -> AgentTaskOptions:
    async def distinct(column: str, order_by: str) -> list[str]:
        validation = SQLSafetyGate().validate(
            f"SELECT DISTINCT {column} FROM score_facts ORDER BY {order_by}"
        )
        rows = await execute_scoped_query(user, validation)
        return [str(row[column]) for row in rows]

    return AgentTaskOptions(
        classes=await distinct("class_name", "class_name"),
        subjects=await distinct("subject_name", "subject_name"),
        exams=await distinct("exam_name", "exam_name"),
    )


async def _validated_scope(user: User, scope: AgentTaskScope) -> dict[str, str | int]:
    return await validate_scope(user, AgentTaskScope(**scope.model_dump()))


async def _build_task_input(
    user: User,
    task_type: str,
    effective_scope: dict[str, str | int],
) -> TaskInput:
    if task_type == "batch_report":
        evidence = insights_for_llm(await collect_learning_insights(user, effective_scope))
        result_prefix = None
    else:
        predictions = await collect_risk_predictions(user, effective_scope)
        evidence = risk_batch_evidence(predictions)
        summary = evidence["deterministic_summary"]
        result_prefix = (
            "确定性统计（以此为准）："
            f"共 {summary['total_predictions']} 条学生-科目风险记录，"
            f"高风险 {summary['high_count']} 条，中风险 {summary['medium_count']} 条，"
            f"低风险 {summary['low_count']} 条；"
            f"提供给模型解释的明细为 {summary['evidence_items_count']} 条。\n"
            "以下 AI 解释仅供人工复核，不构成新的风险证据或事实。"
        )
    description = json.dumps(
        {"task_type": task_type, "scope": effective_scope, "evidence": evidence},
        ensure_ascii=False,
        default=str,
    )
    return TaskInput(description, result_prefix)


@router.get("", response_model=list[AgentTaskResponse])
async def read_agent_tasks(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[AgentTaskResponse]:
    if current_user.role == UserRole.STUDENT:
        return []
    return await list_tasks(session, current_user)


@router.get("/options", response_model=AgentTaskOptions)
async def read_agent_task_options(
    current_user: User = Depends(get_current_user),
) -> AgentTaskOptions:
    if current_user.role == UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="学生账号不能启动批量任务")
    return await _task_options(current_user)


@router.post("", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_agent_task(
    payload: AgentTaskRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentTaskResponse:
    _authorize(current_user, payload.task_type)
    scope = await _validated_scope(current_user, payload.scope)
    if payload.task_type == "batch_warning" and scope.get("exam_name"):
        raise HTTPException(status_code=422, detail="风险任务不支持按单次考试过滤")
    task = await create_task_record(
        session,
        current_user,
        payload.task_type,
        payload.scope.model_dump(),
        scope,
    )
    try:
        task_input = await _build_task_input(current_user, payload.task_type, scope)
    except Exception:
        return await fail_task(
            session,
            task,
            "evidence_collection_failed",
            "任务数据准备失败，可稍后重新执行",
        )
    try:
        return await submit_task(
            session,
            task,
            task_input.description,
            task_input.result_prefix,
        )
    except httpx.HTTPError:
        return await fail_task(
            session,
            task,
            "worker_unavailable",
            "Agent 服务暂不可用，可稍后重新执行",
        )


@router.get("/{task_id}", response_model=AgentTaskResponse)
async def read_agent_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentTaskResponse:
    try:
        return await get_task(session, current_user, task_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from None
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法读取任务",
        ) from exc


@router.post("/{task_id}/retry", response_model=AgentTaskResponse)
async def retry_agent_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentTaskResponse:
    try:
        task = await load_owned_task(session, current_user, task_id)
        _authorize(current_user, task.task_type)
        requested_scope = AgentTaskScope(**task.requested_scope)
        effective_scope = await _validated_scope(current_user, requested_scope)
        task_input = await _build_task_input(current_user, task.task_type, effective_scope)
        return await retry_task(
            session,
            current_user,
            task_id,
            task_input.description,
            effective_scope,
            task_input.result_prefix,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from None
    except InvalidTaskTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent 服务暂不可用",
        ) from exc


@router.post("/{task_id}/update", response_model=AgentTaskResponse)
async def revise_agent_task(
    task_id: str,
    payload: AgentTaskUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentTaskResponse:
    try:
        message = await redact_student_identifiers(
            session, current_user.school_id, payload.message
        )
        return await update_task(session, current_user, task_id, message)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from None
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法更新任务",
        ) from exc


@router.delete("/{task_id}", response_model=AgentTaskResponse)
async def stop_agent_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentTaskResponse:
    try:
        return await cancel_task(session, current_user, task_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from None
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法取消任务",
        ) from exc
