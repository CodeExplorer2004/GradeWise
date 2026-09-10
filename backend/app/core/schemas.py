from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    id: int
    username: str
    role: str
    school_id: int
    display_name: str

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserInfo


class AnalysisScope(BaseModel):
    academic_year: str | None = None
    grade_level: str | None = None
    term: str | None = None
    exam_type: str | None = None
    cohort_year: int | None = None
    class_name: str | None = None
    subject_name: str | None = None
    exam_name: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    scope: AnalysisScope = Field(default_factory=AnalysisScope)


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "radar", "pie", "none"] = "none"
    title: str = ""
    option: dict[str, Any] = Field(default_factory=dict)


class AchievementSubject(BaseModel):
    subject_name: str
    score: float
    max_score: float
    pass_score: float
    passed: bool


class AchievementExam(BaseModel):
    exam_name: str
    exam_date: str
    subjects: list[AchievementSubject] = Field(default_factory=list)
    total_score: float
    total_max_score: float
    passed_subjects: int
    subject_count: int
    class_rank: int | None = None
    class_size: int | None = None
    grade_rank: int | None = None
    grade_size: int | None = None


class StudentAchievementOverview(BaseModel):
    student_name: str
    class_name: str
    grade_level: str
    scope_label: str
    exams: list[AchievementExam] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    sql: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart: ChartSpec | None = None
    student_overview: StudentAchievementOverview | None = None
    audit: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    sql: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart: ChartSpec | None = None
    student_overview: StudentAchievementOverview | None = None
    allowed: bool | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationHistory(BaseModel):
    conversation_id: str
    messages: list[ChatMessage] = Field(default_factory=list)


class AnalysisFilterOptions(BaseModel):
    academic_years: list[str] = Field(default_factory=list)
    grade_levels: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    exam_types: list[str] = Field(default_factory=list)
    cohort_years: list[int] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    exams: list[str] = Field(default_factory=list)
    defaults: AnalysisScope = Field(default_factory=AnalysisScope)


class GradeComparison(BaseModel):
    grade_level: str
    score_rate: float
    pass_rate: float
    student_count: int


class YearComparison(BaseModel):
    academic_year: str
    score_rate: float
    pass_rate: float
    student_count: int


class DashboardResponse(BaseModel):
    # Retained for API compatibility; mixed-subject UI uses overall_score_rate.
    average_score: float
    overall_score_rate: float
    pass_rate: float
    student_count: int
    exam_count: int
    scope_description: str
    applied_scope: AnalysisScope = Field(default_factory=AnalysisScope)
    mixed_grade_scope: bool = False
    mixed_academic_year_scope: bool = False
    comparison_note: str = ""
    grade_comparison: list[GradeComparison] = Field(default_factory=list)
    year_comparison: list[YearComparison] = Field(default_factory=list)
    subject_averages: list[dict[str, Any]]
    exam_trend: list[dict[str, Any]]


class ScoreBand(BaseModel):
    label: str
    count: int


class LearningAlert(BaseModel):
    type: Literal["anomaly", "fluctuation", "current_risk"]
    severity: Literal["medium", "high"]
    student_id: int
    student_name: str
    class_name: str
    subject_name: str
    exam_name: str
    title: str
    detail: str
    current_score: float
    reference_score: float | None = None


class InsightsResponse(BaseModel):
    # Retained for API compatibility; reports use overall_score_rate.
    average_score: float
    overall_score_rate: float = 0
    pass_rate: float
    score_distribution: list[ScoreBand]
    distribution_exam_name: str
    distribution_sample_size: int
    anomalies: list[LearningAlert]
    fluctuations: list[LearningAlert]
    current_risks: list[LearningAlert]
    alert_count: int
    alert_counts: dict[str, int]


class AlertPageResponse(BaseModel):
    alert_type: Literal["anomaly", "fluctuation", "current_risk"]
    items: list[LearningAlert]
    total: int
    page: int
    page_size: int


class ReportRequest(BaseModel):
    report_type: Literal["auto", "student", "scope_brief"] = "auto"
    scope: AnalysisScope = Field(default_factory=AnalysisScope)


class ReportResponse(BaseModel):
    report_type: Literal["student", "scope_brief"]
    title: str
    overview: str
    highlights: list[str]
    concerns: list[str]
    recommendations: list[str]
    ai_comment: str
    warning_summary: str
    generated_by: Literal["qwen", "deepseek", "fallback"]


class RiskPrediction(BaseModel):
    student_id: int
    class_id: int
    subject_id: int
    student_name: str
    class_name: str
    subject_name: str
    risk_score: float
    risk_level: Literal["low", "medium", "high"]
    latest_score: float
    trend: float
    volatility: float
    failure_ratio: float
    exam_count: int
    reasons: list[str]


class RiskSummaryResponse(BaseModel):
    model_version: str = "transparent-rule-v2"
    disclaimer: str
    predictions: list[RiskPrediction]
    high_count: int
    medium_count: int


class ImportErrorItem(BaseModel):
    row: int
    reason: str


class ImportResult(BaseModel):
    batch_id: str
    filename: str
    source_type: Literal["csv", "xlsx", "json"]
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    inserted_rows: int
    updated_rows: int
    errors: list[ImportErrorItem]


class ChartExportRequest(BaseModel):
    chart_type: Literal["bar", "line", "radar", "pie"]
    title: str = Field(min_length=1, max_length=120)
    option: dict[str, Any]


class AgentTaskScope(AnalysisScope):
    pass


class AgentTaskRequest(BaseModel):
    task_type: Literal["batch_report", "batch_warning"]
    scope: AgentTaskScope = Field(default_factory=AgentTaskScope)


class AgentTaskOptions(BaseModel):
    classes: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    exams: list[str] = Field(default_factory=list)


class AgentTaskUpdate(BaseModel):
    message: str = Field(min_length=1, max_length=3000)


AgentTaskStatus = Literal[
    "queued", "running", "success", "error", "cancelled", "interrupted"
]
AgentTaskStage = Literal[
    "collecting_evidence",
    "submitting",
    "agent_running",
    "saving_result",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]


class AgentTaskResponse(BaseModel):
    task_id: str
    run_id: str | None = None
    task_type: Literal["batch_report", "batch_warning"]
    status: AgentTaskStatus
    stage: AgentTaskStage
    status_message: str
    result: str | None = None
    scope: AgentTaskScope = Field(default_factory=AgentTaskScope)
    requested_scope: AgentTaskScope = Field(default_factory=AgentTaskScope)
    error_code: str | None = None
    attempt_count: int = 0
    can_retry: bool = False
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
