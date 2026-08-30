from datetime import date

from app.services.achievement_overview import _filter_details_to_result_exams


def test_overview_follows_the_exam_range_returned_by_the_query() -> None:
    details = [
        {"exam_name": "期中考试", "exam_date": date(2026, 11, 1)},
        {"exam_name": "期末考试", "exam_date": date(2027, 1, 10)},
        {"exam_name": "一模", "exam_date": date(2027, 3, 10)},
    ]
    rows = [
        {"exam_name": "期末考试", "exam_date": date(2027, 1, 10)},
        {"exam_name": "一模", "exam_date": date(2027, 3, 10)},
    ]

    filtered = _filter_details_to_result_exams(details, rows)

    assert [row["exam_name"] for row in filtered] == ["期末考试", "一模"]


def test_overview_can_follow_exam_names_when_query_omits_dates() -> None:
    details = [
        {"exam_name": "期中考试", "exam_date": date(2026, 11, 1)},
        {"exam_name": "期末考试", "exam_date": date(2027, 1, 10)},
    ]

    filtered = _filter_details_to_result_exams(details, [{"exam_name": "期末考试"}])

    assert [row["exam_name"] for row in filtered] == ["期末考试"]
