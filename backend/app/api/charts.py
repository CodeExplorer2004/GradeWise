import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.agents.contracts import VisualizationDraft
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.models import User
from app.core.schemas import ChartExportRequest
from app.services.chart_security import secure_chart

router = APIRouter(prefix="/charts", tags=["charts"])
settings = get_settings()


@router.post("/export.svg")
async def export_chart_svg(
    payload: ChartExportRequest,
    _: User = Depends(get_current_user),
) -> Response:
    secured = secure_chart(
        VisualizationDraft(type=payload.chart_type, title=payload.title, option=payload.option)
    )
    if secured.type == "none":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=secured.title or "图表配置未通过安全校验",
        )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{settings.chart_mcp_url.rstrip('/')}/render",
                headers={"Authorization": f"Bearer {settings.mcp_service_token}"},
                json={"option": secured.option, "width": 1200, "height": 700},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="图表 MCP 服务暂不可用",
        ) from exc
    filename = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]", "_", payload.title)[:60] or "chart"
    ascii_filename = re.sub(r"[^0-9A-Za-z_-]", "_", filename).strip("_") or "chart"
    content_disposition = (
        f'attachment; filename="{ascii_filename}.svg"; '
        f"filename*=UTF-8''{quote(f'{filename}.svg')}"
    )
    return Response(
        content=response.content,
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": content_disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
