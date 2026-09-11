from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

settings = get_settings()
logger = structlog.get_logger(__name__)

_STATUS_SCRIPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

_FAILURE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


class RedisLike(Protocol):
    async def eval(
        self,
        script: str,
        key_count: int,
        key: str,
        *arguments: int,
    ) -> Any: ...

    async def delete(self, key: str) -> Any: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class RateLimitState:
    limited: bool
    retry_after: int


class LoginRateLimiter:
    def __init__(
        self,
        redis: RedisLike,
        max_failures: int,
        window_seconds: int,
    ) -> None:
        self.redis = redis
        self.max_failures = max_failures
        self.window_seconds = window_seconds

    @staticmethod
    def _key(client_ip: str, username: str) -> str:
        normalized = f"{client_ip}\0{username.strip().casefold()}"
        digest = sha256(normalized.encode("utf-8")).hexdigest()
        return f"gradewise:login-fail:{digest}"

    def _state(self, raw: Any) -> RateLimitState:
        count, ttl = (int(raw[0]), int(raw[1]))
        limited = count >= self.max_failures
        retry_after = max(ttl, 1) if limited else 0
        return RateLimitState(limited=limited, retry_after=retry_after)

    async def status(self, client_ip: str, username: str) -> RateLimitState:
        try:
            raw = await self.redis.eval(
                _STATUS_SCRIPT,
                1,
                self._key(client_ip, username),
            )
        except RedisError:
            logger.warning("login_rate_limit_unavailable", operation="status")
            return RateLimitState(False, 0)
        return self._state(raw)

    async def record_failure(self, client_ip: str, username: str) -> RateLimitState:
        try:
            raw = await self.redis.eval(
                _FAILURE_SCRIPT,
                1,
                self._key(client_ip, username),
                self.window_seconds,
            )
        except RedisError:
            logger.warning("login_rate_limit_unavailable", operation="record_failure")
            return RateLimitState(False, 0)
        return self._state(raw)

    async def clear(self, client_ip: str, username: str) -> None:
        try:
            await self.redis.delete(self._key(client_ip, username))
        except RedisError:
            logger.warning("login_rate_limit_unavailable", operation="clear")


login_rate_limiter = LoginRateLimiter(
    redis=Redis.from_url(settings.redis_url, decode_responses=True),
    max_failures=settings.login_max_failures,
    window_seconds=settings.login_window_seconds,
)
