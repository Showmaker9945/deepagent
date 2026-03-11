from fastapi.testclient import TestClient

from app.agents import RuntimeStreamEvent
from app.main import app
from app.schemas import RunVerdict


class FakeRuntime:
    def run_streaming(self, run_id, payload, classification, *, timeout_seconds, should_cancel):
        yield RuntimeStreamEvent(
            "agent_started",
            {"category": classification.category, "message": "主 Deep Agent 已接管。"},
        )
        yield RuntimeStreamEvent("agent_token", {"text": "我先看一下你给的信息。"})
        yield RuntimeStreamEvent(
            "tool_started",
            {"tool_name": "fetch_url_content", "summary": "开始抓取你给的链接。"},
        )
        if payload.links:
            yield RuntimeStreamEvent(
                "source_captured",
                {
                    "source_type": "webpage",
                    "title": "示例商品页",
                    "url": payload.links[0],
                    "snippet": "这是一个来自测试桩的网页摘要。",
                    "source_meta": {"query": "stub"},
                },
            )
        yield RuntimeStreamEvent(
            "tool_finished",
            {"tool_name": "fetch_url_content", "status": "ok", "summary": "链接抓取完成。"},
        )
        yield RuntimeStreamEvent(
            "verdict_ready",
            RunVerdict(
                category=classification.category,
                verdict="可以做，但别上头",
                confidence=0.74,
                why_yes=["收益是真的有。"],
                why_no=["时间成本比你想象中高。"],
                top_risks=["范围一不留神就膨胀。"],
                best_alternative="先做一个更小的试跑版。",
                recommended_next_step="先拿 30 分钟做最小验证，不要一上来就铺大摊子。",
                follow_up_question="什么结果会让你觉得这事明显值了？",
                punchline="能冲，但先别把自己冲成工位摆件。",
            ).model_dump(mode="json"),
        )


class TimeoutRuntime:
    def run_streaming(self, run_id, payload, classification, *, timeout_seconds, should_cancel):
        yield RuntimeStreamEvent(
            "agent_started",
            {"category": classification.category, "message": "主 Deep Agent 已接管。"},
        )
        yield RuntimeStreamEvent("timeout", {"message": "本轮分析超过 1 秒，已自动收手。"})


class ExplodingRuntime:
    def run_streaming(self, run_id, payload, classification, *, timeout_seconds, should_cancel):
        raise RuntimeError("stub exploded")


def test_run_flow_feedback_and_sources():
    with TestClient(app) as client:
        app.state.manager.runtime = FakeRuntime()

        create_response = client.post(
            "/api/runs",
            json={
                "question": "这个周末我要不要开始做一个小项目？我想做点能放作品集的东西，参考链接 https://example.com/item",
            },
        )
        assert create_response.status_code == 200

        run_id = create_response.json()["run_id"]
        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        body = run_response.json()
        assert body["run"]["status"] == "completed"
        assert body["run"]["verdict"]["verdict"] == "可以做，但别上头"
        assert any(source["url"] == "https://example.com/item" for source in body["sources"])

        feedback_response = client.post(
            f"/api/runs/{run_id}/feedback",
            json={
                "actual_action": "做了一个更小的版本",
                "satisfaction_score": 4,
                "regret_score": 1,
                "note": "缩小范围后顺畅多了。",
            },
        )
        assert feedback_response.status_code == 200


def test_clarification_flow():
    with TestClient(app) as client:
        app.state.manager.runtime = FakeRuntime()

        create_response = client.post(
            "/api/runs",
            json={"question": "要不要去", "notes": "", "links": []},
        )
        run_id = create_response.json()["run_id"]

        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        assert run_response.json()["run"]["status"] == "needs_clarification"


def test_clarification_link_is_persisted_and_resumes_run():
    with TestClient(app) as client:
        app.state.manager.runtime = FakeRuntime()

        create_response = client.post(
            "/api/runs",
            json={"question": "要不要买这款显示器", "notes": "", "links": []},
        )
        assert create_response.status_code == 200

        run_id = create_response.json()["run_id"]
        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        assert run_response.json()["run"]["status"] == "needs_clarification"

        clarification_response = client.post(
            f"/api/runs/{run_id}/clarifications",
            json={"answer": "商品链接在这：https://example.com/item，帮我看看值不值。"},
        )
        assert clarification_response.status_code == 200

        resumed_run = client.get(f"/api/runs/{run_id}")
        assert resumed_run.status_code == 200
        body = resumed_run.json()
        assert body["run"]["status"] == "completed"
        assert "https://example.com/item" in body["run"]["input_payload"]["links"]
        assert "Clarification: 商品链接在这：https://example.com/item，帮我看看值不值。" in body["run"]["input_payload"]["notes"]


def test_stream_respects_last_event_id_after_completion():
    with TestClient(app) as client:
        app.state.manager.runtime = FakeRuntime()

        create_response = client.post(
            "/api/runs",
            json={"question": "这个周末要不要做一个新项目？"},
        )
        assert create_response.status_code == 200

        run_id = create_response.json()["run_id"]
        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        last_event_id = run_response.json()["events"][-1]["id"]

        stream_response = client.get(
            f"/api/runs/{run_id}/stream",
            headers={"Last-Event-ID": str(last_event_id)},
        )
        assert stream_response.status_code == 200
        assert stream_response.text == ""


def test_freeform_question_can_finish_without_extra_form_fields():
    with TestClient(app) as client:
        app.state.manager.runtime = FakeRuntime()

        create_response = client.post(
            "/api/runs",
            json={
                "question": "我最近已经有两把键盘了，但又看上一把新的机械键盘，主要是手感和颜值让我心动，这笔钱花得值不值？",
            },
        )
        assert create_response.status_code == 200

        run_id = create_response.json()["run_id"]
        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        assert run_response.json()["run"]["status"] == "completed"


def test_cancel_endpoint_marks_waiting_run_cancelled():
    with TestClient(app) as client:
        app.state.manager.runtime = FakeRuntime()

        create_response = client.post(
            "/api/runs",
            json={"question": "要不要去", "notes": "", "links": []},
        )
        assert create_response.status_code == 200
        run_id = create_response.json()["run_id"]

        cancel_response = client.post(f"/api/runs/{run_id}/cancel")
        assert cancel_response.status_code == 200

        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        assert run_response.json()["run"]["status"] == "cancelled"


def test_timeout_uses_fallback_verdict_and_keeps_timeout_event():
    with TestClient(app) as client:
        app.state.manager.runtime = TimeoutRuntime()

        create_response = client.post(
            "/api/runs",
            json={"question": "这个周末要不要开始做一个新项目？"},
        )
        assert create_response.status_code == 200
        run_id = create_response.json()["run_id"]

        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        body = run_response.json()
        assert body["run"]["status"] == "completed"
        assert body["run"]["verdict"] is not None
        assert any(event["event_type"] == "timeout" for event in body["events"])
        assert any(source["title"] == "本地保守兜底" for source in body["sources"])


def test_runtime_exception_uses_fallback_verdict():
    with TestClient(app) as client:
        app.state.manager.runtime = ExplodingRuntime()

        create_response = client.post(
            "/api/runs",
            json={"question": "我要不要买这个新键盘？"},
        )
        assert create_response.status_code == 200
        run_id = create_response.json()["run_id"]

        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        body = run_response.json()
        assert body["run"]["status"] == "completed"
        assert body["run"]["verdict"] is not None
        assert any(event["event_type"] == "error" for event in body["events"])
