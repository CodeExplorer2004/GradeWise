from redis.exceptions import RedisError

from app.services.login_rate_limit import LoginRateLimiter, RateLimitState


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    @property
    def keys(self) -> list[str]:
        return list(self.values)

    async def eval(
        self,
        _script: str,
        _key_count: int,
        key: str,
        *arguments: int,
    ) -> list[int]:
        if arguments:
            self.values[key] = self.values.get(key, 0) + 1
            self.ttls.setdefault(key, int(arguments[0]))
        return [self.values.get(key, 0), self.ttls.get(key, -2)]

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)


class BrokenRedis:
    async def eval(self, *_args) -> list[int]:
        raise RedisError("redis unavailable")

    async def delete(self, *_args) -> None:
        raise RedisError("redis unavailable")


async def test_fifth_failure_is_limited_for_same_client_and_username() -> None:
    limiter = LoginRateLimiter(
        redis=FakeRedis(),
        max_failures=5,
        window_seconds=60,
    )

    states = [
        await limiter.record_failure("10.0.0.4", " Academic01 ")
        for _ in range(5)
    ]

    assert [state.limited for state in states] == [False, False, False, False, True]
    assert states[-1].retry_after == 60


async def test_counters_are_isolated_and_keys_hide_identity() -> None:
    redis = FakeRedis()
    limiter = LoginRateLimiter(redis=redis, max_failures=2, window_seconds=60)

    await limiter.record_failure("10.0.0.4", "academic01")

    assert (await limiter.status("10.0.0.5", "academic01")).limited is False
    assert (await limiter.status("10.0.0.4", "teacher01")).limited is False
    assert all("academic01" not in key and "10.0.0.4" not in key for key in redis.keys)


async def test_clear_removes_only_the_successful_identity_counter() -> None:
    redis = FakeRedis()
    limiter = LoginRateLimiter(redis=redis, max_failures=5, window_seconds=60)
    for _ in range(4):
        await limiter.record_failure("10.0.0.4", "academic01")
        await limiter.record_failure("10.0.0.5", "teacher01")

    await limiter.clear("10.0.0.4", "academic01")

    assert (await limiter.status("10.0.0.4", "academic01")).limited is False
    assert (await limiter.record_failure("10.0.0.5", "teacher01")).limited is True


async def test_redis_error_fails_open_without_raising() -> None:
    limiter = LoginRateLimiter(
        redis=BrokenRedis(),
        max_failures=5,
        window_seconds=60,
    )

    assert await limiter.status("10.0.0.4", "academic01") == RateLimitState(False, 0)
    assert await limiter.record_failure("10.0.0.4", "academic01") == RateLimitState(
        False,
        0,
    )
    await limiter.clear("10.0.0.4", "academic01")
