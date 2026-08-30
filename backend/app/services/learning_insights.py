from __future__ import annotations

from typing import Any, Literal

from app.core.models import User
from app.core.schemas import AlertPageResponse, InsightsResponse, LearningAlert, ScoreBand
from app.services.privacy import student_reference
from app.services.sql_security import SQLSafetyGate, execute_scoped_query

AlertType = Literal["anomaly", "fluctuation", "current_risk"]
InsightFilters = dict[str, str | int]
FILTER_COLUMNS = {"class_name", "subject_name", "exam_name"}
FILTER_COLUMNS.update(
    {"academic_year", "grade_level", "term", "exam_type", "cohort_year"}
)

ANOMALY_SOURCE = (
    "FROM (SELECT student_id, student_name, class_name, exam_name, subject_name, score, "
    "AVG(score) OVER (PARTITION BY class_id, exam_id, subject_id) AS peer_average, "
    "(AVG(score) OVER (PARTITION BY class_id, exam_id, subject_id) - score) / "
    "NULLIF(STDDEV_POP(score) OVER (PARTITION BY class_id, exam_id, subject_id), 0) "
    "AS z_score FROM score_facts) score_stats WHERE z_score >= 2"
)
FLUCTUATION_SOURCE = (
    "FROM (SELECT student_id, student_name, class_name, exam_name, exam_date, exam_id, "
    "subject_id, subject_name, score, max_score, "
    "score / NULLIF(max_score, 0) AS score_rate, "
    "LAG(score) OVER (PARTITION BY student_id, subject_id "
    "ORDER BY exam_date, exam_id) AS previous_score, "
    "LAG(score / NULLIF(max_score, 0)) OVER (PARTITION BY student_id, subject_id "
    "ORDER BY exam_date, exam_id) AS previous_score_rate FROM score_facts) score_changes "
    "WHERE previous_score IS NOT NULL AND ABS(score_rate - previous_score_rate) >= 0.15"
)
CURRENT_RISK_SOURCE = (
    "FROM (SELECT student_id, student_name, class_name, exam_name, exam_date, exam_id, "
    "subject_id, subject_name, score, max_score, pass_score, ROW_NUMBER() OVER ("
    "PARTITION BY student_id, subject_id ORDER BY exam_date DESC, exam_id DESC) AS latest_rank "
    "FROM score_facts) latest_scores WHERE latest_rank = 1 AND score < pass_score"
)


async def _safe_query(user: User, sql: str) -> list[dict[str, Any]]:
    validation = SQLSafetyGate().validate(sql)
    if not validation.allowed:
        raise RuntimeError(f"Internal insight query rejected: {validation.violations}")
    return await execute_scoped_query(user, validation)


def _quoted(value: str | int) -> str:
    if isinstance(value, int):
        return str(value)
    return "'" + value.replace("'", "''") + "'"


def _filter_predicate(filters: InsightFilters | None) -> str:
    if not filters:
        return ""
    predicates = [
        f"{column} = {_quoted(value)}"
        for column, value in filters.items()
        if column in FILTER_COLUMNS and value
    ]
    return " AND ".join(predicates)


def _where(filters: InsightFilters | None) -> str:
    predicate = _filter_predicate(filters)
    return f" WHERE {predicate}" if predicate else ""


def _filtered_source(source: str, filters: InsightFilters | None) -> str:
    predicate = _filter_predicate(filters)
    if not predicate:
        return source
    return source.replace("FROM score_facts)", f"FROM score_facts WHERE {predicate})")


def _number(value: Any) -> float:
    return round(float(value or 0), 2)


def _to_alert(alert_type: AlertType, row: dict[str, Any]) -> LearningAlert:
    common = {
        "student_id": int(row["student_id"]),
        "student_name": str(row["student_name"]),
        "class_name": str(row["class_name"]),
        "subject_name": str(row["subject_name"]),
        "exam_name": str(row["exam_name"]),
        "current_score": _number(row["score"]),
    }
    if alert_type == "anomaly":
        z_score = _number(row["z_score"])
        return LearningAlert(
            type=alert_type,
            severity="high" if z_score >= 3 else "medium",
            title="同组成绩异常",
            detail=f"低于同班同科均值 {z_score} 个标准差",
            reference_score=_number(row["peer_average"]),
            **common,
        )
    if alert_type == "fluctuation":
        change_rate = _number(row["change_rate"])
        return LearningAlert(
            type=alert_type,
            severity="high" if change_rate >= 25 else "medium",
            title="成绩波动预警",
            detail=f"较上次同科得分率变化 {change_rate} 个百分点",
            reference_score=_number(row["previous_score"]),
            **common,
        )
    return LearningAlert(
        type=alert_type,
        severity=(
            "high"
            if _number(row["score"]) / max(_number(row["max_score"]), 1) < 0.5
            else "medium"
        ),
        title="最新成绩未达及格线",
        detail=f"当前 {_number(row['score'])} 分，及格线 {_number(row['pass_score'])} 分",
        reference_score=_number(row["pass_score"]),
        **common,
    )


def _alert_query(alert_type: AlertType, filters: InsightFilters | None = None) -> str:
    sources = {
        "anomaly": _filtered_source(ANOMALY_SOURCE, filters),
        "fluctuation": _filtered_source(FLUCTUATION_SOURCE, filters),
        "current_risk": _filtered_source(CURRENT_RISK_SOURCE, filters),
    }
    if alert_type == "anomaly":
        return (
            "SELECT student_id, student_name, class_name, exam_name, subject_name, score, "
            "ROUND(peer_average::numeric, 2) AS peer_average, "
            f"ROUND(z_score::numeric, 2) AS z_score {sources['anomaly']} "
            "ORDER BY z_score DESC, student_id"
        )
    if alert_type == "fluctuation":
        return (
            "SELECT student_id, student_name, class_name, exam_name, subject_name, score, "
            "previous_score, ROUND((ABS(score_rate - previous_score_rate) * 100)::numeric, 2) "
            f"AS change_rate {sources['fluctuation']} ORDER BY change_rate DESC, student_id"
        )
    return (
        "SELECT student_id, student_name, class_name, exam_name, subject_name, score, "
        "max_score, pass_score "
        f"{sources['current_risk']} ORDER BY score, student_id"
    )


async def _alert_count(
    user: User, alert_type: AlertType, filters: InsightFilters | None = None
) -> int:
    source = {
        "anomaly": ANOMALY_SOURCE,
        "fluctuation": FLUCTUATION_SOURCE,
        "current_risk": CURRENT_RISK_SOURCE,
    }[alert_type]
    rows = await _safe_query(
        user, f"SELECT COUNT(*) AS total {_filtered_source(source, filters)}"
    )
    return int(rows[0]["total"] if rows else 0)


async def _alerts(
    user: User,
    alert_type: AlertType,
    *,
    limit: int,
    offset: int = 0,
    filters: InsightFilters | None = None,
) -> list[LearningAlert]:
    rows = await _safe_query(
        user,
        f"{_alert_query(alert_type, filters)} LIMIT {int(limit)} OFFSET {int(offset)}",
    )
    return [_to_alert(alert_type, row) for row in rows]


async def collect_alert_page(
    user: User,
    alert_type: AlertType,
    page: int,
    page_size: int,
    filters: InsightFilters | None = None,
) -> AlertPageResponse:
    total = await _alert_count(user, alert_type, filters)
    items = await _alerts(
        user,
        alert_type,
        limit=page_size,
        offset=(page - 1) * page_size,
        filters=filters,
    )
    return AlertPageResponse(
        alert_type=alert_type,
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


async def collect_learning_insights(
    user: User, filters: InsightFilters | None = None
) -> InsightsResponse:
    where = _where(filters)
    predicate = _filter_predicate(filters)
    metrics_rows = await _safe_query(
        user,
        "SELECT ROUND(AVG(score)::numeric, 2) AS average_score, "
        "ROUND(AVG(score / NULLIF(max_score, 0))::numeric * 100, 2) "
        "AS overall_score_rate, "
        "ROUND(AVG(CASE WHEN passed THEN 1 ELSE 0 END)::numeric * 100, 2) AS pass_rate "
        f"FROM score_facts{where}",
    )
    distribution_rows = await _safe_query(
        user,
        "SELECT score_band, COUNT(*) AS count FROM ("
        "SELECT CASE WHEN student_score_rate >= 90 THEN '90-100%' "
        "WHEN student_score_rate >= 80 THEN '80-89%' "
        "WHEN student_score_rate >= 70 THEN '70-79%' "
        "WHEN student_score_rate >= 60 THEN '60-69%' ELSE '0-59%' END AS score_band, "
        "CASE WHEN student_score_rate >= 90 THEN 1 WHEN student_score_rate >= 80 THEN 2 "
        "WHEN student_score_rate >= 70 THEN 3 WHEN student_score_rate >= 60 THEN 4 ELSE 5 END "
        "AS band_order FROM (SELECT student_id, "
        "AVG(score / NULLIF(max_score, 0)) * 100 AS student_score_rate "
        "FROM score_facts WHERE "
        + (f"{predicate} AND " if predicate else "")
        + "exam_date = (SELECT MAX(exam_date) FROM score_facts"
        + (f" WHERE {predicate}" if predicate else "")
        + ") "
        "GROUP BY student_id) student_averages) banded "
        "GROUP BY score_band, band_order ORDER BY band_order",
    )
    latest_exam_rows = await _safe_query(
        user,
        f"SELECT exam_name FROM score_facts{where} "
        "ORDER BY exam_date DESC, exam_id DESC LIMIT 1",
    )

    alert_types: tuple[AlertType, ...] = ("anomaly", "fluctuation", "current_risk")
    alert_counts = {
        alert_type: await _alert_count(user, alert_type, filters) for alert_type in alert_types
    }
    anomalies = await _alerts(user, "anomaly", limit=20, filters=filters)
    fluctuations = await _alerts(user, "fluctuation", limit=20, filters=filters)
    current_risks = await _alerts(user, "current_risk", limit=20, filters=filters)

    metrics = metrics_rows[0] if metrics_rows else {}
    distribution = [
        ScoreBand(label=str(row["score_band"]), count=int(row["count"]))
        for row in distribution_rows
    ]
    return InsightsResponse(
        average_score=_number(metrics.get("average_score")),
        overall_score_rate=_number(metrics.get("overall_score_rate")),
        pass_rate=_number(metrics.get("pass_rate")),
        score_distribution=distribution,
        distribution_exam_name=str(latest_exam_rows[0]["exam_name"]) if latest_exam_rows else "",
        distribution_sample_size=sum(item.count for item in distribution),
        anomalies=anomalies,
        fluctuations=fluctuations,
        current_risks=current_risks,
        alert_count=sum(alert_counts.values()),
        alert_counts=alert_counts,
    )


def insights_for_llm(insights: InsightsResponse) -> dict[str, Any]:
    def masked(alert: LearningAlert) -> dict[str, Any]:
        return {
            "student_ref": student_reference(alert.student_id),
            "class_name": alert.class_name,
            "subject_name": alert.subject_name,
            "exam_name": alert.exam_name,
            "type": alert.type,
            "severity": alert.severity,
            "current_score": alert.current_score,
            "reference_score": alert.reference_score,
            "detail": alert.detail,
        }

    return {
        "overall_score_rate": insights.overall_score_rate,
        "pass_rate": insights.pass_rate,
        "distribution_exam_name": insights.distribution_exam_name,
        "score_distribution": [item.model_dump() for item in insights.score_distribution],
        "anomalies": [masked(item) for item in insights.anomalies[:8]],
        "fluctuations": [masked(item) for item in insights.fluctuations[:8]],
        "current_risks": [masked(item) for item in insights.current_risks[:8]],
        "alert_count": insights.alert_count,
        "alert_counts": insights.alert_counts,
    }
