import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.models import User
from app.core.schemas import AnalysisScope
from app.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已过期，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise unauthorized
    try:
        user_id = decode_token(credentials.credentials, "access")
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None
    user = await session.scalar(
        select(User)
        .options(selectinload(User.student), selectinload(User.teacher))
        .where(User.id == user_id, User.active.is_(True))
    )
    if not user:
        raise unauthorized
    return user


def user_display_name(user: User) -> str:
    if user.student:
        return user.student.display_name
    if user.teacher:
        return user.teacher.display_name
    return user.username


def get_analysis_scope(
    academic_year: str | None = Query(default=None, max_length=20),
    grade_level: str | None = Query(default=None, max_length=40),
    term: str | None = Query(default=None, max_length=20),
    exam_type: str | None = Query(default=None, max_length=30),
    cohort_year: int | None = Query(default=None, ge=1900, le=2200),
    class_name: str | None = Query(default=None, max_length=80),
    subject_name: str | None = Query(default=None, max_length=80),
    exam_name: str | None = Query(default=None, max_length=120),
) -> AnalysisScope:
    return AnalysisScope(
        academic_year=academic_year,
        grade_level=grade_level,
        term=term,
        exam_type=exam_type,
        cohort_year=cohort_year,
        class_name=class_name,
        subject_name=subject_name,
        exam_name=exam_name,
    )
