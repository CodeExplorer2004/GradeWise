from app.agents.contracts import SchemaResolution
from app.agents.query_graph import _failure_subject_chart, _subject_score_rate_trend_chart
from app.core.models import User, UserRole
from app.services.chart_security import secure_chart


def test_subject_rate_trend_chart_is_independent_and_bounded() -> None:
    rows = [
        {
            "exam_date": "2027-01-20",
            "exam_name": "期末考试",
            "subject_name": "语文",
            "score_rate": 74.666666,
        },
        {
            "exam_date": "2027-01-20",
            "exam_name": "期末考试",
            "subject_name": "物理",
            "score_rate": 82.5,
        },
        {
            "exam_date": "2027-03-20",
            "exam_name": "一模",
            "subject_name": "语文",
            "score_rate": 78.0,
        },
        {
            "exam_date": "2027-03-20",
            "exam_name": "一模",
            "subject_name": "物理",
            "score_rate": 80.5,
        },
    ]

    draft = _subject_score_rate_trend_chart(rows)
    assert draft is not None
    chart = secure_chart(draft)

    assert chart.type == "line"
    assert chart.option["yAxis"]["min"] == 0
    assert chart.option["yAxis"]["max"] == 100
    assert chart.option["xAxis"]["data"] == ["2027-01-20", "2027-03-20"]
    assert chart.option["series"][0]["data"] == [74.67, 78.0]
    assert chart.option["series"][1]["data"] == [82.5, 80.5]
    assert all("stack" not in series for series in chart.option["series"])


def test_subject_rate_trend_chart_derives_rates_from_raw_scores() -> None:
    rows = [
        {
            "exam_date": "2027-01-20",
            "subject_name": "语文",
            "score": 112.0,
            "max_score": 150.0,
        },
        {
            "exam_date": "2027-01-20",
            "subject_name": "物理",
            "score": 82.5,
            "max_score": 100.0,
        },
        {
            "exam_date": "2027-03-20",
            "subject_name": "语文",
            "score": 117.0,
            "max_score": 150.0,
        },
        {
            "exam_date": "2027-03-20",
            "subject_name": "物理",
            "score": 80.5,
            "max_score": 100.0,
        },
    ]

    draft = _subject_score_rate_trend_chart(rows)

    assert draft is not None
    assert draft.option["series"][0]["data"] == [74.67, 78.0]
    assert draft.option["series"][1]["data"] == [82.5, 80.5]
    assert draft.option["yAxis"]["max"] == 100


def test_failure_chart_aggregates_by_subject_and_hides_legend() -> None:
    state = {
        "question": "查看初三下学期二模不及格记录",
        "catalog": {
            "classes": ["初三1班"],
            "exams": ["初三下学期二模"],
            "subjects": ["语文", "数学", "英语", "物理", "化学", "政治", "历史"],
        },
        "schema_resolution": SchemaResolution(intent="不及格记录"),
        "user": User(role=UserRole.HEAD_TEACHER),
    }
    counts = [
        {"subject_name": "语文", "failed_count": 0, "student_count": 0},
        {"subject_name": "数学", "failed_count": 4, "student_count": 4},
        {"subject_name": "英语", "failed_count": 0, "student_count": 0},
        {"subject_name": "物理", "failed_count": 2, "student_count": 2},
        {"subject_name": "化学", "failed_count": 0, "student_count": 0},
        {"subject_name": "政治", "failed_count": 0, "student_count": 0},
        {"subject_name": "历史", "failed_count": 0, "student_count": 0},
    ]

    draft = _failure_subject_chart(counts, state)

    assert draft.type == "bar"
    assert draft.title == "初三下学期二模各科不及格人次"
    assert draft.option["xAxis"]["data"] == state["catalog"]["subjects"]
    assert draft.option["series"][0]["data"] == [0, 4, 0, 2, 0, 0, 0]
    assert draft.option["legend"]["show"] is False
    assert draft.option["tooltip"]["position"] == "top"
    assert draft.option["yAxis"]["name"] == "不及格人次"


def test_failure_chart_only_shows_subjects_visible_to_subject_teacher() -> None:
    state = {
        "question": "查看不及格记录",
        "catalog": {
            "classes": ["初三1班", "初三2班"],
            "exams": ["初三下学期二模"],
            "subjects": ["语文", "数学", "英语", "物理", "化学", "政治", "历史"],
        },
        "schema_resolution": SchemaResolution(intent="不及格记录"),
        "user": User(role=UserRole.SUBJECT_TEACHER),
    }

    draft = _failure_subject_chart(
        [{"subject_name": "语文", "failed_count": 2, "student_count": 2}], state
    )

    assert draft.option["xAxis"]["data"] == ["语文"]
    assert draft.option["series"][0]["data"] == [2]
