from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.models import RiskSnapshot, User
from app.core.schemas import RiskPrediction, RiskSummaryResponse
from app.services.analysis_scope import filter_where
from app.services.sql_security import SQLSafetyGate, execute_scoped_query

MODEL_VERSION = "transparent-rule-v2"
RISK_PAGE_SIZE = max(1, get_settings().query_max_rows)
SNAPSHOT_BATCH_SIZE = 500
DISCLAIMER = (
    "该结果是基于最近成绩、历史不及格比例、趋势和波动的透明规则估计，"
    "仅用于教学关注排序，不代表对学生能力的判断。"
)


def _clamp(value: float, lower: float = 0, upper: float = 1) -> float:
    return max(lower, min(upper, value))


def _number(value: Any) -> float:
    return float(value or 0)


def prediction_from_row(row: dict[str, Any]) -> RiskPrediction:
    latest = _number(row["latest_score"])
    first = _number(row["first_score"])
    pass_score = _number(row["pass_score"]) or 60
    max_score = _number(row.get("max_score")) or 100
    volatility = _number(row["volatility"])
    failure_ratio = _number(row["failure_ratio"])
    trend = latest - first
    latest_rate = latest / max_score * 100
    first_rate = first / max_score * 100
    pass_rate = pass_score / max_score * 100
    trend_rate = latest_rate - first_rate
    volatility_rate = volatility / max_score * 100

    margin_risk = _clamp((pass_rate + 10 - latest_rate) / 25)
    decline_risk = _clamp(-trend_rate / 25)
    volatility_risk = _clamp(volatility_rate / 18)
    risk_score = round(
        (0.4 * margin_risk + 0.3 * failure_ratio + 0.2 * decline_risk + 0.1 * volatility_risk)
        * 100,
        1,
    )
    if risk_score >= 65:
        level = "high"
    elif risk_score >= 35:
        level = "medium"
    else:
        level = "low"

    reasons: list[str] = []
    if latest < pass_score:
        reasons.append(f"最近成绩 {latest:.1f} 分，低于及格线 {pass_score:.1f} 分")
    elif latest_rate < pass_rate + 10:
        reasons.append(f"最近成绩距离及格线仅 {latest - pass_score:.1f} 分")
    if failure_ratio >= 0.34:
        reasons.append(f"历史未及格比例为 {failure_ratio * 100:.0f}%")
    if trend_rate <= -10:
        reasons.append(f"较首场同科考试得分率下降 {abs(trend_rate):.1f} 个百分点")
    if volatility_rate >= 12:
        reasons.append(f"历次成绩得分率标准差为 {volatility_rate:.1f} 个百分点，波动较大")
    if not reasons:
        reasons.append("当前未见显著风险特征")

    return RiskPrediction(
        student_id=int(row["student_id"]),
        class_id=int(row["class_id"]),
        subject_id=int(row["subject_id"]),
        student_name=str(row["student_name"]),
        class_name=str(row["class_name"]),
        subject_name=str(row["subject_name"]),
        risk_score=risk_score,
        risk_level=level,
        latest_score=round(latest, 2),
        trend=round(trend, 2),
        volatility=round(volatility, 2),
        failure_ratio=round(failure_ratio, 4),
        exam_count=int(row["exam_count"]),
        reasons=reasons,
    )


async def collect_risk_predictions(
    user: User, filters: dict[str, str | int] | None = None
) -> list[RiskPrediction]:
    where = filter_where(filters)
    base_sql = (
        "SELECT DISTINCT student_id, student_name, "
        "FIRST_VALUE(class_id) OVER (PARTITION BY student_id, subject_id "
        "ORDER BY exam_date DESC, exam_id DESC) AS class_id, "
        "FIRST_VALUE(class_name) OVER (PARTITION BY student_id, subject_id "
        "ORDER BY exam_date DESC, exam_id DESC) AS class_name, subject_id, "
        "subject_name, FIRST_VALUE(score) OVER (PARTITION BY student_id, subject_id "
        "ORDER BY exam_date DESC, exam_id DESC) AS latest_score, "
        "FIRST_VALUE(score) OVER (PARTITION BY student_id, subject_id "
        "ORDER BY exam_date, exam_id) AS first_score, "
        "FIRST_VALUE(pass_score) OVER (PARTITION BY student_id, subject_id "
        "ORDER BY exam_date DESC, exam_id DESC) AS pass_score, "
        "FIRST_VALUE(max_score) OVER (PARTITION BY student_id, subject_id "
        "ORDER BY exam_date DESC, exam_id DESC) AS max_score, "
        "STDDEV_POP(score) OVER (PARTITION BY student_id, subject_id) AS volatility, "
        "AVG(CASE WHEN passed THEN 0 ELSE 1 END) OVER (PARTITION BY student_id, subject_id) "
        "AS failure_ratio, COUNT(*) OVER (PARTITION BY student_id, subject_id) AS exam_count "
        f"FROM score_facts{where} ORDER BY student_id, subject_id"
    )
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        validation = SQLSafetyGate().validate(
            f"{base_sql} LIMIT {RISK_PAGE_SIZE} OFFSET {offset}"
        )
        if not validation.allowed:
            raise RuntimeError(f"Internal risk query rejected: {validation.violations}")
        page = await execute_scoped_query(user, validation)
        rows.extend(page)
        if len(page) < RISK_PAGE_SIZE:
            break
        offset += RISK_PAGE_SIZE

    predictions = _deduplicate_predictions([prediction_from_row(row) for row in rows])
    return sorted(predictions, key=lambda item: item.risk_score, reverse=True)


def _deduplicate_predictions(predictions: list[RiskPrediction]) -> list[RiskPrediction]:
    unique: dict[tuple[int, int], RiskPrediction] = {}
    for item in predictions:
        unique[(item.student_id, item.subject_id)] = item
    return list(unique.values())


def risk_summary(predictions: list[RiskPrediction]) -> RiskSummaryResponse:
    return RiskSummaryResponse(
        model_version=MODEL_VERSION,
        disclaimer=DISCLAIMER,
        predictions=predictions[:100],
        high_count=sum(item.risk_level == "high" for item in predictions),
        medium_count=sum(item.risk_level == "medium" for item in predictions),
    )


async def persist_risk_snapshots(
    session: AsyncSession,
    school_id: int,
    predictions: list[RiskPrediction],
) -> None:
    predictions = _deduplicate_predictions(predictions)
    if not predictions:
        return
    for start in range(0, len(predictions), SNAPSHOT_BATCH_SIZE):
        values = [
            {
                "school_id": school_id,
                "student_id": item.student_id,
                "class_id": item.class_id,
                "subject_id": item.subject_id,
                "risk_score": item.risk_score,
                "risk_level": item.risk_level,
                "latest_score": item.latest_score,
                "trend": item.trend,
                "volatility": item.volatility,
                "failure_ratio": item.failure_ratio,
                "reasons": item.reasons,
            }
            for item in predictions[start : start + SNAPSHOT_BATCH_SIZE]
        ]
        statement = insert(RiskSnapshot).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[RiskSnapshot.student_id, RiskSnapshot.subject_id],
            set_={
                "school_id": statement.excluded.school_id,
                "class_id": statement.excluded.class_id,
                "risk_score": statement.excluded.risk_score,
                "risk_level": statement.excluded.risk_level,
                "latest_score": statement.excluded.latest_score,
                "trend": statement.excluded.trend,
                "volatility": statement.excluded.volatility,
                "failure_ratio": statement.excluded.failure_ratio,
                "reasons": statement.excluded.reasons,
                "computed_at": func.now(),
            },
        )
        await session.execute(statement)
    await session.commit()
