from typing import Any, Literal

from pydantic import BaseModel, Field


class SchemaResolution(BaseModel):
    intent: str
    relevant_columns: list[str] = Field(default_factory=list)
    resolved_filters: dict[str, str] = Field(default_factory=dict)
    ambiguity: str | None = None


class SQLDraft(BaseModel):
    sql: str
    explanation: str = ""


class AuditExplanation(BaseModel):
    risk_level: Literal["low", "medium", "high"]
    violation_types: list[str] = Field(default_factory=list)
    explanation: str


class VisualizationDraft(BaseModel):
    type: Literal["bar", "line", "radar", "pie", "none"] = "none"
    title: str = ""
    option: dict[str, Any] = Field(default_factory=dict)


class WarningAnalysis(BaseModel):
    severity: Literal["low", "medium", "high"] = "low"
    summary: str
    key_risks: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class LearningReportDraft(BaseModel):
    title: str
    overview: str
    highlights: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    ai_comment: str
