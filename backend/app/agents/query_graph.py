from __future__ import annotations

import json
import re
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from app.agents.contracts import AuditExplanation, SchemaResolution, SQLDraft, VisualizationDraft
from app.agents.factory import registry
from app.core.models import User, UserRole
from app.services.analysis_scope import apply_scope_to_sql
from app.services.chart_security import secure_chart
from app.services.privacy import (
    StudentAlias,
    mask_student_aliases_in_sql,
    restore_student_aliases_in_sql,
    rows_for_llm,
)
from app.services.sql_security import SQLSafetyGate, ValidationResult, execute_scoped_query

logger = structlog.get_logger(__name__)


class QueryState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    llm_question: str
    llm_history: list[dict[str, str]]
    student_aliases: dict[str, StudentAlias]
    catalog: dict[str, list[str]]
    user: User
    analysis_filters: dict[str, str | int]
    schema_resolution: SchemaResolution
    sql_draft: SQLDraft
    validation: ValidationResult
    audit: AuditExplanation
    rows: list[dict[str, Any]]
    chart: VisualizationDraft
    answer: str
    sql_retry_count: int


async def _structured(agent: Any, prompt: str, model_type: type[Any]) -> Any:
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    structured = result.get("structured_response")
    if isinstance(structured, model_type):
        return structured
    if isinstance(structured, dict):
        return model_type.model_validate(structured)
    raise ValueError(f"{model_type.__name__} structured response missing")


def _history_means_past(question: str) -> bool:
    return (
        ("各科" in question or "所有科目" in question)
        and ("历史考试" in question or "历史成绩" in question)
    )


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _recent_exam_limit(question: str) -> int | None:
    match = re.search(
        r"(?:最近|近)\s*([零〇一二两三四五六七八九十\d]+)\s*(?:次|场)\s*考试",
        question,
    )
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        value = int(token)
    elif "十" in token:
        tens, ones = token.split("十", maxsplit=1)
        value = (_CHINESE_DIGITS.get(tens, 1) if tens else 1) * 10
        value += _CHINESE_DIGITS.get(ones, 0) if ones else 0
    else:
        value = _CHINESE_DIGITS.get(token, 0)
    return value if value > 0 else None


def _is_broad_history_question(question: str) -> bool:
    markers = ("历史考试", "历次考试", "过往考试", "以往考试", "近几次考试")
    return _recent_exam_limit(question) is not None or any(
        marker in question for marker in markers
    ) or bool(
        re.search(r"[一二三四五六七八九十\d]+次考试", question)
    )


def _is_personal_history_query(state: QueryState) -> bool:
    question = state["question"]
    user = state["user"]
    explicitly_personal_scores = (
        any(marker in question for marker in ("我", "本人")) and "成绩" in question
    )
    subject_history = (
        any(marker in question for marker in ("各科", "所有科目", "科目"))
        and any(marker in question for marker in ("成绩", "得分率", "趋势"))
    )
    return (
        user.role == UserRole.STUDENT
        and _is_broad_history_question(question)
        and (explicitly_personal_scores or subject_history)
    )


def _is_subject_rate_history_query(question: str) -> bool:
    return (
        _is_broad_history_question(question)
        and any(marker in question for marker in ("各科", "所有科目", "科目"))
        and any(marker in question for marker in ("得分率", "趋势", "折线"))
    )


def _is_failure_query(question: str) -> bool:
    return any(marker in question for marker in ("不及格", "挂科"))


def _query_filters(state: QueryState) -> dict[str, str]:
    return _resolved_filters(state["question"], state["catalog"])


def _recent_exam_predicate(filters: dict[str, str], limit: int) -> str:
    inner_predicates = [
        f"{column} = {_quoted(value)}" for column, value in filters.items()
    ]
    inner_where = (
        f" WHERE {' AND '.join(inner_predicates)}" if inner_predicates else ""
    )
    return (
        "exam_id IN (SELECT exam_id FROM score_facts"
        f"{inner_where} GROUP BY exam_id, exam_date "
        f"ORDER BY exam_date DESC, exam_id DESC LIMIT {limit})"
    )


def _where_clause(
    filters: dict[str, str],
    *,
    failed_only: bool = False,
    recent_exam_limit: int | None = None,
) -> str:
    predicates = [
        f"{column} = {_quoted(value)}" for column, value in filters.items()
    ]
    if failed_only:
        predicates.insert(0, "passed = false")
    if recent_exam_limit is not None:
        predicates.append(_recent_exam_predicate(filters, recent_exam_limit))
    return f" WHERE {' AND '.join(predicates)}" if predicates else ""


def _resolved_filters(question: str, catalog: dict[str, list[str]]) -> dict[str, str]:
    mapping = {
        "classes": "class_name",
        "exams": "exam_name",
        "subjects": "subject_name",
    }
    resolved: dict[str, str] = {}
    for group, column in mapping.items():
        for value in catalog.get(group, []):
            if (
                group == "subjects"
                and value == "历史"
                and _history_means_past(question)
            ):
                # “历史考试各科成绩”里的“历史”表达过往时间，不是历史学科。
                continue
            if value in question:
                resolved[column] = value
                break
    return resolved


def _is_history_subject_equality(node: exp.Expression) -> bool:
    if not isinstance(node, exp.EQ):
        return False
    for column, value in ((node.left, node.right), (node.right, node.left)):
        if (
            isinstance(column, exp.Column)
            and column.name.lower() == "subject_name"
            and isinstance(value, exp.Literal)
            and value.is_string
            and value.this == "历史"
        ):
            return True
    return False


def _strip_history_subject_filter(sql: str) -> str:
    """Remove only the model's ambiguous 历史-subject equality from an AND predicate."""
    try:
        tree = parse_one(sql, read="postgres")
    except ParseError:
        return sql
    where = tree.args.get("where")
    if not isinstance(where, exp.Where):
        return sql

    def strip(node: exp.Expression) -> exp.Expression | None:
        if _is_history_subject_equality(node):
            return None
        if isinstance(node, exp.Paren):
            inner = strip(node.this)
            return exp.Paren(this=inner) if inner is not None else None
        if isinstance(node, exp.And):
            left = strip(node.left)
            right = strip(node.right)
            if left is None:
                return right
            if right is None:
                return left
            return exp.and_(left, right)
        return node

    filtered = strip(where.this)
    if filtered is None:
        tree.set("where", None)
    else:
        where.set("this", filtered)
    return tree.sql(dialect="postgres")


def _fallback_schema(state: QueryState) -> SchemaResolution:
    question = state["question"]
    filters = _resolved_filters(question, state["catalog"])
    columns = ["student_no", "student_name", "exam_name", "subject_name", "score"]
    if "平均" in question or "均分" in question:
        columns = ["average_score"]
    if "趋势" in question:
        columns = ["score_rate", "exam_date", "exam_name"]
    return SchemaResolution(
        intent="成绩查询与分析", relevant_columns=columns, resolved_filters=filters
    )


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _fallback_sql(state: QueryState) -> SQLDraft:
    question = state["question"]
    filters = state["schema_resolution"].resolved_filters
    predicates = [f"{column} = {_quoted(value)}" for column, value in filters.items()]
    if "不及格" in question or "挂科" in question:
        predicates.append("passed = false")
    where = f" WHERE {' AND '.join(predicates)}" if predicates else ""

    if "趋势" in question:
        sql = (
            "SELECT exam_date, exam_name, "
            "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) AS score_rate "
            f"FROM score_facts{where} GROUP BY exam_date, exam_name ORDER BY exam_date"
        )
    elif ("各科" in question or "科目" in question) and ("平均" in question or "均分" in question):
        sql = (
            "SELECT subject_name, ROUND(AVG(score)::numeric, 2) AS average_score, "
            "MAX(max_score) AS max_score "
            f"FROM score_facts{where} GROUP BY subject_name ORDER BY subject_name"
        )
    elif "班" in question and ("平均" in question or "均分" in question):
        sql = (
            "SELECT class_name, "
            "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) AS score_rate "
            f"FROM score_facts{where} GROUP BY class_name ORDER BY class_name"
        )
    elif "最高" in question:
        sql = (
            "SELECT student_no, student_name, exam_name, subject_name, score, max_score, "
            "ROUND((score / NULLIF(max_score, 0))::numeric * 100, 2) AS score_rate "
            f"FROM score_facts{where} ORDER BY score_rate DESC LIMIT 20"
        )
    else:
        sql = (
            "SELECT student_no, student_name, exam_name, subject_name, score, passed "
            f"FROM score_facts{where} ORDER BY exam_date DESC, student_no LIMIT 50"
        )
    return SQLDraft(sql=sql, explanation="本地安全模板生成；配置模型密钥后由 SQL 子智能体生成。")


async def schema_node(state: QueryState) -> dict[str, Any]:
    if (
        _is_failure_query(state["question"])
        or _recent_exam_limit(state["question"]) is not None
        or not registry.enabled
    ):
        return {"schema_resolution": _fallback_schema(state)}
    prompt = json.dumps(
        {
            "question": state.get("llm_question", state["question"]),
            "recent_history": state.get("llm_history", state.get("history", []))[-6:],
            "entity_catalog": state["catalog"],
            "active_analysis_scope": state.get("analysis_filters", {}),
        },
        ensure_ascii=False,
    )
    result = await _structured(registry.schema_agent, prompt, SchemaResolution)
    return {"schema_resolution": result}


async def sql_node(state: QueryState) -> dict[str, Any]:
    recent_exam_limit = _recent_exam_limit(state["question"])
    if _is_failure_query(state["question"]):
        where = _where_clause(
            _query_filters(state),
            failed_only=True,
            recent_exam_limit=recent_exam_limit,
        )
        return {
            "sql_draft": SQLDraft(
                sql=(
                    "SELECT student_no, student_name, class_name, exam_date, exam_name, "
                    "subject_name, score, max_score, pass_score, passed "
                    f"FROM score_facts{where} "
                    "ORDER BY exam_date DESC, subject_name, score, student_no"
                ),
                explanation=(
                    "不及格明细使用确定性安全模板；考试、班级和科目按实体目录解析，"
                    "角色可见范围由服务器注入。"
                ),
            ),
            "sql_retry_count": state.get("sql_retry_count", 0),
        }
    if recent_exam_limit is not None:
        filters = dict(state["schema_resolution"].resolved_filters)
        where = _where_clause(filters, recent_exam_limit=recent_exam_limit)
        if any(marker in state["question"] for marker in ("趋势", "折线")):
            sql = (
                "SELECT exam_date, exam_name, subject_name, "
                "ROUND(AVG(score::numeric / NULLIF(max_score::numeric, 0)) "
                "* 100, 2) AS score_rate "
                f"FROM score_facts{where} "
                "GROUP BY exam_date, exam_name, subject_name "
                "ORDER BY exam_date, subject_name"
            )
            explanation = "最近多次考试趋势使用确定性安全模板。"
        elif any(marker in state["question"] for marker in ("平均", "均分")):
            sql = (
                "SELECT subject_name, ROUND(AVG(score)::numeric, 2) AS average_score, "
                "MAX(max_score) AS max_score, "
                "COUNT(DISTINCT exam_id) AS exam_count "
                f"FROM score_facts{where} "
                "GROUP BY subject_name ORDER BY subject_name"
            )
            explanation = "最近多次考试平均分使用确定性安全模板。"
        else:
            sql = (
                "SELECT student_name, class_name, exam_date, exam_name, subject_name, "
                "score, max_score, pass_score, passed "
                f"FROM score_facts{where} "
                "ORDER BY exam_date DESC, subject_name"
            )
            explanation = "最近多次考试成绩使用确定性安全模板。"
        return {
            "sql_draft": SQLDraft(
                sql=sql,
                explanation=f"{explanation}身份与角色范围由服务器注入。",
            ),
            "sql_retry_count": state.get("sql_retry_count", 0),
        }
    if _is_subject_rate_history_query(state["question"]):
        filters = dict(state["schema_resolution"].resolved_filters)
        if _history_means_past(state["question"]):
            filters.pop("subject_name", None)
        predicates = [
            f"{column} = {_quoted(value)}" for column, value in filters.items()
        ]
        where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
        return {
            "sql_draft": SQLDraft(
                sql=(
                    "SELECT exam_date, exam_name, subject_name, "
                    "ROUND(AVG(score::numeric / NULLIF(max_score::numeric, 0)) "
                    "* 100, 2) AS score_rate "
                    f"FROM score_facts{where} "
                    "GROUP BY exam_date, exam_name, subject_name "
                    "ORDER BY exam_date, subject_name"
                ),
                explanation=(
                    "多次考试各科得分率趋势使用确定性安全模板，"
                    "身份与角色范围由服务器注入。"
                ),
            ),
            "sql_retry_count": state.get("sql_retry_count", 0),
        }
    if _is_personal_history_query(state):
        return {
            "sql_draft": SQLDraft(
                sql=(
                    "SELECT student_name, class_name, exam_date, exam_name, subject_name, "
                    "score, max_score, pass_score, passed FROM score_facts "
                    "ORDER BY exam_date, subject_name"
                ),
                explanation="本人多次考试成绩使用确定性安全模板，身份范围由服务器注入。",
            ),
            "sql_retry_count": state.get("sql_retry_count", 0),
        }
    if not registry.enabled:
        return {"sql_draft": _fallback_sql(state)}
    retry_count = state.get("sql_retry_count", 0)
    payload: dict[str, Any] = {
        "question": state.get("llm_question", state["question"]),
        "schema_resolution": state["schema_resolution"].model_dump(),
        "active_analysis_scope": state.get("analysis_filters", {}),
    }
    if retry_count:
        payload.update(
            {
                "instruction": (
                    "上一次 SQL 未通过确定性安全校验。根据违规原因重新生成；"
                    "不要生成任何用户身份函数、变量或 ID 条件，权限范围由服务器注入。"
                ),
                "previous_sql": mask_student_aliases_in_sql(
                    state["sql_draft"].sql, state.get("student_aliases", {})
                ),
                "validation_violations": state["validation"].violations,
            }
        )
    prompt = json.dumps(payload, ensure_ascii=False)
    result = await _structured(registry.sql_agent, prompt, SQLDraft)
    result = result.model_copy(
        update={
            "sql": restore_student_aliases_in_sql(
                result.sql, state.get("student_aliases", {})
            )
        }
    )
    if _history_means_past(state["question"]):
        result = result.model_copy(update={"sql": _strip_history_subject_filter(result.sql)})
    return {"sql_draft": result, "sql_retry_count": retry_count}


async def validation_node(state: QueryState) -> dict[str, Any]:
    scoped_sql = apply_scope_to_sql(
        state["sql_draft"].sql, state.get("analysis_filters", {})
    )
    result = SQLSafetyGate().validate(scoped_sql)
    return {
        "sql_draft": state["sql_draft"].model_copy(update={"sql": scoped_sql}),
        "validation": result,
    }


IDENTITY_FUNCTION_VIOLATIONS = {
    "FUNCTION_NOT_ALLOWED:current_user_id",
    "FUNCTION_NOT_ALLOWED:current_student_id",
    "FUNCTION_NOT_ALLOWED:current_user",
}


def validation_route(state: QueryState) -> str:
    validation = state["validation"]
    should_retry = (
        registry.enabled
        and not validation.allowed
        and state.get("sql_retry_count", 0) == 0
        and any(item in IDENTITY_FUNCTION_VIOLATIONS for item in validation.violations)
    )
    return "prepare_retry" if should_retry else "audit"


def prepare_sql_retry(_: QueryState) -> dict[str, int]:
    return {"sql_retry_count": 1}


async def audit_node(state: QueryState) -> dict[str, Any]:
    validation = state["validation"]
    if (
        registry.enabled
        and not _is_failure_query(state["question"])
        and _recent_exam_limit(state["question"]) is None
    ):
        prompt = json.dumps(
            {
                "sql": mask_student_aliases_in_sql(
                    state["sql_draft"].sql, state.get("student_aliases", {})
                ),
                "deterministic_allowed": validation.allowed,
                "violations": validation.violations,
            },
            ensure_ascii=False,
        )
        result = await _structured(registry.audit_agent, prompt, AuditExplanation)
    else:
        result = AuditExplanation(
            risk_level="low" if validation.allowed else "high",
            violation_types=validation.violations,
            explanation=(
                "确定性规则与固定查询模板校验通过。"
                if validation.allowed
                else "确定性规则拒绝执行。"
            ),
        )
    return {"audit": result}


def audit_route(state: QueryState) -> str:
    return "execute" if state["validation"].allowed else "denied"


async def execute_node(state: QueryState) -> dict[str, Any]:
    rows = await execute_scoped_query(state["user"], state["validation"])
    return {"rows": rows}


def _fallback_chart(rows: list[dict[str, Any]], question: str) -> VisualizationDraft:
    if not rows:
        return VisualizationDraft(type="none", title="暂无数据", option={})
    keys = list(rows[0])
    value_key = next(
        (
            key
            for key in ("score_rate", "average_score", "score", "pass_rate", "student_count")
            if key in keys
        ),
        None,
    )
    category_key = next(
        (
            key
            for key in ("exam_name", "subject_name", "class_name", "student_name", "student_no")
            if key in keys
        ),
        None,
    )
    if not value_key or not category_key:
        return VisualizationDraft(type="none", title="查询结果", option={})
    chart_type = "line" if "趋势" in question or "exam_date" in keys else "bar"
    title = "得分率趋势" if chart_type == "line" and value_key == "score_rate" else "成绩对比"
    y_axis_max = (
        max(float(row.get("max_score") or 0) for row in rows)
        if value_key == "average_score" and "max_score" in keys
        else 100
    )
    return VisualizationDraft(
        type=chart_type,
        title=title,
        option={
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 24, "top": 56, "bottom": 48},
            "xAxis": {"type": "category", "data": [str(row[category_key]) for row in rows]},
            "yAxis": {"type": "value", "min": 0, "max": y_axis_max},
            "series": [
                {
                    "name": value_key,
                    "type": chart_type,
                    "smooth": chart_type == "line",
                    "data": [float(row[value_key]) for row in rows],
                }
            ],
        },
    )


async def _failure_subject_counts(state: QueryState) -> list[dict[str, Any]]:
    filters = _query_filters(state)
    where = _where_clause(
        filters,
        recent_exam_limit=_recent_exam_limit(state["question"]),
    )
    validation = SQLSafetyGate().validate(
        "SELECT subject_name, "
        "SUM(CASE WHEN passed = false THEN 1 ELSE 0 END) AS failed_count, "
        "COUNT(DISTINCT CASE WHEN passed = false THEN student_id END) AS student_count "
        f"FROM score_facts{where} GROUP BY subject_name ORDER BY subject_name"
    )
    return await execute_scoped_query(state["user"], validation)


def _failure_subject_chart(
    counts: list[dict[str, Any]], state: QueryState
) -> VisualizationDraft:
    filters = _query_filters(state)
    exam_name = filters.get("exam_name")
    title = f"{exam_name}各科不及格人次" if exam_name else "各科不及格人次"
    count_by_subject = {
        str(row["subject_name"]): int(row.get("failed_count") or 0)
        for row in counts
        if row.get("subject_name")
    }
    selected_subject = filters.get("subject_name")
    visible_subjects = set(count_by_subject)
    subjects = (
        [selected_subject]
        if selected_subject
        else [
            subject
            for subject in state["catalog"].get("subjects", [])
            if subject in visible_subjects
        ]
    )
    if not subjects:
        subjects = list(count_by_subject)
    values = [count_by_subject.get(subject, 0) for subject in subjects]
    if not any(values):
        return VisualizationDraft(type="none", title="当前范围内没有不及格记录")
    return VisualizationDraft(
        type="bar",
        title=title,
        option={
            "title": {"text": title, "left": "center", "top": 0},
            "tooltip": {
                "trigger": "item",
                "position": "top",
                "confine": True,
                "axisPointer": {"type": "shadow"},
            },
            "legend": {"show": False},
            "grid": {
                "left": 56,
                "right": 24,
                "top": 72,
                "bottom": 48,
                "containLabel": True,
            },
            "xAxis": {
                "type": "category",
                "data": subjects,
                "axisLabel": {"interval": 0, "hideOverlap": True},
            },
            "yAxis": {
                "type": "value",
                "name": "不及格人次",
                "min": 0,
                "minInterval": 1,
            },
            "series": [
                {
                    "name": "不及格人次",
                    "type": "bar",
                    "data": values,
                    "maxBarWidth": 52,
                    "label": {"show": True, "position": "top"},
                }
            ],
        },
    )


def _subject_score_rate_trend_chart(
    rows: list[dict[str, Any]],
) -> VisualizationDraft | None:
    if not rows:
        return None

    columns = set(rows[0])
    has_score_rate = {"exam_date", "subject_name", "score_rate"}.issubset(columns)
    has_raw_score = {"exam_date", "subject_name", "score", "max_score"}.issubset(
        columns
    )
    if not has_score_rate and not has_raw_score:
        return None

    exams: list[str] = []
    subjects: list[str] = []
    rate_samples: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        exam_date = str(row.get("exam_date") or "")
        subject_name = str(row.get("subject_name") or "")
        if not exam_date or not subject_name:
            continue
        if has_score_rate:
            score_rate = float(row.get("score_rate") or 0)
        else:
            max_score = float(row.get("max_score") or 0)
            if max_score <= 0:
                return VisualizationDraft(
                    type="none",
                    title="科目满分必须大于 0，无法生成得分率趋势图",
                    option={},
                )
            score_rate = float(row.get("score") or 0) / max_score * 100
        if not 0 <= score_rate <= 100:
            return VisualizationDraft(
                type="none",
                title="得分率数据超出 0–100%，无法生成趋势图",
                option={},
            )
        if exam_date not in exams:
            exams.append(exam_date)
        if subject_name not in subjects:
            subjects.append(subject_name)
        rate_samples.setdefault((exam_date, subject_name), []).append(score_rate)

    if len(exams) < 2 or not subjects:
        return None

    rates = {
        key: round(sum(values) / len(values), 2)
        for key, values in rate_samples.items()
    }

    title = "历次考试各科目得分率趋势"
    return VisualizationDraft(
        type="line",
        title=title,
        option={
            "title": {"text": title, "left": "center", "top": 0},
            "tooltip": {"trigger": "axis"},
            "legend": {
                "type": "scroll",
                "top": 36,
                "left": 52,
                "right": 20,
                "itemWidth": 18,
                "itemHeight": 8,
                "itemGap": 16,
            },
            "grid": {
                "left": 56,
                "right": 24,
                "top": 92,
                "bottom": 56,
                "containLabel": True,
            },
            "xAxis": {
                "type": "category",
                "boundaryGap": False,
                "data": exams,
                "axisLabel": {"hideOverlap": True},
            },
            "yAxis": {
                "type": "value",
                "name": "得分率（%）",
                "min": 0,
                "max": 100,
                "interval": 20,
            },
            "series": [
                {
                    "name": subject,
                    "type": "line",
                    "smooth": False,
                    "symbol": "circle",
                    "symbolSize": 6,
                    "connectNulls": False,
                    "data": [rates.get((exam, subject)) for exam in exams],
                }
                for subject in subjects
            ],
        },
    )


async def visualization_node(state: QueryState) -> dict[str, Any]:
    rows = state.get("rows", [])
    if _is_failure_query(state["question"]):
        counts = await _failure_subject_counts(state)
        return {"chart": secure_chart(_failure_subject_chart(counts, state))}
    deterministic_rate_chart = _subject_score_rate_trend_chart(rows)
    if deterministic_rate_chart:
        return {"chart": secure_chart(deterministic_rate_chart)}
    if _recent_exam_limit(state["question"]) is not None:
        return {"chart": secure_chart(_fallback_chart(rows, state["question"]))}
    if not registry.enabled:
        return {"chart": secure_chart(_fallback_chart(rows, state["question"]))}
    prompt = json.dumps(
        {
            "question": state.get("llm_question", state["question"]),
            "rows": rows_for_llm(rows[:100], state.get("student_aliases", {})),
        },
        ensure_ascii=False,
        default=str,
    )
    result = await _structured(registry.visualization_agent, prompt, VisualizationDraft)
    chart = secure_chart(result)
    if result.type != "none" and chart.type == "none":
        fallback = secure_chart(_fallback_chart(rows, state["question"]))
        logger.warning(
            "model_chart_rejected_using_fallback",
            model_chart_type=result.type,
            fallback_chart_type=fallback.type,
        )
        return {"chart": fallback}
    return {"chart": chart}


async def final_node(state: QueryState) -> dict[str, Any]:
    rows = state.get("rows", [])
    if _is_failure_query(state["question"]):
        chart = state.get("chart", VisualizationDraft())
        if chart.type == "none":
            return {"answer": "当前查询范围内没有不及格记录。"}
        subjects = chart.option.get("xAxis", {}).get("data", [])
        values = chart.option.get("series", [{}])[0].get("data", [])
        counts = [
            (str(subject), int(value))
            for subject, value in zip(subjects, values, strict=False)
            if int(value) > 0
        ]
        total = sum(value for _, value in counts)
        top_subjects = sorted(counts, key=lambda item: item[1], reverse=True)[:3]
        top_text = "、".join(f"{subject}{count}人次" for subject, count in top_subjects)
        exam_name = _query_filters(state).get("exam_name")
        recent_exam_limit = _recent_exam_limit(state["question"])
        scope = exam_name or (
            f"最近{recent_exam_limit}次考试"
            if recent_exam_limit is not None
            else "当前查询范围"
        )
        detail_note = (
            f"下方显示其中{len(rows)}条明细。"
            if len(rows) < total
            else "详细记录见下方表格。"
        )
        return {
            "answer": (
                f"{scope}共有{total}人次不及格；"
                f"不及格人次较多的科目为{top_text}。{detail_note}"
            )
        }
    recent_exam_limit = _recent_exam_limit(state["question"])
    if recent_exam_limit is not None:
        if not rows:
            return {"answer": f"最近{recent_exam_limit}次考试内没有找到符合条件的数据。"}

        question = state["question"]
        if any(marker in question for marker in ("平均", "均分")):
            actual_exam_count = max(int(row.get("exam_count") or 0) for row in rows)
            if len(rows) == 1:
                row = rows[0]
                subject_name = str(row.get("subject_name") or "该科目")
                average_score = float(row.get("average_score") or 0)
                if actual_exam_count < recent_exam_limit:
                    return {
                        "answer": (
                            f"查询最近{recent_exam_limit}次考试，实际找到"
                            f"{actual_exam_count}次；{subject_name}平均分为"
                            f"{average_score:.2f}分。"
                        )
                    }
                return {
                    "answer": (
                        f"最近{recent_exam_limit}次考试{subject_name}"
                        f"平均分为{average_score:.2f}分。"
                    )
                }
            return {
                "answer": (
                    f"已统计最近{actual_exam_count}次考试的{len(rows)}个科目平均分，"
                    "详见下方图表和数据。"
                )
            }

        exams = {
            (str(row.get("exam_date", "")), str(row.get("exam_name", "")))
            for row in rows
            if row.get("exam_name")
        }
        subjects = {str(row["subject_name"]) for row in rows if row.get("subject_name")}
        if any(marker in question for marker in ("趋势", "折线")):
            return {
                "answer": (
                    f"已汇总最近{len(exams)}次考试、{len(subjects)}个科目的成绩趋势，"
                    "详见下方图表和数据。"
                )
            }
        if len(rows) == 1 and rows[0].get("score") is not None:
            row = rows[0]
            return {
                "answer": (
                    f"最近一次{row.get('exam_name', '考试')}中，"
                    f"{row.get('subject_name', '该科目')}成绩为{row['score']}分。"
                )
            }
        return {
            "answer": (
                f"已汇总最近{len(exams)}次考试、{len(subjects)}个科目的成绩；"
                "详细分数见下方成绩档案。"
            )
        }
    if rows and _is_broad_history_question(state["question"]):
        exams = {
            (str(row.get("exam_date", "")), str(row.get("exam_name", "")))
            for row in rows
            if row.get("exam_name")
        }
        subjects = {str(row["subject_name"]) for row in rows if row.get("subject_name")}
        if len(exams) > 1:
            latest_date, latest_name = max(exams)
            latest_rows = [
                row
                for row in rows
                if str(row.get("exam_date", "")) == latest_date
                and str(row.get("exam_name", "")) == latest_name
            ]
            passed = sum(bool(row.get("passed")) for row in latest_rows)
            student_name = next(
                (str(row["student_name"]) for row in rows if row.get("student_name")),
                "该学生",
            )
            return {
                "answer": (
                    f"已汇总{student_name}{len(exams)}次考试、{len(subjects)}个科目的成绩；"
                    f"最近一次{latest_name}{passed}/{len(latest_rows)}科合格。"
                    "详细分数、总分和排名见下方成绩档案。"
                )
            }
    if not registry.enabled:
        answer = f"查询完成，共返回 {len(rows)} 条结果。" if rows else "没有找到符合条件的数据。"
        return {"answer": answer}

    prompt = json.dumps(
        {
            "instruction": "只根据数据形成不超过120字的中文回答，不要调用子智能体。",
            "question": state.get("llm_question", state["question"]),
            "rows": rows_for_llm(rows[:50], state.get("student_aliases", {})),
            "chart_type": state.get("chart", VisualizationDraft()).type,
        },
        ensure_ascii=False,
        default=str,
    )
    result = await registry.orchestrator.ainvoke(
        {"messages": [{"role": "user", "content": prompt}]}
    )
    messages = result.get("messages", [])
    answer = messages[-1].content if messages else "查询完成。"
    return {"answer": str(answer)}


async def denied_node(state: QueryState) -> dict[str, Any]:
    violations = "、".join(state["validation"].violations)
    return {
        "rows": [],
        "chart": VisualizationDraft(),
        "answer": f"查询被安全策略拒绝：{violations}",
    }


def build_query_graph() -> Any:
    graph = StateGraph(QueryState)
    graph.add_node("schema", schema_node)
    graph.add_node("sql", sql_node)
    graph.add_node("prepare_retry", prepare_sql_retry)
    graph.add_node("validate", validation_node)
    graph.add_node("audit", audit_node)
    graph.add_node("execute", execute_node)
    graph.add_node("visualize", visualization_node)
    graph.add_node("final", final_node)
    graph.add_node("denied", denied_node)
    graph.add_edge(START, "schema")
    graph.add_edge("schema", "sql")
    graph.add_edge("sql", "validate")
    graph.add_conditional_edges(
        "validate", validation_route, {"prepare_retry": "prepare_retry", "audit": "audit"}
    )
    graph.add_edge("prepare_retry", "sql")
    graph.add_conditional_edges("audit", audit_route, {"execute": "execute", "denied": "denied"})
    graph.add_edge("execute", "visualize")
    graph.add_edge("visualize", "final")
    graph.add_edge("final", END)
    graph.add_edge("denied", END)
    return graph.compile()


query_graph = build_query_graph()
