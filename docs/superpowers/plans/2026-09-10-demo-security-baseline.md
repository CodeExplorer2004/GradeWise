# Demo Security Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add demo-appropriate Redis login throttling, consistent browser security headers, hidden Nginx version information, and a reproducibly updated pip without introducing production IAM complexity.

**Architecture:** A focused `LoginRateLimiter` owns Redis keying and fixed-window failure accounting; the authentication route consumes its small status API and keeps credential responses non-enumerating. FastAPI applies API security headers, Nginx applies the same policy to static SPA responses and suppresses its version, while behavior is verified through unit tests and the real Docker gateway.

**Tech Stack:** FastAPI, redis-py asyncio, PostgreSQL-backed authentication, Nginx Alpine, pytest, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-10-demo-agent-foundation-design.md`

## Global Constraints

- Keep the project positioned as a production-aware demo, not a production IAM implementation.
- Limit by the SHA-256 digest of normalized username plus direct client IP; never store the password or raw username in a Redis key.
- Allow at most 5 failed attempts in a 60-second fixed window; the fifth and later attempts return HTTP 429 with `Retry-After`.
- A successful login clears only that client-and-username failure counter.
- Redis errors are logged without credentials and fail open so an optional demo dependency cannot lock out every account.
- Invalid credentials before the threshold continue returning the existing generic HTTP 401 message.
- Security headers must preserve same-origin microphone use for the existing Web Speech feature.
- Do not add refresh-token revocation, HttpOnly cookie migration, CAPTCHA, distributed identity, or production service authentication in this plan.

---

### Task 1: Add the Redis login failure limiter

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/login_rate_limit.py`
- Create: `backend/tests/test_login_rate_limit.py`

**Interfaces:**
- Consumes: `Settings.redis_url`, redis-py `Redis`, structlog.
- Produces: `RateLimitState(limited: bool, retry_after: int)`; `LoginRateLimiter.status(client_ip: str, username: str) -> RateLimitState`; `record_failure(client_ip: str, username: str) -> RateLimitState`; `clear(client_ip: str, username: str) -> None`; singleton `login_rate_limiter`.

- [x] **Step 1: Write the failing limiter behavior tests**

Create a small in-memory Redis double that implements the exact `eval` and `delete` boundary used by the service. Add tests proving:

```python
async def test_fifth_failure_is_limited_for_same_client_and_username():
    limiter = LoginRateLimiter(redis=fake, max_failures=5, window_seconds=60)
    states = [await limiter.record_failure("10.0.0.4", " Academic01 ") for _ in range(5)]
    assert [state.limited for state in states] == [False, False, False, False, True]
    assert states[-1].retry_after == 60

async def test_counters_are_isolated_and_keys_hide_identity():
    await limiter.record_failure("10.0.0.4", "academic01")
    assert (await limiter.status("10.0.0.5", "academic01")).limited is False
    assert (await limiter.status("10.0.0.4", "teacher01")).limited is False
    assert all("academic01" not in key for key in fake.keys)

async def test_clear_removes_only_the_successful_identity_counter():
    for _ in range(4):
        await limiter.record_failure("10.0.0.4", "academic01")
        await limiter.record_failure("10.0.0.5", "teacher01")
    await limiter.clear("10.0.0.4", "academic01")
    assert (await limiter.status("10.0.0.4", "academic01")).limited is False
    assert (await limiter.record_failure("10.0.0.5", "teacher01")).limited is True

async def test_redis_error_fails_open_without_raising():
    limiter = LoginRateLimiter(redis=BrokenRedis(), max_failures=5, window_seconds=60)
    assert await limiter.status("10.0.0.4", "academic01") == RateLimitState(False, 0)
    assert await limiter.record_failure("10.0.0.4", "academic01") == RateLimitState(False, 0)
    await limiter.clear("10.0.0.4", "academic01")
```

The production mutation each test catches is respectively: an off-by-one threshold, a shared or identifying key, over-broad clearing, and global login outage during Redis failure.

- [x] **Step 2: Run the limiter tests and verify RED**

Run:

```powershell
python -m pytest tests/test_login_rate_limit.py -q -p no:cacheprovider
```

Expected: collection fails because `app.services.login_rate_limit` does not exist.

- [x] **Step 3: Implement the minimal fixed-window service**

Add settings:

```python
login_max_failures: int = Field(default=5, ge=2, le=20)
login_window_seconds: int = Field(default=60, ge=10, le=3600)
```

Use SHA-256 over `client_ip + "\\0" + username.strip().casefold()` to construct `gradewise:login-fail:<digest>`. Use one Redis Lua script for atomic `INCR`, first-write `EXPIRE`, and TTL retrieval. A read-only status script returns current count and remaining TTL. Clamp missing/non-positive TTL to the configured window. Catch `RedisError`, log only `operation`, and return an allowed state.

- [x] **Step 4: Run the limiter tests and Ruff**

Run:

```powershell
python -m pytest tests/test_login_rate_limit.py -q -p no:cacheprovider
python -m ruff check --no-cache app/services/login_rate_limit.py tests/test_login_rate_limit.py app/core/config.py
```

Expected: all tests and lint pass.

- [x] **Step 5: Commit the limiter**

```powershell
git add backend/app/core/config.py backend/app/services/login_rate_limit.py backend/tests/test_login_rate_limit.py
git commit -m "feat: add redis login failure limiter"
```

### Task 2: Enforce throttling in the authentication route

**Files:**
- Modify: `backend/app/api/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_auth_rate_limit.py`

**Interfaces:**
- Consumes: `login_rate_limiter.status`, `record_failure`, and `clear`.
- Produces: `POST /api/auth/login` responses: 401 before the threshold, 429 with integer `Retry-After` at/after the threshold, normal token response after successful authentication.

- [ ] **Step 1: Write failing route behavior tests**

Call the real async `login()` function with a request-shaped object containing `client.host`, an `AsyncMock` database session, and a limiter fake with real counter state. Patch only password hashing verification. Cover:

```python
async def test_login_returns_429_with_retry_after_when_already_limited():
    with pytest.raises(HTTPException) as error:
        await login(
            request,
            LoginRequest(username="academic01", password="bad-password"),
            session,
        )
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) > 0
    session.scalar.assert_not_awaited()

async def test_fifth_invalid_login_changes_generic_401_to_429():
    details = []
    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            await login(request, invalid_payload, session)
        details.append((error.value.status_code, error.value.detail))
    assert details[:4] == [(401, "用户名或密码错误")] * 4
    assert details[4] == (429, "登录尝试过于频繁，请稍后再试")

async def test_successful_login_clears_its_failure_counter():
    limiter.count = 4
    response = await login(request, valid_payload, session_with_valid_user)
    assert response.user.username == "academic01"
    assert limiter.count == 0

async def test_redis_outage_does_not_replace_valid_authentication():
    response = await login(request, valid_payload, session_with_valid_user)
    assert response.access_token
    assert response.user.username == "academic01"
```

Assert only consumer-visible results and real limiter state, not mock call counts except to prove a pre-limited request does not perform password/database work.

- [ ] **Step 2: Run route tests and verify RED**

Run:

```powershell
python -m pytest tests/test_auth_rate_limit.py -q -p no:cacheprovider
```

Expected: tests fail because `login()` does not accept the request or consult the limiter.

- [ ] **Step 3: Wire the limiter into login and lifecycle**

Change the route signature to accept `Request` before the payload. Derive the direct client host, check status before querying the user, record invalid attempts, attach `Retry-After` on 429, and clear after password verification succeeds. Close `login_rate_limiter.redis` in the application lifespan beside the existing conversation Redis client.

- [ ] **Step 4: Run focused and full authentication tests**

Run:

```powershell
python -m pytest tests/test_auth_rate_limit.py tests/test_security.py -q -p no:cacheprovider
python -m ruff check --no-cache app/api/auth.py app/main.py tests/test_auth_rate_limit.py
```

Expected: all pass.

- [ ] **Step 5: Commit route enforcement**

```powershell
git add backend/app/api/auth.py backend/app/main.py backend/tests/test_auth_rate_limit.py
git commit -m "feat: throttle repeated login failures"
```

### Task 3: Add API and SPA security headers

**Files:**
- Create: `backend/app/services/security_headers.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/nginx/default.conf`
- Modify: `frontend/e2e/core-flow.spec.ts`
- Create: `backend/tests/test_security_headers.py`

**Interfaces:**
- Produces headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(), geolocation=(), microphone=(self)`, and a CSP limited to same-origin application assets with no objects or framing.
- Nginx must emit `Server: nginx` without a version token.

- [ ] **Step 1: Write failing backend header tests**

Test `apply_security_headers(Response())` and assert the five exact values. Also pass a response that already carries `X-Request-ID` and prove the helper preserves unrelated headers.

- [ ] **Step 2: Extend the gateway E2E before changing configuration**

In the existing public health test, request both `/health/live` and `/`. Assert the API and SPA responses expose the required headers and that the SPA `server` response header does not match `/nginx\\/\\d/i`.

Run against the current stack:

```powershell
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:28080'
npm --prefix frontend run test:e2e -- core-flow.spec.ts
```

Expected: FAIL because the headers and version suppression are absent.

- [ ] **Step 3: Implement FastAPI and Nginx header policy**

Create a small response helper with a literal immutable header mapping and call it from a FastAPI middleware. In Nginx set `server_tokens off;` and add the same headers with `always` inside the static `location /` block. Use this CSP:

```text
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self';
media-src 'self' blob:; object-src 'none'; base-uri 'self';
frame-ancestors 'none'; form-action 'self'
```

API and health responses receive the policy from FastAPI; static SPA responses receive it from Nginx, avoiding duplicate proxy headers.

- [ ] **Step 4: Verify unit behavior, rebuild gateway services, and turn E2E GREEN**

Run:

```powershell
python -m pytest tests/test_security_headers.py -q -p no:cacheprovider
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml build backend frontend
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml up --detach --no-deps backend frontend
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:28080'
npm --prefix frontend run test:e2e
```

Expected: backend header tests pass and all Playwright tests pass without CSP console failures.

- [ ] **Step 5: Commit the security headers**

```powershell
git add backend/app/services/security_headers.py backend/app/main.py backend/tests/test_security_headers.py frontend/nginx/default.conf frontend/e2e/core-flow.spec.ts
git commit -m "feat: add demo security response headers"
```

### Task 4: Update pip reproducibly and record the security baseline

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `docs/test-report-2026-09-10.md`
- Modify: `README.md`

**Interfaces:**
- Produces: backend image with pip `26.2.1`; dated report containing exact throttling, header, build, and test evidence.

- [ ] **Step 1: Pin the updated installer in the backend image**

Before installing the project, add:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --timeout 120 --retries 10 "pip==26.2.1"
```

Keep project dependency installation as a separate cached layer.

- [ ] **Step 2: Build and inspect the real image**

Run:

```powershell
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml build backend
docker run --rm --entrypoint python gradewise-hardening-backend -m pip --version
```

Expected: exit 0 and output begins with `pip 26.2.1`.

- [ ] **Step 3: Run the complete security and project verification**

Run:

```powershell
python -m pytest -q -p no:cacheprovider
python -m ruff check --no-cache app tests alembic
alembic check
npm --prefix frontend run build
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:28080'
npm --prefix frontend run test:e2e
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml ps
```

Expected: every command exits 0 and all six services are healthy.

- [ ] **Step 4: Update documentation with measured evidence**

Document the 5 failures / 60 seconds rule, Redis fail-open demo boundary, response-header policy, Nginx version suppression, pip version, exact test counts, and that token revocation/HttpOnly cookies remain outside this demo scope.

- [ ] **Step 5: Commit documentation and Dockerfile**

```powershell
git add backend/Dockerfile README.md docs/test-report-2026-09-10.md
git commit -m "build: harden demo service baseline"
```

## Completion Checkpoint

After this plan is green, keep `codex/production-hardening` in its isolated worktree and create the next independent plan for precise Python dependency locking and vulnerability audit. Do not merge yet; multi-role/import E2E and presentation artifacts remain separate follow-on plans.
