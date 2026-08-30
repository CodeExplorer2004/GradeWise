from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.contracts import LearningReportDraft, WarningAnalysis
from app.agents.factory import registry


class ReportState(TypedDict, total=False):
    report_type: Literal["student", "scope_brief"]
    insights: dict[str, Any]
    warning_analysis: WarningAnalysis
    report: LearningReportDraft


async def _structured(agent: Any, prompt: str, model_type: type[Any]) -> Any:
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    structured = result.get("structured_response")
    if isinstance(structured, model_type):
        return structured
    return model_type.model_validate(structured)


def _fallback_warning(state: ReportState) -> WarningAnalysis:
    insights = state["insights"]
    count = int(insights.get("alert_count", 0))
    return WarningAnalysis(
        severity="high" if insights.get("current_risks") else ("medium" if count else "low"),
        summary=f"当前范围共识别 {count} 条需关注记录。",
        key_risks=[item["detail"] for item in insights.get("current_risks", [])[:3]],
        evidence=[item["detail"] for item in insights.get("fluctuations", [])[:3]],
    )


async def warning_node(state: ReportState) -> dict[str, Any]:
    if not registry.enabled:
        return {"warning_analysis": _fallback_warning(state)}
    prompt = json.dumps(state["insights"], ensure_ascii=False, default=str)
    analysis = await _structured(registry.warning_agent, prompt, WarningAnalysis)
    return {"warning_analysis": analysis}


def _fallback_report(state: ReportState) -> LearningReportDraft:
    insights = state["insights"]
    personal = state["report_type"] == "student"
    return LearningReportDraft(
        title="学生成绩报告" if personal else "学情简报",
        overview=(
            f"当前整体得分率 {insights.get('overall_score_rate', 0)}%，"
            f"及格率 {insights.get('pass_rate', 0)}%。"
        ),
        highlights=["已完成各科成绩、得分率趋势和分布统计。"],
        concerns=state["warning_analysis"].key_risks,
        recommendations=["结合具体科目错题进行针对性复盘。", "持续观察下一次考试变化。"],
        ai_comment="保持稳定节奏，用连续的小进步积累长期提升。",
    )


async def report_node(state: ReportState) -> dict[str, Any]:
    if not registry.enabled:
        return {"report": _fallback_report(state)}
    prompt = json.dumps(
        {
            "report_type": state["report_type"],
            "insights": state["insights"],
            "warning_analysis": state["warning_analysis"].model_dump(),
        },
        ensure_ascii=False,
        default=str,
    )
    report = await _structured(registry.report_agent, prompt, LearningReportDraft)
    return {"report": report}


def build_report_graph() -> Any:
    graph = StateGraph(ReportState)
    graph.add_node("warning", warning_node)
    graph.add_node("report", report_node)
    graph.add_edge(START, "warning")
    graph.add_edge("warning", "report")
    graph.add_edge("report", END)
    return graph.compile()


report_graph = build_report_graph()
