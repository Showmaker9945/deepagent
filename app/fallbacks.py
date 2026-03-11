from __future__ import annotations

from typing import Any

from app.schemas import Category, ClassificationResult, RunCreateRequest, RunVerdict


DIMENSION_LABELS: dict[Category, dict[str, str]] = {
    "spending": {
        "necessity": "必要性",
        "reusability": "使用频率",
        "budget_friction": "预算压力",
        "alternatives": "替代空间",
        "regret_risk": "后悔风险",
        "links_context": "资料完整度",
        "budget_ready": "预算明确度",
    },
    "travel": {
        "weather_fit": "天气匹配度",
        "time_cost": "时间成本",
        "money_cost": "金钱成本",
        "event_value": "现场价值",
        "fallback_window": "改期空间",
        "location_ready": "地点明确度",
    },
    "work_learning": {
        "leverage": "杠杆收益",
        "effort": "投入强度",
        "deadline_pressure": "截止压力",
        "reusability": "可复用性",
        "opportunity_cost": "机会成本",
    },
    "social": {
        "relationship_value": "关系价值",
        "boundaries": "边界感",
        "emotional_cost": "情绪成本",
        "timing": "时机",
        "signal_quality": "反馈信号",
    },
    "unsupported": {
        "risk": "风险级别",
    },
}


POSITIVE_TEMPLATES: dict[Category, dict[str, str]] = {
    "spending": {
        "necessity": "这件东西对你不是纯装饰，确实有实际用途。",
        "reusability": "如果真会高频使用，这笔钱就没那么像情绪税。",
        "alternatives": "现在还有替代空间，说明你不是被逼到单选题。",
        "links_context": "你已经给了链接，至少不是闭眼冲。",
        "budget_ready": "预算边界已经摆出来了，不容易一路滑到超支。",
    },
    "travel": {
        "weather_fit": "天气条件如果还行，这趟体验就不会先天掉分。",
        "event_value": "这次出行本身是有现场价值的，不只是为了动一动。",
        "fallback_window": "改期空间还在，说明决策弹性不错。",
        "location_ready": "地点已经明确，判断不会完全飘在空中。",
    },
    "work_learning": {
        "leverage": "这件事对作品集、能力沉淀或长期杠杆是有帮助的。",
        "reusability": "投入不只是一次性消耗，后面有复用价值。",
        "deadline_pressure": "时间边界相对清楚，至少不会无限拖成心债。",
    },
    "social": {
        "relationship_value": "这段关系本身有值得维护的价值。",
        "timing": "时机不算太别扭，现在聊未必是坏选择。",
        "signal_quality": "对方给到的信号不算太冷，至少不是硬凑局。",
    },
    "unsupported": {},
}


NEGATIVE_TEMPLATES: dict[Category, dict[str, str]] = {
    "spending": {
        "budget_friction": "预算痛感偏高，容易买完以后开始和钱包对视。",
        "regret_risk": "这事有点像情绪上头型消费，后悔概率不低。",
        "necessity": "必要性还不够硬，像是想要多过需要。",
    },
    "travel": {
        "time_cost": "时间成本可能比你现在脑补的更狠。",
        "money_cost": "花费不一定夸张，但性价比还没站稳。",
        "weather_fit": "天气这关如果不稳，体验会被直接打折。",
    },
    "work_learning": {
        "effort": "投入强度不低，容易和你现有主线任务打架。",
        "opportunity_cost": "做它的代价，是别的更重要事情会被挤掉。",
        "deadline_pressure": "如果时间很紧，这事容易把热情卷成压力。",
    },
    "social": {
        "boundaries": "边界感如果拿不准，见面后很容易自己先累。",
        "emotional_cost": "情绪成本不低，未必值得你硬撑一把。",
        "signal_quality": "对方反馈信号一般，别替沉默脑补情深。",
    },
    "unsupported": {},
}


ALTERNATIVE_BY_CATEGORY: dict[Category, str] = {
    "spending": "先找二手、替代款，或者给自己留一个 24 小时冷静窗口。",
    "travel": "先看能不能改期、缩短行程，或者换成成本更低的版本。",
    "work_learning": "先做一个最小可行版本，不要一上来就铺满战线。",
    "social": "先发一条轻量消息试水，再决定要不要升级到线下见面。",
    "unsupported": "先把事实整理清楚，再找对应专业人士确认。",
}


NEXT_STEP_BY_CATEGORY: dict[Category, str] = {
    "spending": "先写下你为什么需要它、多久会用一次，再决定今天下不下单。",
    "travel": "先把出发时间、来回成本和最坏天气情况列成三行，再决定去不去。",
    "work_learning": "先拿 30 分钟做最小验证，别先立宏大项目牌坊。",
    "social": "先发一句不费劲的消息试试水，再看对方反馈决定下一步。",
    "unsupported": "把你真正想确认的问题缩成一句话，带着去问专业人士。",
}


FOLLOW_UP_BY_MISSING_FIELD = {
    "location_or_time": "这件事最缺的是地点和时间边界，你到底打算什么时候、去哪里？",
    "more_context": "你到底为什么想做这件事，是刚需、好奇，还是单纯上头了？",
    "goal_or_timing": "你最想拿到的结果是什么，最晚什么时候必须决定？",
    "context": "你和对方目前是什么关系、这次互动的具体场景是什么？",
}


def _pick_high_scores(scores: dict[str, float]) -> list[str]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [name for name, value in ranked if value >= 7][:2]


def _pick_low_scores(scores: dict[str, float]) -> list[str]:
    ranked = sorted(scores.items(), key=lambda item: item[1])
    return [name for name, value in ranked if value <= 5][:3]


def _verdict_from_average(average: float) -> tuple[str, float]:
    if average >= 7.4:
        return "可以做，但别上头", 0.64
    if average >= 6.0:
        return "可以先小步试试", 0.56
    return "先别急着做", 0.48


def _fallback_punchline(category: Category, humor_allowed: bool, average: float) -> str | None:
    if not humor_allowed or category == "unsupported":
        return None
    if average >= 7.4:
        return "能冲，但先把鞋带系好。"
    if average >= 6.0:
        return "能试，但先别一脚油门到底。"
    return "先别燃，火苗还没到能开锅的程度。"


def build_fallback_verdict(
    category: Category,
    request: RunCreateRequest,
    classification: ClassificationResult,
    score_result: dict[str, Any],
) -> RunVerdict:
    scores = score_result.get("scores", {})
    average = float(score_result.get("average", 5.0))
    verdict, confidence = _verdict_from_average(average)
    confidence = max(0.35, min(0.72, confidence - 0.05 * len(classification.missing_fields)))

    positive_dimensions = _pick_high_scores(scores)
    negative_dimensions = _pick_low_scores(scores)
    positive_templates = POSITIVE_TEMPLATES.get(category, {})
    negative_templates = NEGATIVE_TEMPLATES.get(category, {})
    labels = DIMENSION_LABELS.get(category, {})

    why_yes = [positive_templates[name] for name in positive_dimensions if name in positive_templates]
    why_no = [negative_templates[name] for name in negative_dimensions if name in negative_templates]
    top_risks = [
        f"{labels.get(name, name)} 这一项还偏弱，容易把判断拖向后悔。"
        for name in negative_dimensions[:2]
    ]

    if not why_yes:
        why_yes = ["现有信息还不算全空白，至少能先做一个保守判断。"]
    if not why_no:
        why_no = ["信息还不够厚，别把一点点心动误读成确定答案。"]
    if not top_risks:
        top_risks = ["上下文还不够完整，容易把模糊感错当成可执行性。"]

    follow_up_question = None
    if classification.missing_fields:
        follow_up_question = FOLLOW_UP_BY_MISSING_FIELD.get(classification.missing_fields[0])
    elif negative_dimensions:
        follow_up_question = f"如果把“{labels.get(negative_dimensions[0], negative_dimensions[0])}”这件事说得更具体，你的决定会不会更清楚？"

    if request.links and category in {"spending", "travel"}:
        why_yes.append("你已经给了链接或具体资料，至少不是纯靠想象开会。")
        why_yes = why_yes[:3]

    if category == "social" and not request.links:
        why_no.append("社交类判断天然有主观成分，别期待像查天气一样精确。")
        why_no = why_no[:3]

    return RunVerdict(
        category=category,
        verdict=verdict,
        confidence=round(confidence, 2),
        why_yes=why_yes[:3],
        why_no=why_no[:3],
        top_risks=top_risks[:3],
        best_alternative=ALTERNATIVE_BY_CATEGORY[category],
        recommended_next_step=NEXT_STEP_BY_CATEGORY[category],
        follow_up_question=follow_up_question,
        punchline=_fallback_punchline(category, classification.humor_allowed, average),
    )
