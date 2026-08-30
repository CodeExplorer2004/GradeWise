from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_analysis_scope, get_current_user
from app.core.models import User
from app.core.schemas import AlertPageResponse, AnalysisScope, InsightsResponse
from app.services.analysis_scope import validate_scope
from app.services.learning_insights import collect_alert_page, collect_learning_insights

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/summary", response_model=InsightsResponse)
async def insight_summary(
    scope: AnalysisScope = Depends(get_analysis_scope),
    current_user: User = Depends(get_current_user),
) -> InsightsResponse:
    filters = await validate_scope(current_user, scope)
    return await collect_learning_insights(current_user, filters)


@router.get("/alerts", response_model=AlertPageResponse)
async def insight_alerts(
    alert_type: Literal["anomaly", "fluctuation", "current_risk"] = Query(alias="type"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    scope: AnalysisScope = Depends(get_analysis_scope),
    current_user: User = Depends(get_current_user),
) -> AlertPageResponse:
    filters = await validate_scope(current_user, scope)
    return await collect_alert_page(current_user, alert_type, page, page_size, filters)
