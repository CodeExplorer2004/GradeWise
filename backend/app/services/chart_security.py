import json
from copy import deepcopy
from typing import Any

from app.agents.contracts import VisualizationDraft

ALLOWED_TOP_LEVEL_KEYS = {
    "dataset",
    "grid",
    "legend",
    "radar",
    "series",
    "title",
    "tooltip",
    "xAxis",
    "yAxis",
}
ALLOWED_SERIES_TYPES = {"bar", "line", "pie", "radar"}
FORBIDDEN_KEYS = {"formatter", "graphic", "renderItem", "toolbox"}
FORBIDDEN_STRING_PREFIXES = ("data:", "file:", "http:", "https:", "javascript:")


def _is_rate_chart(draft: VisualizationDraft, option: dict[str, Any]) -> bool:
    searchable = json.dumps(
        {"title": draft.title, "option": option},
        ensure_ascii=False,
        default=str,
    ).lower()
    return "得分率" in searchable or "score_rate" in searchable


def _round_chart_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, list):
        return [_round_chart_value(item) for item in value]
    if isinstance(value, dict) and "value" in value:
        return {**value, "value": _round_chart_value(value["value"])}
    return value


def _normalize_rate_chart(option: dict[str, Any]) -> None:
    series = option.get("series", [])
    if isinstance(series, list):
        for item in series:
            if not isinstance(item, dict):
                continue
            item.pop("stack", None)
            if "data" in item:
                item["data"] = _round_chart_value(item["data"])

    y_axes = option.get("yAxis")
    axes = y_axes if isinstance(y_axes, list) else [y_axes]
    for axis in axes:
        if isinstance(axis, dict):
            axis.update({"type": "value", "name": "得分率（%）", "min": 0, "max": 100})

    legend = option.setdefault("legend", {})
    if isinstance(legend, dict):
        legend.pop("bottom", None)
        legend.update(
            {
                "type": "scroll",
                "top": 36,
                "left": 52,
                "right": 20,
                "itemWidth": 18,
                "itemHeight": 8,
                "itemGap": 16,
            }
        )

    grid = option.setdefault("grid", {})
    if isinstance(grid, dict):
        grid.update(
            {
                "left": 56,
                "right": 24,
                "top": 92,
                "bottom": 56,
                "containLabel": True,
            }
        )


def _is_safe_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return not normalized.startswith(FORBIDDEN_STRING_PREFIXES) and "<" not in value
    if isinstance(value, list):
        return len(value) <= 1_000 and all(_is_safe_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str)
            and key not in FORBIDDEN_KEYS
            and _is_safe_value(item)
            for key, item in value.items()
        )
    return False


def secure_chart(draft: VisualizationDraft) -> VisualizationDraft:
    if draft.type == "none":
        return VisualizationDraft(type="none", title=draft.title, option={})
    if set(draft.option) - ALLOWED_TOP_LEVEL_KEYS:
        return VisualizationDraft(type="none", title="图表配置未通过安全校验", option={})
    if not _is_safe_value(draft.option):
        return VisualizationDraft(type="none", title="图表配置未通过安全校验", option={})
    option = deepcopy(draft.option)
    if _is_rate_chart(draft, option):
        _normalize_rate_chart(option)
    series = option.get("series", [])
    if not isinstance(series, list) or len(series) > 20:
        return VisualizationDraft(type="none", title="图表配置未通过安全校验", option={})
    if any(
        not isinstance(item, dict) or item.get("type") not in ALLOWED_SERIES_TYPES
        for item in series
    ):
        return VisualizationDraft(type="none", title="图表配置未通过安全校验", option={})
    if len(json.dumps(option, ensure_ascii=False, default=str)) > 100_000:
        return VisualizationDraft(type="none", title="图表配置过大", option={})
    return draft.model_copy(update={"option": option})
