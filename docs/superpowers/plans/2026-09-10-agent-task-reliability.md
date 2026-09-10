# Agent Task Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace expiring Redis Agent task metadata with a PostgreSQL task ledger that preserves results, detects lost in-memory worker runs, and supports permission-safe manual retry.

**Architecture:** PostgreSQL owns application task identity and lifecycle; the LangGraph development worker remains the transient execution runtime. API orchestration validates scope before recording a task, persists every externally visible transition, and treats worker 404 responses differently from temporary connectivity failures. The frontend continues polling but renders the persisted stage, safe error, attempt count, and retry action.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 16, `langgraph-sdk`, Pydantic 2, Vue 3, Pinia, TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-10-demo-agent-foundation-design.md`

## Global Constraints

- Keep the current in-memory Agent worker; do not introduce a queue or production Agent Server.
- PostgreSQL is the only source of truth for task metadata and results; Redis remains conversation cache only.
- Never persist the full model evidence payload; save requested/effective scope and the already-redacted final result.
- Revalidate the current user role and requested scope on every retry.
- A temporary worker connection failure must not convert a running task to `interrupted`; only a confirmed missing thread or run may do so.
- Never expose provider exceptions, internal URLs, stack traces, API keys, or raw student identity in task errors.
- Do not display hidden model reasoning; stages must correspond to observable application work.
- Preserve the existing `/api/tasks` API shape where practical by returning `scope` as the effective scope and `task_id` as the application task ID.

---

### Task 1: Add the persistent Agent task contract

**Files:**
- Create: `backend/tests/test_agent_tasks.py`
- Modify: `backend/app/core/models.py`
- Modify: `backend/app/core/schemas.py`
- Create: `backend/alembic/versions/20260910_0004_add_agent_tasks.py`

**Interfaces:**
- Consumes: existing `School`, `User`, `AgentTaskScope`, and SQLAlchemy `Base`.
- Produces: ORM `AgentTask`; response `AgentTaskResponse`; status/stage literal aliases; migration revision `20260910_0004` with down revision `20260830_0003`.

- [ ] **Step 1: Write failing model and response-contract tests**

Add imports and tests to `backend/tests/test_agent_tasks.py`:

```python
from datetime import UTC, datetime

from app.core.models import AgentTask
from app.core.schemas import AgentTaskResponse


def test_agent_task_model_contains_persistent_worker_and_lifecycle_fields() -> None:
    columns = AgentTask.__table__.columns
    assert {
        "id", "school_id", "user_id", "task_type", "requested_scope",
        "effective_scope", "worker_thread_id", "worker_run_id", "status",
        "stage", "status_message", "result", "result_prefix", "error_code",
        "attempt_count", "created_at", "started_at", "finished_at", "updated_at",
    } <= set(columns.keys())
    assert columns["result"].nullable
    assert columns["worker_run_id"].nullable


def test_agent_task_response_preserves_compatible_scope_and_retry_metadata() -> None:
    now = datetime.now(UTC)
    response = AgentTaskResponse(
        task_id="task-1",
        run_id=None,
        task_type="batch_report",
        status="interrupted",
        stage="interrupted",
        status_message="Agent 运行环境已重启，可重新执行",
        scope={"class_name": "初一（1）班"},
        requested_scope={"class_name": "初一（1）班"},
        error_code="worker_state_missing",
        attempt_count=1,
        can_retry=True,
        created_at=now,
        updated_at=now,
    )
    assert response.scope.class_name == "初一（1）班"
    assert response.run_id is None
    assert response.can_retry is True
```

- [ ] **Step 2: Run the focused tests and confirm the missing contract failure**

Run from `backend`:

```powershell
python -m pytest tests/test_agent_tasks.py -q
```

Expected: collection fails because `AgentTask` does not exist or response fields are missing.

- [ ] **Step 3: Add the ORM model and API schema**

Add `Text` and `Index` imports in `backend/app/core/models.py`, then define `AgentTask` with:

```python
class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(32))
    requested_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    effective_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    worker_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(32), default="collecting_evidence")
    status_message: Mapped[str] = mapped_column(String(255), default="正在准备任务")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_agent_tasks_user_created", "user_id", created_at.desc()),
        CheckConstraint(
            "task_type IN ('batch_report', 'batch_warning')",
            name="ck_agent_tasks_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'error', 'cancelled', 'interrupted')",
            name="ck_agent_tasks_status",
        ),
    )
```

In `backend/app/core/schemas.py`, make `run_id` nullable and extend `AgentTaskResponse` with exact fields:

```python
AgentTaskStatus = Literal["queued", "running", "success", "error", "cancelled", "interrupted"]
AgentTaskStage = Literal[
    "collecting_evidence", "submitting", "agent_running", "saving_result",
    "completed", "failed", "cancelled", "interrupted",
]


class AgentTaskResponse(BaseModel):
    task_id: str
    run_id: str | None = None
    task_type: Literal["batch_report", "batch_warning"]
    status: AgentTaskStatus
    stage: AgentTaskStage
    status_message: str
    result: str | None = None
    scope: AgentTaskScope = Field(default_factory=AgentTaskScope)
    requested_scope: AgentTaskScope = Field(default_factory=AgentTaskScope)
    error_code: str | None = None
    attempt_count: int = 0
    can_retry: bool = False
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **Step 4: Add the Alembic migration**

Create `backend/alembic/versions/20260910_0004_add_agent_tasks.py`. Its `upgrade()` must create every ORM column above, foreign keys to `schools.id` and `users.id`, the two check constraints, ordinary indexes for school/user/status, and `ix_agent_tasks_user_created`. Its `downgrade()` must drop `agent_tasks` only.

- [ ] **Step 5: Verify the contract, migration, and schema drift**

Run:

```powershell
python -m pytest tests/test_agent_tasks.py -q
alembic upgrade head
alembic check
```

Expected: tests pass, upgrade reaches `20260910_0004`, and Alembic reports no new upgrade operations.

- [ ] **Step 6: Commit the persistent contract**

```powershell
git add backend/app/core/models.py backend/app/core/schemas.py backend/alembic/versions/20260910_0004_add_agent_tasks.py backend/tests/test_agent_tasks.py
git commit -m "feat: add persistent agent task model"
```

---

### Task 2: Replace Redis task metadata with a database lifecycle service

**Files:**
- Modify: `backend/app/services/agent_tasks.py`
- Modify: `backend/tests/test_agent_tasks.py`

**Interfaces:**
- Consumes: ORM `AgentTask`, `AsyncSession`, `User`, `AgentTaskResponse`, `get_client()`.
- Produces:
  - `create_task_record(session, user, task_type, requested_scope, effective_scope, result_prefix=None) -> AgentTask`
  - `submit_task(session, task, description) -> AgentTaskResponse`
  - `get_task(session, user, task_id) -> AgentTaskResponse`
  - `list_tasks(session, user) -> list[AgentTaskResponse]`
  - `retry_task(session, user, task_id, description, effective_scope, result_prefix=None) -> AgentTaskResponse`
  - `update_task(session, user, task_id, message) -> AgentTaskResponse`
  - `cancel_task(session, user, task_id) -> AgentTaskResponse`
  - `fail_task(session, task, error_code, status_message) -> AgentTaskResponse`
  - `load_owned_task(session, user, task_id, for_update=False) -> AgentTask`

- [ ] **Step 1: Write failing pure status and response mapping tests**

Add to `backend/tests/test_agent_tasks.py`:

```python
from types import SimpleNamespace

from app.services.agent_tasks import normalize_worker_status, task_response


def test_worker_statuses_are_normalized_to_application_states() -> None:
    assert normalize_worker_status("pending") == ("running", "agent_running")
    assert normalize_worker_status("running") == ("running", "agent_running")
    assert normalize_worker_status("success") == ("success", "completed")
    assert normalize_worker_status("timeout") == ("error", "failed")
    assert normalize_worker_status("interrupted") == ("interrupted", "interrupted")


def test_task_response_never_exposes_result_prefix() -> None:
    task = SimpleNamespace(
        id="task-1", worker_run_id=None, task_type="batch_report",
        status="error", stage="failed", status_message="Agent 服务暂不可用",
        result=None, result_prefix="internal deterministic prefix",
        requested_scope={}, effective_scope={}, error_code="worker_unavailable",
        attempt_count=1, created_at=None, started_at=None, finished_at=None,
        updated_at=None,
    )
    response = task_response(task)
    assert response.error_code == "worker_unavailable"
    assert response.can_retry is True
    assert "result_prefix" not in response.model_dump()
```

- [ ] **Step 2: Run the focused tests and confirm helper failures**

```powershell
python -m pytest tests/test_agent_tasks.py -q
```

Expected: imports fail because the mapping helpers do not exist.

- [ ] **Step 3: Implement status normalization and safe response mapping**

Replace Redis JSON helpers in `agent_tasks.py` with constants and pure helpers. Use this mapping:

```python
WORKER_STATUS_MAP = {
    "pending": ("running", "agent_running"),
    "running": ("running", "agent_running"),
    "success": ("success", "completed"),
    "error": ("error", "failed"),
    "timeout": ("error", "failed"),
    "cancelled": ("cancelled", "cancelled"),
    "interrupted": ("interrupted", "interrupted"),
}
RETRYABLE_STATUSES = {"error", "interrupted"}
TERMINAL_STATUSES = {"success", "error", "cancelled", "interrupted"}
```

`task_response()` must return `scope=effective_scope or requested_scope`, derive `can_retry`, and never serialize `result_prefix`.

- [ ] **Step 4: Write failing lifecycle tests with mocked SDK and session**

Tests must use `AsyncMock` for `session.commit`, `session.flush`, and SDK methods, and cover these exact cases:

Use a `make_task(status)` fixture returning an `AgentTask` owned by user 7 in school 1, a session `SimpleNamespace` whose async methods are `AsyncMock`, and a client whose `threads.create/get` and `runs.create/get/cancel` methods are `AsyncMock`. Implement these assertions:

- `test_submit_task_persists_worker_ids_and_first_attempt`: worker returns `thread-2`, `run-2`, `pending`; assert the application ID stays `task-1`, IDs are stored, status normalizes to `running`, attempt count becomes 1, and the session commits.
- `test_successful_poll_persists_prefixed_redacted_result`: worker returns `success` and last content `模型结果`; assert the stored result is exactly `确定性摘要\n\n模型结果`, status is `success`, stage is `completed`, and the session commits.
- `test_worker_404_marks_running_task_interrupted`: raise `httpx.HTTPStatusError` with an attached 404 response; assert `interrupted`, `worker_state_missing`, and `can_retry=True` are persisted.
- `test_temporary_worker_failure_preserves_running_state`: raise `httpx.ConnectError("offline")`; assert the exception propagates, status stays `running`, and no commit occurs.
- `test_retry_rejects_running_task_before_worker_submission`: assert `InvalidTaskTransition` and that `threads.create` was not awaited.
- `test_retry_reuses_application_id_and_increments_attempt`: begin at `interrupted` with attempt 1; assert result ID remains `task-1`, attempt becomes 2, and worker IDs change.
- `test_user_cannot_load_another_users_task`: make `session.scalar()` return `None`; assert `load_owned_task()` raises `KeyError("task-1")`.

The 404 fixture must use executable construction rather than a message-only exception:

```python
request = httpx.Request("GET", "http://agent-worker/runs/missing")
response = httpx.Response(404, request=request)
missing = httpx.HTTPStatusError("missing", request=request, response=response)
```

Construct a confirmed missing-worker error with an `httpx.Response(404, request=httpx.Request("GET", "http://agent-worker/runs/x"))`; construct the transient case with `httpx.ConnectError("offline")`.

- [ ] **Step 5: Implement database lookup and worker lifecycle methods**

Use SQLAlchemy `select()` filtered by all of `AgentTask.id`, `AgentTask.user_id`, and `AgentTask.school_id`. For retry, reselect with `.with_for_update()`, reject non-retryable states with a dedicated `InvalidTaskTransition`, set the row to `queued`, clear old result/error/worker IDs, increment `attempt_count`, commit, then submit the external run.

When a worker run succeeds, fetch the last thread message, prepend `result_prefix` once, set `saving_result`, then persist `success/completed`. On a confirmed 404 for a nonterminal task, persist `interrupted` with `error_code="worker_state_missing"`. Let other `httpx.HTTPError` values propagate without changing the stored state.

If worker submission fails after an attempt was prepared, persist `error/failed`, `error_code="worker_unavailable"`, and the safe message `Agent 服务暂不可用，可稍后重新执行`; do not persist `str(exc)`.

- [ ] **Step 6: Run the lifecycle tests**

```powershell
python -m pytest tests/test_agent_tasks.py -q
```

Expected: all persistent lifecycle, 404, transient failure, ownership, and retry tests pass.

- [ ] **Step 7: Commit the lifecycle service**

```powershell
git add backend/app/services/agent_tasks.py backend/tests/test_agent_tasks.py
git commit -m "feat: persist agent task lifecycle"
```

---

### Task 3: Wire creation, retry, cancellation, and continuation into the API

**Files:**
- Modify: `backend/app/api/tasks.py`
- Create: `backend/tests/test_agent_task_api.py`
- Modify: `backend/tests/test_regression_fixes.py`

**Interfaces:**
- Consumes: Task 2 lifecycle service and existing `validate_scope`, insight, risk, and privacy services.
- Produces: `POST /api/tasks/{task_id}/retry`; every task route receives `AsyncSession`; shared `_build_task_input()` used by create and retry.

- [ ] **Step 1: Write failing API orchestration tests**

Create `backend/tests/test_agent_task_api.py` with direct async endpoint tests using a `SimpleNamespace` user and `AsyncMock` session. Cover:

Use direct async endpoint calls, an `admin()` fixture returning `SimpleNamespace(id=7, school_id=1, role=UserRole.ACADEMIC_ADMIN)`, and `AsyncMock` service substitutions. Implement these assertions:

- `test_create_records_validated_scope_before_submitting`: append markers from mocked validation, record creation, evidence construction, and submission; assert exact order `validate, record, evidence, submit`.
- `test_create_returns_persisted_safe_error_when_submission_fails`: make submission raise `httpx.ConnectError`; assert the response is the record returned by `fail_task()` with `worker_unavailable`, and the provider exception text is absent.
- `test_retry_revalidates_saved_requested_scope`: return stored `requested_scope={"class_name": "初一（1）班"}`; assert `_validated_scope` receives that scope and `retry_task` receives the newly returned effective scope and newly built description.
- `test_retry_rechecks_current_role`: return a stored `batch_warning` task for a subject teacher; assert HTTP 403 before evidence construction.
- `test_student_cannot_retry_batch_task`: return a stored batch report for a student; assert HTTP 403 before evidence construction.
- `test_invalid_retry_transition_returns_409`: make `retry_task` raise `InvalidTaskTransition("任务当前不可重试")`; assert HTTP 409 with the same safe detail.

Use this exact ordering assertion in the creation test:

```python
result = await task_api.create_agent_task(payload, admin(), AsyncMock())
assert result.task_id == "task-1"
assert calls == ["validate", "record", "evidence", "submit"]
```

The retry test must assert that `_validated_scope(current_user, AgentTaskScope(**task.requested_scope))` runs before new evidence is generated and before `retry_task()` receives its description.

- [ ] **Step 2: Run API tests and confirm route/signature failures**

```powershell
python -m pytest tests/test_agent_task_api.py tests/test_regression_fixes.py -q
```

Expected: new retry route/helper tests fail; the existing regression test documents signatures that must be updated.

- [ ] **Step 3: Extract deterministic task-input construction**

Create this API-local structure:

```python
@dataclass
class TaskInput:
    description: str
    result_prefix: str | None


async def _build_task_input(
    user: User,
    task_type: str,
    effective_scope: dict[str, str | int],
) -> TaskInput:
    if task_type == "batch_report":
        evidence = insights_for_llm(
            await collect_learning_insights(user, effective_scope)
        )
        result_prefix = None
    else:
        evidence = risk_batch_evidence(
            await collect_risk_predictions(user, effective_scope)
        )
        summary = evidence["deterministic_summary"]
        result_prefix = (
            "确定性统计（以此为准）："
            f"共 {summary['total_predictions']} 条学生-科目风险记录，"
            f"高风险 {summary['high_count']} 条，中风险 {summary['medium_count']} 条，"
            f"低风险 {summary['low_count']} 条；"
            f"提供给模型解释的明细为 {summary['evidence_items_count']} 条。\n"
            "以下 AI 解释仅供人工复核，不构成新的风险证据或事实。"
        )
    description = json.dumps(
        {"task_type": task_type, "scope": effective_scope, "evidence": evidence},
        ensure_ascii=False,
        default=str,
    )
    return TaskInput(description, result_prefix)
```

Both create and retry must call this helper, and the deterministic warning prefix wording must remain unchanged.

- [ ] **Step 4: Update all task routes to use the database session**

For list, detail, update, and cancel, pass `session: AsyncSession = Depends(get_db)` to the Task 2 service. Convert `KeyError` to 404, `InvalidTaskTransition` to 409, and temporary `httpx.HTTPError` to 503.

Creation order must be:

```python
_authorize(current_user, payload.task_type)
effective_scope = await _validated_scope(current_user, payload.scope)
task = await create_task_record(
    session, current_user, payload.task_type,
    payload.scope.model_dump(), effective_scope,
)
task_input = await _build_task_input(current_user, payload.task_type, effective_scope)
return await submit_task(session, task, task_input.description, task_input.result_prefix)
```

If evidence collection or submission fails after the record exists, call the lifecycle service's safe failure method and return the persisted task response so it appears immediately in the UI.

- [ ] **Step 5: Add retry endpoint with current authorization**

Implement:

```python
@router.post("/{task_id}/retry", response_model=AgentTaskResponse)
async def retry_agent_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentTaskResponse:
    task = await load_owned_task(session, current_user, task_id)
    _authorize(current_user, task.task_type)
    requested = AgentTaskScope(**task.requested_scope)
    effective_scope = await _validated_scope(current_user, requested)
    task_input = await _build_task_input(current_user, task.task_type, effective_scope)
    return await retry_task(
        session, current_user, task_id, task_input.description,
        effective_scope, task_input.result_prefix,
    )
```

The concrete implementation must use the shared exception mapping from Step 4 and must not accept scope or task type from the retry request body.

- [ ] **Step 6: Preserve successful results when continuation context is gone**

For `POST /{task_id}/update`, a confirmed worker 404 on an already successful database task returns HTTP 409 with `原 Agent 上下文已失效，请创建新任务`; it must leave `status`, `result`, and `finished_at` unchanged.

- [ ] **Step 7: Run API and full backend tests**

```powershell
python -m pytest tests/test_agent_task_api.py tests/test_agent_tasks.py tests/test_regression_fixes.py -q
python -m pytest -q -p no:cacheprovider
```

Expected: focused tests and the complete backend suite pass.

- [ ] **Step 8: Commit the API integration**

```powershell
git add backend/app/api/tasks.py backend/tests/test_agent_task_api.py backend/tests/test_regression_fixes.py
git commit -m "feat: add permission-safe agent task retry"
```

---

### Task 4: Show persisted lifecycle and retry in the frontend

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/stores/tasks.ts`
- Modify: `frontend/src/views/DashboardView.vue`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: extended `AgentTaskResponse` and `POST /tasks/{task_id}/retry`.
- Produces: typed retry client/store action, status/stage UI, safe error display, attempt metadata, and state-gated retry button.

- [ ] **Step 1: Update the TypeScript task contract first**

Replace the loose task status with exact unions:

```typescript
export type AgentTaskStatus = 'queued' | 'running' | 'success' | 'error' | 'cancelled' | 'interrupted'
export type AgentTaskStage = 'collecting_evidence' | 'submitting' | 'agent_running' | 'saving_result' | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export interface AgentTask {
  task_id: string
  run_id?: string | null
  task_type: 'batch_report' | 'batch_warning'
  status: AgentTaskStatus
  stage: AgentTaskStage
  status_message: string
  result?: string | null
  scope: AgentTaskScope
  requested_scope: AgentTaskScope
  error_code?: string | null
  attempt_count: number
  can_retry: boolean
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  updated_at?: string | null
}
```

- [ ] **Step 2: Run type checking and confirm callers require updates**

Run from `frontend`:

```powershell
npm exec vue-tsc -- --noEmit -p tsconfig.app.json
```

Expected: any hand-built task fixtures or status assumptions that no longer satisfy the exact interface fail.

- [ ] **Step 3: Add API and store retry support**

Add `tasksApi.retry(taskId)` and this store action:

```typescript
async function retry(taskId: string) {
  loading.value = true
  try {
    const { data } = await tasksApi.retry(taskId)
    merge(data)
    currentTaskId.value = data.task_id
    schedulePoll()
    return data
  } finally {
    loading.value = false
  }
}
```

Use `queued` and `running` as the only active statuses. Continue preserving tasks during transient polling failures.

- [ ] **Step 4: Render truthful lifecycle information**

In `DashboardView.vue`:

- Add `queued: '等待执行'` to status labels and remove the old `pending` application status.
- Render `task.status_message` beneath the task header.
- Render `尝试次数：{attempt_count}` and formatted `updated_at` in task metadata.
- Render a warning block for `error_code` without printing raw exception data.
- Show `重新执行` only when `task.can_retry` is true.
- Add `retryAgentTask()` that calls `taskStore.retry()` and reports success/failure with `MessagePlugin`.
- Keep “追加要求” visible only for `running` tasks.

Add narrowly scoped styles for `.task-stage-message`, `.task-error`, and `.task-retry` using the existing task panel color system.

- [ ] **Step 5: Run frontend verification**

```powershell
npm exec vue-tsc -- --noEmit -p tsconfig.app.json
npm run build
```

Expected: type checking and production build pass with no new chunk-size warning.

- [ ] **Step 6: Commit the lifecycle UI**

```powershell
git add frontend/src/types.ts frontend/src/api/index.ts frontend/src/stores/tasks.ts frontend/src/views/DashboardView.vue frontend/src/styles/global.css
git commit -m "feat: show agent task recovery state"
```

---

### Task 5: Verify persistence across a worker restart and document the boundary

**Files:**
- Modify: `docs/architecture.md`
- Create: `docs/test-report-2026-09-10.md`

**Interfaces:**
- Consumes: Tasks 1-4 and the isolated Compose project `gradewise-hardening` on `127.0.0.1:28080`.
- Produces: verified restart/retry evidence, updated architecture wording, and a dated test report.

- [ ] **Step 1: Update architecture documentation**

Replace the statement that Redis binds task ownership with the PostgreSQL task-ledger design. State explicitly that the worker remains in-memory, application records/results survive, a missing run becomes `interrupted`, and retry starts a fresh execution rather than resuming model state.

- [ ] **Step 2: Rebuild the changed services and migrate the isolated database**

Run from repository root:

```powershell
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml up --build --detach --wait --wait-timeout 240 backend frontend
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml exec -T backend alembic current
```

Expected: backend and frontend are healthy; Alembic current revision is `20260910_0004`.

- [ ] **Step 3: Run all static and automated checks**

```powershell
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml exec -T backend python -m pytest -q -p no:cacheprovider
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml exec -T backend ruff check --no-cache app tests alembic
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml exec -T backend alembic check
npm --prefix frontend exec vue-tsc -- --noEmit -p tsconfig.app.json
npm --prefix frontend run build
```

Expected: all commands exit 0 and Alembic reports no drift.

- [ ] **Step 4: Perform the worker restart acceptance check**

Using an authenticated non-student demo account and a configured model key, create a batch report and capture its application task ID. Restart only the worker:

```powershell
docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml restart agent-worker
```

After health recovers, query that task. Expected: the database row remains; if the run was nonterminal it becomes `interrupted` after the worker confirms it is missing; the UI offers `重新执行`. Retry must preserve the application task ID and change worker IDs with `attempt_count + 1`.

If no real model key is available, execute the same state transitions with the automated mocked-worker tests and mark the live Agent check as “未执行：未配置模型密钥”; do not report it as passed.

- [ ] **Step 5: Write the dated test report**

Create `docs/test-report-2026-09-10.md` containing exact commands, pass counts, migration revision, frontend build result, worker restart outcome, and remaining limits. The remaining limits must include the in-memory worker, browser-session notifications, and absence of precise mid-run resume.

- [ ] **Step 6: Commit documentation and evidence**

```powershell
git add docs/architecture.md docs/test-report-2026-09-10.md
git commit -m "docs: record agent task reliability verification"
```
