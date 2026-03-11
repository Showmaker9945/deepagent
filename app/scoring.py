from __future__ import annotations

from typing import Any

from app.schemas import Category, RunCreateRequest


KEYWORD_GROUPS: dict[Category, dict[str, tuple[str, ...]]] = {
    "spending": {
        "necessity": ("need", "\u5fc5\u987b", "\u521a\u9700", "daily", "\u6bcf\u5929", "upgrade", "\u66ff\u6362"),
        "reusability": ("\u6bcf\u5929", "\u957f\u671f", "everyday", "weekly", "workhorse"),
        "budget_friction": ("\u8d35", "\u8d35\u4e0d\u8d35", "expensive", "\u9884\u7b97", "\u5206\u671f", "\u8d85\u652f"),
        "alternatives": ("\u66ff\u4ee3", "\u4e8c\u624b", "rent", "\u501f", "\u5171\u4eab"),
        "regret_risk": ("\u51b2\u52a8", "\u540e\u6094", "\u4e0a\u5934", "\u79cd\u8349", "\u503c\u4e0d\u503c"),
    },
    "travel": {
        "weather_fit": ("\u5929\u6c14", "\u4e0b\u96e8", "\u6674\u5929", "temperature", "forecast"),
        "time_cost": ("\u901a\u52e4", "\u6765\u56de", "\u8d76", "\u8fdf\u5230", "hours"),
        "money_cost": ("\u8f66\u8d39", "\u95e8\u7968", "\u9152\u5e97", "\u673a\u7968", "\u9884\u7b97"),
        "event_value": ("\u6f14\u51fa", "\u5c55", "\u805a\u4f1a", "\u89c1\u9762", "\u673a\u4f1a\u96be\u5f97"),
        "fallback_window": ("\u6539\u5929", "\u5ef6\u671f", "\u4e0b\u5468", "\u4e0b\u6b21"),
    },
    "work_learning": {
        "leverage": ("\u957f\u671f", "portfolio", "\u7b80\u5386", "\u6760\u6746", "\u590d\u7528"),
        "effort": ("\u9700\u8981\u51e0\u5929", "\u597d\u591a\u5c0f\u65f6", "hard", "\u590d\u6742"),
        "deadline_pressure": ("ddl", "deadline", "\u622a\u6b62", "\u672c\u5468", "\u660e\u5929"),
        "reusability": ("\u901a\u7528", "\u53ef\u590d\u7528", "\u6a21\u677f", "\u6c89\u6dc0"),
        "opportunity_cost": ("\u522b\u7684\u4efb\u52a1", "\u5206\u5fc3", "\u803d\u8bef", "\u4f18\u5148\u7ea7"),
    },
    "social": {
        "relationship_value": ("\u670b\u53cb", "\u540c\u4e8b", "\u5bb6\u4eba", "\u5bf9\u8c61", "\u91cd\u8981"),
        "boundaries": ("\u8fb9\u754c", "\u4e0d\u8212\u670d", "\u52c9\u5f3a", "\u6b20\u4eba\u60c5"),
        "emotional_cost": ("\u793e\u6050", "\u7d2f", "\u5185\u8017", "\u7126\u8651"),
        "timing": ("\u73b0\u5728", "\u4eca\u665a", "\u8fd9\u5468", "\u65f6\u673a"),
        "signal_quality": ("\u5bf9\u65b9", "\u56de\u590d", "\u9080\u8bf7", "\u6001\u5ea6"),
    },
    "unsupported": {
        "risk": ("medical", "\u6cd5\u5f8b", "\u6295\u8d44", "self-harm", "suicide", "\u8bca\u65ad"),
    },
}


def _keyword_score(haystack: str, needles: tuple[str, ...], baseline: int = 4) -> int:
    score = baseline
    lowered = haystack.lower()
    for needle in needles:
        if needle.lower() in lowered:
            score += 2
    return max(1, min(score, 10))


def score_tradeoff(category: Category, request: RunCreateRequest) -> dict[str, Any]:
    text = " ".join(
        part for part in [request.question, request.notes or "", request.budget or "", request.deadline or ""] if part
    )
    groups = KEYWORD_GROUPS[category]
    scores = {dimension: _keyword_score(text, needles) for dimension, needles in groups.items()}
    if request.links:
        scores["links_context"] = 7
    if request.location and category == "travel":
        scores["location_ready"] = 8
    if request.budget and category == "spending":
        scores["budget_ready"] = 8

    average = round(sum(scores.values()) / max(len(scores), 1), 1)
    summary = f"基于当前信息，这个 {category.replace('_', ' ')} 问题的本地权衡分大约是 {average}/10。"
    return {"category": category, "scores": scores, "average": average, "summary": summary}
