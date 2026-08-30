from app.agents.contracts import VisualizationDraft
from app.services.chart_security import secure_chart


def test_allows_safe_echarts_option() -> None:
    draft = VisualizationDraft(
        type="bar",
        title="各科均分",
        option={
            "xAxis": {"type": "category", "data": ["语文", "数学"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [80, 90]}],
        },
    )

    assert secure_chart(draft).type == "bar"


def test_rejects_formatter_and_external_url() -> None:
    formatter = VisualizationDraft(
        type="bar",
        option={"series": [{"type": "bar", "formatter": "alert(1)", "data": [1]}]},
    )
    external_image = VisualizationDraft(
        type="bar",
        option={"series": [{"type": "bar", "symbol": "https://example.com/a.png", "data": [1]}]},
    )

    assert secure_chart(formatter).type == "none"
    assert secure_chart(external_image).type == "none"


def test_rejects_custom_series_type() -> None:
    draft = VisualizationDraft(
        type="bar",
        option={"series": [{"type": "custom", "data": [1]}]},
    )

    assert secure_chart(draft).type == "none"


def test_rate_chart_removes_stacking_and_separates_legend_from_axis() -> None:
    draft = VisualizationDraft(
        type="line",
        title="各科得分率趋势",
        option={
            "grid": {"top": 20, "bottom": 20},
            "legend": {"bottom": 0},
            "xAxis": {"type": "category", "data": ["2027-01-20"]},
            "yAxis": {"type": "value", "max": 600},
            "series": [
                {
                    "name": "语文得分率",
                    "type": "line",
                    "stack": "total",
                    "data": [74.6666666667],
                }
            ],
        },
    )

    secured = secure_chart(draft)

    assert secured.option["series"][0].get("stack") is None
    assert secured.option["series"][0]["data"] == [74.67]
    assert secured.option["yAxis"]["max"] == 100
    assert secured.option["legend"]["top"] == 36
    assert "bottom" not in secured.option["legend"]
    assert secured.option["grid"]["top"] == 92
