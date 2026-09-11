from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.api import auth as auth_api
from app.core.models import UserRole
from app.core.schemas import LoginRequest
from app.services.login_rate_limit import LoginRateLimiter, RateLimitState


class MemoryLimiter:
    def __init__(self, count: int = 0) -> None:
        self.count = count

    async def status(self, _client_ip: str, _username: str) -> RateLimitState:
        return RateLimitState(self.count >= 5, 60 if self.count >= 5 else 0)

    async def record_failure(self, _client_ip: str, _username: str) -> RateLimitState:
        self.count += 1
        return RateLimitState(self.count >= 5, 60 if self.count >= 5 else 0)

    async def clear(self, _client_ip: str, _username: str) -> None:
        self.count = 0


class BrokenRedis:
    async def eval(self, *_args) -> list[int]:
        raise RedisError("redis unavailable")

    async def delete(self, *_args) -> None:
        raise RedisError("redis unavailable")


def _request() -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host="10.0.0.4"))


def _payload(password: str = "bad-password") -> LoginRequest:
    return LoginRequest(username="academic01", password=password)


def _valid_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        school_id=1,
        username="academic01",
        role=UserRole.ACADEMIC_ADMIN,
        password_hash="stored-hash",
        student=None,
        teacher=None,
    )


async def test_login_returns_429_before_database_work_when_already_limited(
    monkeypatch,
) -> None:
    limiter = MemoryLimiter(count=5)
    session = SimpleNamespace(scalar=AsyncMock())
    monkeypatch.setattr(auth_api, "login_rate_limiter", limiter, raising=False)

    with pytest.raises(HTTPException) as error:
        await auth_api.login(_request(), _payload(), session)

    assert error.value.status_code == 429
    assert error.value.detail == "登录尝试过于频繁，请稍后再试"
    assert error.value.headers == {"Retry-After": "60"}
    session.scalar.assert_not_awaited()


async def test_fifth_invalid_login_changes_generic_401_to_429(monkeypatch) -> None:
    limiter = MemoryLimiter()
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    monkeypatch.setattr(auth_api, "login_rate_limiter", limiter, raising=False)
    outcomes: list[tuple[int, str]] = []

    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            await auth_api.login(_request(), _payload(), session)
        outcomes.append((error.value.status_code, error.value.detail))

    assert outcomes[:4] == [(401, "用户名或密码错误")] * 4
    assert outcomes[4] == (429, "登录尝试过于频繁，请稍后再试")


async def test_successful_login_clears_its_failure_counter(monkeypatch) -> None:
    limiter = MemoryLimiter(count=4)
    session = SimpleNamespace(scalar=AsyncMock(return_value=_valid_user()))
    monkeypatch.setattr(auth_api, "login_rate_limiter", limiter, raising=False)
    monkeypatch.setattr(auth_api, "verify_password", lambda *_args: True)

    response = await auth_api.login(_request(), _payload("GradeWise123!"), session)

    assert response.user.username == "academic01"
    assert response.access_token
    assert limiter.count == 0


async def test_redis_outage_does_not_replace_valid_authentication(monkeypatch) -> None:
    limiter = LoginRateLimiter(
        redis=BrokenRedis(),
        max_failures=5,
        window_seconds=60,
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=_valid_user()))
    monkeypatch.setattr(auth_api, "login_rate_limiter", limiter, raising=False)
    monkeypatch.setattr(auth_api, "verify_password", lambda *_args: True)

    response = await auth_api.login(_request(), _payload("GradeWise123!"), session)

    assert response.access_token
    assert response.user.username == "academic01"
