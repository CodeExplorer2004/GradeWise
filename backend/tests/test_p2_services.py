import json

import pytest

from app.core.scoring import has_valid_score_increment, quantize_score
from app.core.seed import (
    DEMO_CLASS_COUNT,
    DEMO_EXAMS,
    DEMO_STUDENTS_PER_CLASS,
    DEMO_SUBJECT_SCHEMES,
    GRADE_SUBJECT_CODES,
    build_demo_score_values,
)
from app.services.privacy import risks_for_llm, student_reference
from app.services.risk_prediction import prediction_from_row, risk_summary
from app.services.score_import import parse_score_file, score_validation_error


def test_predictive_risk_is_explainable_and_high_for_declining_failures() -> None:
    prediction = prediction_from_row(
        {
            "student_id": 7,
            "student_name": "测试学生",
            "class_id": 1,
            "class_name": "高一（1）班",
            "subject_id": 2,
            "subject_name": "数学",
            "latest_score": 42,
            "first_score": 75,
            "pass_score": 60,
            "volatility": 15,
            "failure_ratio": 0.67,
            "exam_count": 3,
        }
    )

    assert prediction.risk_level == "high"
    assert prediction.risk_score >= 65
    assert any("低于及格线" in reason for reason in prediction.reasons)
    assert any("下降" in reason for reason in prediction.reasons)


def test_risk_llm_payload_uses_hmac_reference_without_identity() -> None:
    prediction = prediction_from_row(
        {
            "student_id": 7,
            "student_name": "测试学生",
            "class_id": 1,
            "class_name": "高一（1）班",
            "subject_id": 2,
            "subject_name": "数学",
            "latest_score": 58,
            "first_score": 65,
            "pass_score": 60,
            "volatility": 5,
            "failure_ratio": 0.34,
            "exam_count": 3,
        }
    )
    payload = risks_for_llm([prediction])

    assert payload[0]["student_ref"] == student_reference(7)
    assert "测试学生" not in str(payload)
    assert "student_id" not in str(payload)


def test_risk_summary_limits_response_but_preserves_counts() -> None:
    predictions = []
    for index in range(110):
        item = prediction_from_row(
            {
                "student_id": index + 1,
                "student_name": f"学生{index}",
                "class_id": 1,
                "class_name": "高一（1）班",
                "subject_id": 2,
                "subject_name": "数学",
                "latest_score": 40,
                "first_score": 70,
                "pass_score": 60,
                "volatility": 15,
                "failure_ratio": 0.67,
                "exam_count": 3,
            }
        )
        predictions.append(item)

    summary = risk_summary(predictions)

    assert len(summary.predictions) == 100
    assert summary.high_count == 110


def test_score_import_parses_chinese_csv_and_normalizes_full_width_values() -> None:
    content = "学号,考试名称,科目编码,成绩\n２０２６０１０１,期中考试,MATH,８８.５\n".encode()
    source_type, rows = parse_score_file("scores.csv", content)

    assert source_type == "csv"
    assert rows == [
        {
            "student_no": "20260101",
            "exam_name": "期中考试",
            "subject_code": "MATH",
            "score": "88.5",
        }
    ]


def test_score_import_parses_json_rows() -> None:
    content = json.dumps(
        [{"student_no": "1", "exam_name": "期中", "subject": "数学", "score": 90}]
    ).encode()
    source_type, rows = parse_score_file("scores.json", content)

    assert source_type == "json"
    assert rows[0]["subject_code"] == "数学"


def test_score_import_rejects_unsupported_file_type() -> None:
    with pytest.raises(ValueError, match="仅支持"):
        parse_score_file("scores.exe", b"unsafe")


@pytest.mark.parametrize("score", [0, 80, 80.5, 149.5, 150])
def test_valid_score_increments_are_integer_or_half_point(score: float) -> None:
    assert has_valid_score_increment(score)


@pytest.mark.parametrize("score", [80.1, 80.25, 80.6, 99.99])
def test_random_score_decimals_are_rejected(score: float) -> None:
    assert not has_valid_score_increment(score)


def test_generated_score_quantization_uses_half_points() -> None:
    assert quantize_score(80.24) == 80
    assert quantize_score(80.26) == 80.5


def test_demo_curriculum_matches_three_grade_rules() -> None:
    assert GRADE_SUBJECT_CODES["初一"] == (
        "CHN", "MATH", "ENG", "POL", "HIST", "GEO", "BIO"
    )
    assert GRADE_SUBJECT_CODES["初二"] == (
        "CHN", "MATH", "ENG", "POL", "PHY", "HIST", "GEO", "BIO"
    )
    assert GRADE_SUBJECT_CODES["初三"] == (
        "CHN", "MATH", "ENG", "POL", "HIST", "PHY", "CHEM"
    )


def test_score_import_validation_rejects_random_decimals() -> None:
    assert score_validation_error(80, 100) is None
    assert score_validation_error(80.5, 100) is None
    assert score_validation_error(80.3, 100) == "成绩只能为整数或 0.5 分"
    assert score_validation_error(100.5, 100) == "成绩必须在 0 到 100 之间"


def test_demo_scores_are_realistic_and_keep_small_risk_sample() -> None:
    class StudentStub:
        def __init__(self, student_id: int) -> None:
            self.id = student_id

    groups = [
        [
            StudentStub(class_index * DEMO_STUDENTS_PER_CLASS + seat + 1)
            for seat in range(DEMO_STUDENTS_PER_CLASS)
        ]
        for class_index in range(DEMO_CLASS_COUNT)
    ]
    max_scores = [max_score for _, _, max_score, _ in DEMO_SUBJECT_SCHEMES]
    values = build_demo_score_values(
        groups,
        exam_count=len(DEMO_EXAMS),
        subject_max_scores=max_scores,
    )
    scores = list(values.values())

    pass_rate = sum(
        score >= max_scores[subject_index] * 0.6
        for (_, _, subject_index), score in values.items()
    ) / len(scores)
    assert 0.92 <= pass_rate <= 0.98
    latest_rates = [
        score / max_scores[subject_index] * 100
        for (_, exam_index, subject_index), score in values.items()
        if exam_index == len(DEMO_EXAMS) - 1
    ]
    assert len(values) == 6 * 42 * 5 * 7
    assert sum(score_rate < 60 for score_rate in latest_rates) >= 5
    assert sum(score_rate < 50 for score_rate in latest_rates) >= 1
    assert all(
        0 <= score <= max_scores[subject_index]
        for (_, _, subject_index), score in values.items()
    )
    assert all(has_valid_score_increment(score) for score in values.values())
    assert values[(1, 0, 1)] == 105
    assert values[(1, 4, 1)] == 69


def test_risk_score_is_equivalent_across_subject_max_scores() -> None:
    common = {
        "student_id": 7,
        "student_name": "测试学生",
        "class_id": 1,
        "class_name": "高一（1）班",
        "subject_id": 2,
        "subject_name": "数学",
        "failure_ratio": 0.67,
        "exam_count": 3,
    }
    hundred = prediction_from_row(
        common
        | {
            "latest_score": 42,
            "first_score": 75,
            "pass_score": 60,
            "max_score": 100,
            "volatility": 15,
        }
    )
    hundred_fifty = prediction_from_row(
        common
        | {
            "latest_score": 63,
            "first_score": 112.5,
            "pass_score": 90,
            "max_score": 150,
            "volatility": 22.5,
        }
    )

    assert hundred_fifty.risk_score == hundred.risk_score
    assert hundred_fifty.risk_level == hundred.risk_level
