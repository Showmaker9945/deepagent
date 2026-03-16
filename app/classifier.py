from __future__ import annotations

from app.schemas import Category, ClassificationResult, RunCreateRequest
from app.text_utils import has_budget_signal, has_location_signal, has_time_signal, merge_text

UNSUPPORTED_TERMS = {
    "medical",
    "\u8bca\u65ad",
    "\u6cbb\u7597",
    "\u6cd5\u5f8b",
    "\u5f8b\u5e08",
    "\u8d77\u8bc9",
    "\u6295\u8d44",
    "\u80a1\u7968",
    "\u671f\u6743",
    "\u81ea\u6740",
    "\u4f24\u5bb3\u81ea\u5df1",
    "harm myself",
}

CATEGORY_TERMS: dict[Category, set[str]] = {
    "spending": {
        "\u4e70",
        "\u8d2d\u4e70",
        "\u82b1\u94b1",
        "\u503c\u4e0d\u503c",
        "upgrade",
        "\u8ba2\u9605",
        "\u4ef7\u683c",
        "\u8d35",
        "\u4fbf\u5b9c",
    },
    "travel": {
        "\u53bb\u4e0d\u53bb",
        "\u51fa\u95e8",
        "\u65c5\u6e38",
        "\u6d3b\u52a8",
        "\u8def\u7a0b",
        "\u901a\u52e4",
        "\u5929\u6c14",
        "\u673a\u7968",
        "\u706b\u8f66",
        "\u6f14\u51fa",
        "\u770b\u5c55",
        "\u97f3\u4e50\u8282",
        "\u65c5\u884c",
    },
    "work_learning": {
        "\u5b66\u4e0d\u5b66",
        "\u505a\u4e0d\u505a",
        "\u9879\u76ee",
        "\u8bfe\u7a0b",
        "\u9762\u8bd5",
        "\u5de5\u4f5c",
        "\u5b66\u4e60",
        "\u51c6\u5907",
    },
    "social": {
        "\u8981\u4e0d\u8981\u7ea6",
        "\u805a\u4f1a",
        "\u670b\u53cb",
        "\u540c\u4e8b",
        "\u804a\u5929",
        "\u544a\u767d",
        "\u89c1\u9762",
        "\u5173\u7cfb",
    },
    "unsupported": set(),
}


def classify_request(payload: RunCreateRequest) -> ClassificationResult:
    haystack = merge_text(payload.question, payload.notes, payload.location, payload.deadline, " ".join(payload.links))
    lowered = haystack.lower()

    if any(term.lower() in lowered for term in UNSUPPORTED_TERMS):
        return ClassificationResult(
            category="unsupported",
            reason="这个问题风险比较高，应该优先寻求专业人士的帮助。",
            humor_allowed=False,
        )

    scores: dict[Category, int] = {category: 0 for category in CATEGORY_TERMS}
    for category, terms in CATEGORY_TERMS.items():
        for term in terms:
            if term.lower() in lowered:
                scores[category] += 1

    if payload.location and ("\u53bb" in payload.question or "\u5230" in payload.question):
        scores["travel"] += 2
    if any(
        term in payload.question
        for term in (
            "\u670b\u53cb",
            "\u540c\u4e8b",
            "\u5bf9\u8c61",
            "\u524d\u4efb",
            "\u7238\u5988",
            "\u5bb6\u4eba",
        )
    ):
        scores["social"] += 2

    category = max(("spending", "travel", "work_learning", "social"), key=lambda item: scores[item])
    if scores[category] == 0:
        category = "work_learning"

    clarification_question = None
    missing_fields: list[str] = []
    has_time = bool(payload.deadline) or has_time_signal(payload.question, payload.notes)
    has_location = bool(payload.location) or has_location_signal(payload.question, payload.notes)
    has_budget = bool(payload.budget) or has_budget_signal(payload.question, payload.notes)
    question_length = len(payload.question.strip())

    if category == "travel":
        if not has_location and not has_time and question_length < 24:
            missing_fields.append("location_or_time")
            clarification_question = (
                "\u8fd9\u8d9f\u884c\u7a0b\u662f\u53bb\u54ea\u91cc\u3001\u6253\u7b97\u4ec0\u4e48\u65f6\u5019\u53bb\uff1f"
            )
    elif category == "spending":
        if question_length < 10 and not has_budget and not payload.links:
            missing_fields.append("more_context")
            clarification_question = (
                "\u4f60\u80fd\u518d\u8865\u4e00\u53e5\u4f60\u4e3a\u4ec0\u4e48\u60f3\u4e70\u3001\u6216\u8005\u76f4\u63a5\u8d34"
                "\u4e00\u4e2a\u76f8\u5173\u94fe\u63a5\u5417\uff1f"
            )
    elif category == "work_learning":
        if question_length < 12 and not has_time:
            missing_fields.append("goal_or_timing")
            clarification_question = (
                "\u8fd9\u4ef6\u4e8b\u4f60\u6700\u60f3\u8981\u7684\u7ed3\u679c\u662f\u4ec0\u4e48\uff0c\u6216\u8005\u6700\u665a"
                "\u4ec0\u4e48\u65f6\u5019\u5f97\u505a\u51b3\u5b9a\uff1f"
            )
    elif category == "social":
        if question_length < 12 and not payload.notes:
            missing_fields.append("context")
            clarification_question = (
                "\u8865\u4e00\u53e5\u80cc\u666f\u5427\uff0c\u6bd4\u5982\u4f60\u548c\u5bf9\u65b9\u7684\u5173\u7cfb\u3001"
                "\u573a\u666f\uff0c\u514d\u5f97\u6211\u50cf\u62ff\u7740\u6a21\u7cca\u76d1\u63a7\u7834\u6848\u3002"
            )

    return ClassificationResult(
        category=category,
        reason=f"根据问题里的关键词和上下文，先把它归到 {category} 这一类。",
        needs_clarification=clarification_question is not None,
        clarification_question=clarification_question,
        missing_fields=missing_fields,
        humor_allowed=category != "unsupported",
    )
