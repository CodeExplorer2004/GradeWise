from app.agents.report_graph import _fallback_report, _fallback_warning
from app.api.reports import _resolve_report_type
from app.core.models import User, UserRole
from app.core.schemas import (
    AgentTaskRequest,
    AgentTaskResponse,
    InsightsResponse,
    LearningAlert,
    ReportRequest,
    ScoreBand,
)
from app.services.learning_insights import (
    _filter_predicate,
    _filtered_source,
    insights_for_llm,
)


def _insights() -> InsightsResponse:
    alert = LearningAlert(
        type="current_risk",
        severity="high",
        student_id=7,
        student_name="测试学生姓名",
        class_name="高一（1）班",
        subject_name="数学",
        exam_name="期中考试",
        title="最新成绩未达及格线",
        detail="当前 48.0 分，及格线 60.0 分",
        current_score=48,
        reference_score=60,
    )
    return InsightsResponse(
        average_score=72.5,
        overall_score_rate=72.5,
        pass_rate=83.3,
        score_distribution=[ScoreBand(label="60-69", count=2)],
        distribution_exam_name="期中考试",
        distribution_sample_size=2,
        anomalies=[],
        fluctuations=[],
        current_risks=[alert],
        alert_count=1,
        alert_counts={"anomaly": 0, "fluctuation": 0, "current_risk": 1},
    )


def test_insights_for_llm_masks_student_identity() -> None:
    masked = insights_for_llm(_insights())

    student_ref = masked["current_risks"][0]["student_ref"]
    assert student_ref.startswith("S-")
    assert student_ref != "S-00000007"
    assert "测试学生姓名" not in str(masked)
    assert "student_name" not in str(masked)


def test_report_fallback_uses_only_supplied_evidence() -> None:
    state = {"report_type": "student", "insights": insights_for_llm(_insights())}
    warning = _fallback_warning(state)
    state["warning_analysis"] = warning
    report = _fallback_report(state)

    assert warning.severity == "high"
    assert report.title == "学生成绩报告"
    assert "整体得分率 72.5%" in report.overview


def test_auto_report_type_follows_role_scope() -> None:
    student = User(role=UserRole.STUDENT)
    teacher = User(role=UserRole.SUBJECT_TEACHER)

    assert _resolve_report_type(ReportRequest(), student) == "student"
    assert _resolve_report_type(ReportRequest(), teacher) == "scope_brief"


def test_batch_report_scope_builds_safe_score_fact_filter() -> None:
    filters = {
        "class_name": "初三1班",
        "subject_name": "语文",
        "exam_name": "老师的'测试",
        "unexpected": "ignored",
    }

    predicate = _filter_predicate(filters)
    source = _filtered_source("FROM (SELECT score FROM score_facts) scoped", filters)

    assert "class_name = '初三1班'" in predicate
    assert "subject_name = '语文'" in predicate
    assert "exam_name = '老师的''测试'" in predicate
    assert "unexpected" not in predicate
    assert f"FROM score_facts WHERE {predicate})" in source


def test_agent_task_models_keep_default_scope_for_existing_tasks() -> None:
    request = AgentTaskRequest(task_type="batch_report")
    existing_task = AgentTaskResponse(
        task_id="thread-1",
        run_id="run-1",
        task_type="batch_report",
        status="success",
        stage="completed",
        status_message="任务已完成",
    )

    assert all(value is None for value in request.scope.model_dump().values())
    assert {"academic_year", "grade_level", "term", "exam_type", "cohort_year"}.issubset(
        request.scope.model_dump()
    )
    assert existing_task.scope.model_dump() == request.scope.model_dump()
    assert existing_task.created_at is None
