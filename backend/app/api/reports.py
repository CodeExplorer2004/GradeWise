from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.factory import registry
from app.agents.report_graph import report_graph
from app.api.deps import get_current_user
from app.core.models import User, UserRole
from app.core.schemas import ReportRequest, ReportResponse
from app.services.analysis_scope import validate_scope
from app.services.learning_insights import collect_learning_insights, insights_for_llm

router = APIRouter(prefix="/reports", tags=["reports"])


def _resolve_report_type(payload: ReportRequest, user: User) -> str:
    is_student = user.role == UserRole.STUDENT
    if payload.report_type == "auto":
        return "student" if is_student else "scope_brief"
    if payload.report_type == "student" and not is_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前版本仅支持学生生成本人成绩报告",
        )
    if payload.report_type == "scope_brief" and is_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="学生账号无权生成班级或教学范围学情简报",
        )
    return payload.report_type


@router.post("/generate", response_model=ReportResponse)
async def generate_report(
    payload: ReportRequest,
    current_user: User = Depends(get_current_user),
) -> ReportResponse:
    report_type = _resolve_report_type(payload, current_user)
    filters = await validate_scope(current_user, payload.scope)
    insights = await collect_learning_insights(current_user, filters)
    state = await report_graph.ainvoke(
        {
            "report_type": report_type,
            "insights": insights_for_llm(insights),
        }
    )
    report = state["report"]
    warning = state["warning_analysis"]
    return ReportResponse(
        report_type=report_type,
        title="学生成绩报告" if report_type == "student" else "当前筛选范围学情简报",
        overview=report.overview,
        highlights=report.highlights,
        concerns=report.concerns,
        recommendations=report.recommendations,
        ai_comment=report.ai_comment,
        warning_summary=warning.summary,
        generated_by=registry.settings.llm_provider if registry.enabled else "fallback",
    )
