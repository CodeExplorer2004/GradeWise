# Recent Exam Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every supported “最近/近 X 次考试” query use one deterministic, permission-scoped exam set.

**Architecture:** Parse the requested exam count in `query_graph.py`, construct a reusable `exam_id` subquery over `score_facts`, and route recent detail, average, trend, and failure requests through deterministic SQL. Keep SQL authorization in the existing `SQLSafetyGate`/`execute_scoped_query` boundary and generate deterministic answers and charts for this family.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, SQLAlchemy, sqlglot, pytest

**Spec:** `docs/superpowers/specs/2026-09-09-recent-exam-scope.md`

## Global Constraints

- Preserve role-based authorization injected by `execute_scoped_query`.
- Query only the allowlisted `score_facts` view.
- Do not rely on the model for explicit recent-exam queries.
- Support Arabic digits plus `一` through `九十九`, including `两`.
- Do not modify unrelated user changes.

---

### Task 1: Parse and scope recent exams

**Files:**
- Modify: `backend/app/agents/query_graph.py`
- Test: `backend/tests/test_sql_security.py`

**Interfaces:**
- Produces: `_recent_exam_limit(question: str) -> int | None`
- Produces: deterministic SQL from `sql_node(state)` containing a permission-rewritable recent-exam subquery

- [x] Add parameterized parser tests for Arabic digits, Chinese digits, `两`, spaces, and non-recent history wording.
- [x] Run the parser tests and verify they fail because the parser does not exist.
- [x] Implement the smallest parser that satisfies the cases.
- [x] Add failing SQL-node tests for recent detail, subject average, all-subject trend, and failure queries.
- [x] Run those tests and verify the current SQL has the wrong range or shape.
- [x] Implement the shared recent-exam predicate and deterministic SQL templates.
- [x] Run the focused tests and verify they pass.

### Task 2: Make downstream behavior deterministic

**Files:**
- Modify: `backend/app/agents/query_graph.py`
- Test: `backend/tests/test_sql_security.py`
- Test: `backend/tests/test_query_charts.py`

**Interfaces:**
- Consumes: `_recent_exam_limit(question)` and SQL rows from Task 1
- Produces: deterministic `schema_node`, `audit_node`, `visualization_node`, and `final_node` results for recent-exam queries

- [x] Add failing tests proving recent queries bypass model agents.
- [x] Add literal-answer tests for single-score detail, combined subject average, trend summary, and fewer-than-X exams.
- [x] Run the focused tests and verify expected failures.
- [x] Implement deterministic downstream branches without changing non-recent behavior.
- [x] Run the focused tests and verify they pass.

### Task 3: Regression and live verification

**Files:**
- Modify only if a regression is exposed by verification.

**Interfaces:**
- Consumes: completed recent-exam query path
- Produces: unit-test and live-API evidence for the approved acceptance cases

- [x] Run the complete backend test suite.
- [x] Run Ruff over the backend.
- [x] Rebuild and recreate the backend container from the current branch.
- [x] Query the live API with the approved phrase matrix and assert exact row counts, exam sets, and averages.
- [x] Remove all generated test conversations.
- [x] Review the final diff for scope and accidental changes.
