from app.classifier import classify_request
from app.schemas import RunCreateRequest


def test_activity_link_prefers_travel_over_spending():
    result = classify_request(RunCreateRequest(question="这个活动要不要去？活动页 https://example.com/event"))

    assert result.category == "travel"


def test_course_link_prefers_work_learning_over_spending():
    result = classify_request(RunCreateRequest(question="这个课程要不要学？课程页 https://example.com/course"))

    assert result.category == "work_learning"


def test_product_link_can_still_be_classified_as_spending():
    result = classify_request(RunCreateRequest(question="这款显示器值不值？商品页 https://example.com/item"))

    assert result.category == "spending"
