from app.core.schemas import ChatMessage


def test_chat_message_accepts_legacy_text_only_history() -> None:
    message = ChatMessage.model_validate({"role": "assistant", "content": "查询完成"})

    assert message.content == "查询完成"
    assert message.rows == []
    assert message.sql is None


def test_chat_message_restores_structured_result() -> None:
    message = ChatMessage.model_validate(
        {
            "role": "assistant",
            "content": "历次考试成绩如下",
            "sql": "SELECT exam_name, score FROM score_facts",
            "rows": [{"exam_name": "期末考试", "score": 96}],
            "chart": {"type": "line", "title": "成绩趋势", "option": {}},
            "allowed": True,
        }
    )

    assert message.allowed is True
    assert message.chart is not None
    assert message.chart.type == "line"
