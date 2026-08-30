import hashlib
import hmac
import re
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from app.core.config import get_settings
from app.core.models import Student
from app.core.schemas import RiskPrediction


class StudentAlias(TypedDict):
    student_name: str
    student_no: str


def _reference(value: str) -> str:
    secret = get_settings().jwt_secret.encode()
    digest = hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()
    return f"S-{digest[:8].upper()}"


def student_reference(student_id: int) -> str:
    return _reference(f"student-id:{student_id}")


def student_identifier_reference(value: object) -> str:
    return _reference(f"student-identifier:{value}")


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


def redact_student_text(text: str, aliases: dict[str, StudentAlias]) -> str:
    redacted = text
    replacements = {
        value: alias
        for alias, student in aliases.items()
        for value in (student["student_name"], student["student_no"])
        if value
    }
    for value in sorted(replacements, key=len, reverse=True):
        redacted = redacted.replace(value, replacements[value])
    return re.sub(r"(?<!\d)\d{8,}(?!\d)", "[已脱敏编号]", redacted)


async def build_student_aliases(
    session: AsyncSession, school_id: int
) -> dict[str, StudentAlias]:
    students = list(
        (await session.scalars(select(Student).where(Student.school_id == school_id))).all()
    )
    return {
        student_reference(student.id): {
            "student_name": student.display_name,
            "student_no": student.student_no,
        }
        for student in students
    }


def rows_for_llm(
    rows: list[dict[str, Any]], aliases: dict[str, StudentAlias]
) -> list[dict[str, Any]]:
    alias_by_value = {
        value: alias
        for alias, student in aliases.items()
        for value in (student["student_name"], student["student_no"])
        if value
    }
    redacted_rows: list[dict[str, Any]] = []
    for row in rows:
        identity = row.get("student_id") or row.get("student_no") or row.get("student_name")
        reference = None
        if row.get("student_id") is not None:
            reference = student_reference(int(row["student_id"]))
        elif identity is not None:
            reference = alias_by_value.get(str(identity)) or student_identifier_reference(identity)
        redacted = {
            key: value
            for key, value in row.items()
            if key not in {"student_id", "student_no", "student_name"}
        }
        if reference:
            redacted["student_ref"] = reference
        redacted_rows.append(redacted)
    return redacted_rows


def _student_column(node: exp.Literal) -> str | None:
    parent = node.parent
    if parent is None:
        return None
    columns = {
        column.name.lower()
        for column in parent.find_all(exp.Column)
        if column.name.lower() in {"student_name", "student_no"}
    }
    return next(iter(columns)) if len(columns) == 1 else None


def restore_student_aliases_in_sql(sql: str, aliases: dict[str, StudentAlias]) -> str:
    try:
        tree = parse_one(sql, read="postgres")
    except ParseError:
        return sql

    def restore(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Literal) and node.is_string and node.this in aliases:
            column = _student_column(node)
            if column:
                return exp.Literal.string(aliases[node.this][column])
        return node

    return tree.transform(restore).sql(dialect="postgres")


def mask_student_aliases_in_sql(sql: str, aliases: dict[str, StudentAlias]) -> str:
    try:
        tree = parse_one(sql, read="postgres")
    except ParseError:
        return redact_student_text(sql, aliases)

    def mask(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Literal) and node.is_string:
            column = _student_column(node)
            if column:
                for alias, student in aliases.items():
                    if node.this == student[column]:
                        return exp.Literal.string(alias)
        return node

    return tree.transform(mask).sql(dialect="postgres")


async def redact_student_identifiers(
    session: AsyncSession,
    school_id: int,
    text: str,
) -> str:
    return redact_student_text(text, await build_student_aliases(session, school_id))
