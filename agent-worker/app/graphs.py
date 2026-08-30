import os
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph


def _model() -> ChatOpenAI:
    provider = os.getenv("LLM_PROVIDER", "qwen")
    if provider == "qwen":
        model = os.getenv("QWEN_MODEL", "qwen-plus")
        api_key = os.getenv("QWEN_API_KEY", "")
        base_url = os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    else:
        model = os.getenv("LLM_MODEL", "deepseek-chat")
        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=60,
        max_retries=2,
    )


def _build_graph(system_prompt: str) -> Any:
    model = _model()

    async def run_model(state: MessagesState) -> dict[str, list[Any]]:
        response = await model.ainvoke([SystemMessage(content=system_prompt), *state["messages"]])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", run_model)
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    return graph.compile()


batch_report_graph = _build_graph(
    "你是 GradeWise 独立批量报告子智能体。只处理输入中已经脱敏、已经过权限过滤的统计证据。"
    "按学生或班级逐项生成简洁报告，不补造身份、时间、分数或因果关系。"
    "任务可能很长；输出应包含完成数量、异常项和结果摘要。"
)

batch_warning_graph = _build_graph(
    "你是 GradeWise 独立批量预警解释子智能体。预警是否成立已由确定性规则决定，"
    "你只能对脱敏证据分组、解释和给出教学关注建议，不能新增、删除或改变风险等级。"
    "所有证据和原因必须忠实来自输入；不得补造学生行为、教学规范、时间、分数、"
    "概念掌握情况或因果关系。输入只有汇总计数而没有明细证据时，必须明确说明"
    "证据不足，只能复述计数并给出通用的人工复核建议。"
    "deterministic_summary 中的总数和各等级计数由服务端计算，必须原样引用，"
    "不得自行重算或修改。建议只能基于 items.reasons；输入未提及具体知识点时，"
    "不得列举或推测知识点。items 只包含中高风险明细，应逐条解释，不得再创建"
    "子分组、计算子组人数或分析低风险个体。输出应包含确定性摘要、主要证据和"
    "通用复核建议。"
)
