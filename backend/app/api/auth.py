import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, user_display_name
from app.core.database import get_db
from app.core.models import User
from app.core.schemas import LoginRequest, RefreshRequest, TokenResponse, UserInfo
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.services.login_rate_limit import RateLimitState, login_rate_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many_attempts(state: RateLimitState) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="登录尝试过于频繁，请稍后再试",
        headers={"Retry-After": str(max(state.retry_after, 1))},
    )


def _user_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        role=user.role,
        school_id=user.school_id,
        display_name=user_display_name(user),
    )


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=_user_info(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    client_ip = _client_ip(request)
    limit_state = await login_rate_limiter.status(client_ip, payload.username)
    if limit_state.limited:
        raise _too_many_attempts(limit_state)
    user = await session.scalar(
        select(User)
        .options(selectinload(User.student), selectinload(User.teacher))
        .where(User.username == payload.username, User.active.is_(True))
    )
    if not user or not verify_password(payload.password, user.password_hash):
        limit_state = await login_rate_limiter.record_failure(client_ip, payload.username)
        if limit_state.limited:
            raise _too_many_attempts(limit_state)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    await login_rate_limiter.clear(client_ip, payload.username)
    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest, session: AsyncSession = Depends(get_db)
) -> TokenResponse:
    try:
        user_id = decode_token(payload.refresh_token, "refresh")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="刷新令牌无效") from None
    user = await session.scalar(
        select(User)
        .options(selectinload(User.student), selectinload(User.teacher))
        .where(User.id == user_id, User.active.is_(True))
    )
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return _token_response(user)


@router.get("/me", response_model=UserInfo)
async def me(current_user: User = Depends(get_current_user)) -> UserInfo:
    return _user_info(current_user)
