import hashlib
import hmac
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.models import Student
from app.core.schemas import RiskPrediction


def student_reference(student_id: int) -> str:
    secret = get_settings().jwt_secret.encode()
    digest = hmac.new(secret, str(student_id).encode(), hashlib.sha256).hexdigest()
    return f"S-{digest[:8].upper()}"


def risks_for_llm(predictions: list[RiskPrediction]) -> list[dict[str, object]]:
    return [
        {
            "student_ref": student_reference(item.student_id),
            "class_name": item.class_name,
            "subject_name": item.subject_name,
            "risk_score": item.risk_score,
            "risk_level": item.risk_level,
            "latest_score": item.latest_score,
            "trend": item.trend,
            "volatility": item.volatility,
            "failure_ratio": item.failure_ratio,
            "exam_count": item.exam_count,
            "reasons": item.reasons,
        }
        for item in predictions[:100]
    ]


def risk_batch_evidence(predictions: list[RiskPrediction]) -> dict[str, object]:
    attention_items = [item for item in predictions if item.risk_level != "low"]
    items = risks_for_llm(attention_items)
    return {
        "deterministic_summary": {
            "total_predictions": len(predictions),
            "high_count": sum(item.risk_level == "high" for item in predictions),
            "medium_count": sum(item.risk_level == "medium" for item in predictions),
            "low_count": sum(item.risk_level == "low" for item in predictions),
            "evidence_items_count": len(items),
            "evidence_note": "仅提供中高风险明细，按风险分数排序，最多前100条",
        },
        "items": items,
    }


async def redact_student_identifiers(
    session: AsyncSession,
    school_id: int,
    text: str,
) -> str:
    students = list(
        (await session.scalars(select(Student).where(Student.school_id == school_id))).all()
    )
    redacted = text
    for student in students:
        reference = student_reference(student.id)
        redacted = redacted.replace(student.display_name, reference)
        redacted = redacted.replace(student.student_no, reference)
    return re.sub(r"(?<!\d)\d{8,}(?!\d)", "[已脱敏编号]", redacted)
