from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.models import User, UserRole
from app.core.schemas import ImportResult
from app.services.score_import import import_scores

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/scores", response_model=ImportResult)
async def upload_scores(
    file: Annotated[UploadFile, File()],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ImportResult:
    if current_user.role != UserRole.ACADEMIC_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅教务管理员可以导入成绩",
        )
    try:
        content = await file.read()
        return await import_scores(session, current_user, file.filename or "scores.csv", content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    finally:
        await file.close()
