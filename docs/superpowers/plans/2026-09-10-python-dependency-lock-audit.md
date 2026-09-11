# Python Dependency Lock and Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make backend and Agent worker Python installations reproducible with hash-verified transitive locks and add repeatable vulnerability audits to local verification and CI.

**Architecture:** Keep each pyproject.toml as the human-edited compatibility contract, generate service-specific pip requirements locks with exact versions and hashes, and install those locks directly in Docker. The backend development lock includes test, lint, lock-generation, and audit tooling; CI installs from it, verifies both runtime locks, and audits backend and worker dependencies independently.

**Tech Stack:** Python 3.12, pip 26.2.1, pip-tools 7.5.3, pip-audit 2.x, Docker BuildKit, GitHub Actions.

**Spec:** docs/superpowers/specs/2026-09-10-demo-agent-foundation-design.md

## Global Constraints

- Lock backend runtime, backend development, and Agent worker runtime graphs separately.
- Every distributable requirement is pinned with == and hashes; Docker and CI install with --require-hashes.
- Lock files are generated artifacts and are never hand-edited.
- Generate, install, audit, and run with Python 3.12.
- Do not ignore audit findings. Fix compatible findings or document advisory ID, package, impact, and acceptance reason.
- Keep dependency resolution at build or CI time, never container startup.

---

### Task 1: Generate exact service locks

**Files:**
- Modify: backend/pyproject.toml
- Create: scripts/compile-python-locks.ps1
- Create: backend/requirements.lock
- Create: backend/requirements-dev.lock
- Create: agent-worker/requirements.lock

**Interfaces:**
- The script accepts -PythonExecutable and -Upgrade.
- Without -Upgrade it runs pip-compile with --no-upgrade; with -Upgrade it refreshes allowed versions intentionally.

- [x] **Step 1: Add tooling ranges**

Add pip-audit>=2.7,<3 and pip-tools==7.5.3 to backend project.optional-dependencies.dev. Version 7.5.3 is pinned because 7.6.1 constructs an invalid PyPI JSON URL for hash lookup and falls back to downloading every release artifact.

- [x] **Step 2: Add the generation script**

The script validates Python 3.12, resolves paths from its own location, and runs:

    python -m piptools compile backend/pyproject.toml --output-file backend/requirements.lock --generate-hashes --allow-unsafe --strip-extras
    python -m piptools compile backend/pyproject.toml --extra dev --output-file backend/requirements-dev.lock --generate-hashes --allow-unsafe --strip-extras
    python -m piptools compile agent-worker/pyproject.toml --output-file agent-worker/requirements.lock --generate-hashes --allow-unsafe --strip-extras

Pass --no-upgrade by default and --upgrade only when -Upgrade is supplied. Set CUSTOM_COMPILE_COMMAND to the script command so regeneration instructions remain stable.

- [x] **Step 3: Bootstrap tooling and generate locks**

Run:

    python -m pip install "pip-tools==7.5.3" "pip-audit>=2.7,<3"
    ./scripts/compile-python-locks.ps1 -PythonExecutable python

Expected: all three lock files contain exact pins and --hash entries.

- [x] **Step 4: Verify deterministic regeneration**

Run the script again without -Upgrade, then run git diff --exit-code on the three lock files. Expected: no changes.

- [x] **Step 5: Commit generation inputs and locks**

    git add backend/pyproject.toml scripts/compile-python-locks.ps1 backend/requirements.lock backend/requirements-dev.lock agent-worker/requirements.lock
    git commit -m "build: lock python dependencies"

### Task 2: Consume locks in both Docker images

**Files:**
- Modify: backend/Dockerfile
- Modify: agent-worker/Dockerfile

**Interfaces:**
- Backend image installs backend/requirements.lock.
- Agent worker image installs agent-worker/requirements.lock.
- Application source remains copied into /app and no runtime resolver is invoked.

- [ ] **Step 1: Change Docker install layers**

Copy pyproject.toml and requirements.lock together. Install with:

    python -m pip install --timeout 120 --retries 10 --require-hashes -r requirements.lock

Do not install the local project package because both images copy and execute source directly.

- [ ] **Step 2: Build both images from a clean dependency layer**

    docker compose -p gradewise-hardening -f docker-compose.yml -f docker-compose.e2e.yml build backend agent-worker

Expected: both builds succeed using only exact hash-verified dependencies.

- [ ] **Step 3: Inspect representative runtime versions**

Run pip freeze in each image and compare every package/version pair against its runtime lock. Expected: no missing or extra distributable dependencies apart from pip, setuptools, and wheel.

- [ ] **Step 4: Commit Docker consumption**

    git add backend/Dockerfile agent-worker/Dockerfile
    git commit -m "build: install python services from locks"

### Task 3: Add repeatable CI vulnerability gates

**Files:**
- Modify: .github/workflows/ci.yml

**Interfaces:**
- CI installs backend/requirements-dev.lock with --require-hashes.
- CI audits backend/requirements.lock and agent-worker/requirements.lock separately.
- CI regenerates locks without upgrades and fails when tracked locks drift from pyproject inputs.

- [ ] **Step 1: Update CI installation**

Replace editable dependency resolution with:

    python -m pip install --require-hashes -r requirements-dev.lock

The source remains importable because CI commands run from backend and pytest already sets pythonpath.

- [ ] **Step 2: Add lock drift checks**

Run the three piptools compile commands with --no-upgrade and fail on git diff for the three lock files.

- [ ] **Step 3: Add two audit commands**

    python -m pip_audit -r requirements.lock
    python -m pip_audit -r ../agent-worker/requirements.lock

Expected: both exit 0. If either reports a vulnerability, update the compatible direct constraint or regenerate with -Upgrade, rebuild, and rerun; do not add an ignore without documentation.

- [ ] **Step 4: Validate workflow syntax and commit**

Parse the YAML, run both audit commands locally, then commit:

    git add .github/workflows/ci.yml
    git commit -m "ci: audit locked python dependencies"

### Task 4: Verify and document dependency reproducibility

**Files:**
- Modify: README.md
- Modify: docs/test-report-2026-09-10.md

- [ ] **Step 1: Run full verification**

Run 149+ backend tests, Ruff over app/tests/alembic, Alembic check, frontend build, all Playwright tests, both Docker builds, both audits, and Compose health checks.

- [ ] **Step 2: Document regeneration and audit commands**

README must explain normal no-upgrade regeneration and intentional -Upgrade usage. The test report records exact lock counts, audit result or advisory details, and image build evidence.

- [ ] **Step 3: Commit evidence**

    git add README.md docs/test-report-2026-09-10.md docs/superpowers/plans/2026-09-10-python-dependency-lock-audit.md
    git commit -m "docs: record python dependency audit"

## Completion Checkpoint

After this plan passes, keep codex/production-hardening unmerged. The next plans cover multi-role/import E2E and presentation artifacts.
