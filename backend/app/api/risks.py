from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_analysis_scope, get_current_user
from app.core.database import get_db
from app.core.models import User, UserRole
from app.core.schemas import AnalysisScope, RiskSummaryResponse
from app.services.analysis_scope import validate_scope
from app.services.risk_prediction import (
    collect_risk_predictions,
    persist_risk_snapshots,
    risk_summary,
)

router = APIRouter(prefix="/risks", tags=["risks"])


@router.get("/summary", response_model=RiskSummaryResponse)
async def get_risk_summary(
    scope: AnalysisScope = Depends(get_analysis_scope),
    current_user: User = Depends(get_current_user),
) -> RiskSummaryResponse:
    filters = await validate_scope(current_user, scope)
    return risk_summary(await collect_risk_predictions(current_user, filters))


@router.post("/refresh", response_model=RiskSummaryResponse)
async def refresh_risk_snapshots(
    scope: AnalysisScope = Depends(get_analysis_scope),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RiskSummaryResponse:
    if current_user.role != UserRole.ACADEMIC_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅教务管理员可以刷新全校风险快照",
        )
    filters = await validate_scope(current_user, scope)
    predictions = await collect_risk_predictions(current_user, filters)
    await persist_risk_snapshots(session, current_user.school_id, predictions)
    return risk_summary(predictions)
