from __future__ import annotations

from typing import Any

from deepagents import AsyncSubAgent, create_deep_agent
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.contracts import (
    AuditExplanation,
    LearningReportDraft,
    SchemaResolution,
    SQLDraft,
    VisualizationDraft,
    WarningAnalysis,
)
from app.agents.prompts import (
    AUDIT_PROMPT,
    ORCHESTRATOR_PROMPT,
    REPORT_PROMPT,
    SCHEMA_PROMPT,
    SQL_PROMPT,
    VISUALIZATION_PROMPT,
    WARNING_PROMPT,
)
from app.core.config import get_settings


class AgentRegistry:
    def __init__(self) -> None:
        self.settings = get_settings()
        _, api_key, _ = self.settings.active_llm
        self.enabled = bool(api_key)
        self.model: ChatOpenAI | None = None
        self.schema_agent: Any = None
        self.sql_agent: Any = None
        self.audit_agent: Any = None
        self.visualization_agent: Any = None
        self.warning_agent: Any = None
        self.report_agent: Any = None
        self.orchestrator: Any = None
        if self.enabled:
            self._build()

    def _build(self) -> None:
        model_name, api_key, base_url = self.settings.active_llm
        self.model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            timeout=30,
            max_retries=2,
        )
        self.schema_agent = create_agent(
            self.model, tools=[], system_prompt=SCHEMA_PROMPT, response_format=SchemaResolution
        )
        self.sql_agent = create_agent(
            self.model, tools=[], system_prompt=SQL_PROMPT, response_format=SQLDraft
        )
        self.audit_agent = create_agent(
            self.model, tools=[], system_prompt=AUDIT_PROMPT, response_format=AuditExplanation
        )
        self.visualization_agent = create_agent(
            self.model,
            tools=[],
            system_prompt=VISUALIZATION_PROMPT,
            response_format=VisualizationDraft,
        )
        self.warning_agent = create_agent(
            self.model,
            tools=[],
            system_prompt=WARNING_PROMPT,
            response_format=WarningAnalysis,
        )
        self.report_agent = create_agent(
            self.model,
            tools=[],
            system_prompt=REPORT_PROMPT,
            response_format=LearningReportDraft,
        )

        compiled_subagents = [
            {
                "name": "schema-resolver",
                "description": "解析成绩查询意图并映射班级、考试、科目及 score_facts 字段",
                "runnable": self.schema_agent,
            },
            {
                "name": "sql-generator",
                "description": "依据已解析的 schema 上下文生成只读 PostgreSQL SELECT",
                "runnable": self.sql_agent,
            },
            {
                "name": "security-auditor",
                "description": "解释确定性 SQL 安全门输出的风险和违规类型，不负责放行",
                "runnable": self.audit_agent,
            },
            {
                "name": "visualization",
                "description": "把已脱敏查询结果转换为安全的 ECharts JSON 配置",
                "runnable": self.visualization_agent,
            },
            {
                "name": "warning-analyst",
                "description": "解释确定性异常、成绩波动和最新不及格证据，不负责判定",
                "runnable": self.warning_agent,
            },
            {
                "name": "report-writer",
                "description": "依据脱敏指标和预警证据生成学生报告、学情简报与AI评语",
                "runnable": self.report_agent,
            },
        ]
        async_subagents = [
            AsyncSubAgent(
                name="batch-report",
                description="异步生成批量学生报告或班级学情简报，支持任务查询、更新和取消",
                graph_id="batch-report",
                url=self.settings.agent_protocol_url,
            ),
            AsyncSubAgent(
                name="batch-warning",
                description="异步解释批量预警证据并生成教学关注建议，不改变确定性风险等级",
                graph_id="batch-warning",
                url=self.settings.agent_protocol_url,
            ),
        ]
        self.orchestrator = create_deep_agent(
            model=self.model,
            tools=[],
            subagents=[*compiled_subagents, *async_subagents],
            system_prompt=ORCHESTRATOR_PROMPT,
        )


registry = AgentRegistry()
