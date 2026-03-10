from app.schemas import RunCreateRequest
from app.scoring import score_tradeoff


def test_freeform_question_extracts_links():
    payload = RunCreateRequest(
        question="这周六去杭州看展值不值？活动页 https://example.com/event ，我周一还得上班。",
    )

    assert payload.links == ["https://example.com/event"]


def test_spending_score_contains_average():
    payload = RunCreateRequest(
        question="我是不是又想冲动买一个很贵的键盘",
        budget="1000 以内",
        notes="最近已经买过两个",
    )

    result = score_tradeoff("spending", payload)

    assert result["category"] == "spending"
    assert "average" in result
    assert result["scores"]["budget_friction"] >= 4
