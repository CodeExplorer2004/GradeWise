from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.query_graph import query_graph
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.models import Conversation, Exam, SchoolClass, Subject, User
from app.core.schemas import (
    ChartSpec,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConversationHistory,
    ConversationSummary,
)
from app.services.achievement_overview import build_student_achievement_overview
from app.services.analysis_scope import validate_scope
from app.services.conversation_memory import conversation_memory

router = APIRouter(prefix="/chat", tags=["chat"])


async def _owned_conversation(
    conversation_id: str, user: User, session: AsyncSession
) -> Conversation:
    try:
        UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="conversation_id 格式错误") from None
    conversation = await session.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


async def _catalog(session: AsyncSession, school_id: int) -> dict[str, list[str]]:
    classes = list(
        (
            await session.scalars(
                select(SchoolClass.name).where(SchoolClass.school_id == school_id)
            )
        ).all()
    )
    exams = list(
        (await session.scalars(select(Exam.name).where(Exam.school_id == school_id))).all()
    )
    subjects = list(
        (await session.scalars(select(Subject.name).where(Subject.school_id == school_id))).all()
    )
    return {"classes": classes, "exams": exams, "subjects": subjects}


async def _conversation_id(
    requested: str | None, user: User, session: AsyncSession, title: str
) -> str:
    if requested:
        await _owned_conversation(requested, user, session)
        return requested
    conversation_id = str(uuid4())
    session.add(
        Conversation(id=conversation_id, user_id=user.id, title=title[:80] or "新对话")
    )
    await session.commit()
    return conversation_id


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ConversationSummary]:
    conversations = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
            .limit(50)
        )
    ).all()
    return [ConversationSummary.model_validate(item) for item in conversations]


@router.get("/{conversation_id}/messages", response_model=ConversationHistory)
async def conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ConversationHistory:
    await _owned_conversation(conversation_id, current_user, session)
    messages = await conversation_memory.get(current_user.id, conversation_id)
    return ConversationHistory(
        conversation_id=conversation_id,
        messages=[ChatMessage.model_validate(message) for message in messages],
    )


@router.post("/query", response_model=ChatResponse)
async def query(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ChatResponse:
    analysis_filters = await validate_scope(current_user, payload.scope)
    conversation_id = await _conversation_id(
        payload.conversation_id, current_user, session, payload.message
    )
    stored_history = await conversation_memory.get(current_user.id, conversation_id)
    history = [
        {"role": item["role"], "content": item["content"]}
        for item in stored_history
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    state = await query_graph.ainvoke(
        {
            "question": payload.message,
            "history": history,
            "catalog": await _catalog(session, current_user.school_id),
            "user": current_user,
            "analysis_filters": analysis_filters,
        }
    )
    validation = state["validation"]
    audit = state["audit"].model_dump()
    audit["deterministic_allowed"] = validation.allowed
    chart = state.get("chart")
    chart_spec = ChartSpec.model_validate(chart.model_dump()) if chart else None
    student_overview = await build_student_achievement_overview(
        current_user, state.get("rows", [])
    )
    await conversation_memory.append(current_user.id, conversation_id, "user", payload.message)
    await conversation_memory.append(
        current_user.id,
        conversation_id,
        "assistant",
        state["answer"],
        sql=validation.display_sql if validation.allowed else None,
        rows=state.get("rows", []),
        chart=chart_spec.model_dump() if chart_spec else None,
        student_overview=(student_overview.model_dump() if student_overview else None),
        allowed=validation.allowed,
    )
    conversation = await session.get(Conversation, conversation_id)
    if conversation:
        conversation.updated_at = datetime.now(UTC)
        await session.commit()
    return ChatResponse(
        conversation_id=conversation_id,
        answer=state["answer"],
        sql=validation.display_sql if validation.allowed else None,
        rows=state.get("rows", []),
        chart=chart_spec,
        student_overview=student_overview,
        audit=audit,
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    conversation = await _owned_conversation(conversation_id, current_user, session)
    await session.delete(conversation)
    await session.commit()
    await conversation_memory.delete(current_user.id, conversation_id)
