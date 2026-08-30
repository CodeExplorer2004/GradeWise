import json

from app.services.privacy import (
    StudentAlias,
    mask_student_aliases_in_sql,
    redact_student_text,
    restore_student_aliases_in_sql,
    rows_for_llm,
)

ALIASES: dict[str, StudentAlias] = {
    "S-ABCDEF12": {"student_name": "测试学生", "student_no": "20260001"}
}


def test_question_and_rows_are_redacted_for_llm() -> None:
    question = "查询测试学生（20260001）的数学成绩"
    rows = [
        {
            "student_id": 7,
            "student_name": "测试学生",
            "student_no": "20260001",
            "subject_name": "数学",
            "score": 92,
        }
    ]

    redacted_question = redact_student_text(question, ALIASES)
    redacted_rows = rows_for_llm(rows, ALIASES)
    outbound = json.dumps(
        {"question": redacted_question, "rows": redacted_rows}, ensure_ascii=False
    )

    assert "测试学生" not in outbound
    assert "20260001" not in outbound
    assert '"student_id"' not in outbound
    assert '"student_name"' not in outbound
    assert '"student_no"' not in outbound
    assert "student_ref" in outbound


def test_student_alias_is_restored_only_for_execution_and_masked_for_audit() -> None:
    generated = (
        "SELECT student_name, score FROM score_facts "
        "WHERE student_name = 'S-ABCDEF12'"
    )

    restored = restore_student_aliases_in_sql(generated, ALIASES)
    masked = mask_student_aliases_in_sql(restored, ALIASES)

    assert "测试学生" in restored
    assert "S-ABCDEF12" not in restored
    assert "测试学生" not in masked
    assert "S-ABCDEF12" in masked


def test_unknown_long_number_is_redacted() -> None:
    assert redact_student_text("编号 1234567890", {}) == "编号 [已脱敏编号]"
