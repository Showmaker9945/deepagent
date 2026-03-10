from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ResearchSummary, RunVerdict, SkepticSummary


class FakeRuntime:
    def run_researcher(self, payload, classification, snapshot):
        return ResearchSummary(
            summary="Research says the idea is plausible.",
            supporting_evidence=["There is a clear upside."],
            factual_observations=["Nothing exploded yet."],
            relevant_links=payload.links,
            tool_notes=["Stubbed in tests."],
        )

    def run_skeptic(self, payload, classification, snapshot, research):
        return SkepticSummary(
            summary="Skeptic says the hidden cost is time.",
            risks=["You may underestimate the time sink."],
            reasons_not_to_do=["Your calendar is already crunchy."],
            cheaper_or_lower_risk_options=["Try a 30-minute version first."],
            boundary_flags=[],
        )

    def run_decider(self, run_id, payload, classification, snapshot, research, skeptic):
        return RunVerdict(
            category=classification.category,
            verdict="do it carefully",
            confidence=0.74,
            why_yes=["The upside is real."],
            why_no=["Time cost is the main trap."],
            top_risks=["Scope creep."],
            best_alternative="Run a smaller pilot first.",
            recommended_next_step="Block 30 minutes and test it on a tiny version.",
            follow_up_question="What would make this obviously worth it?",
            punchline="能冲，但先别把自己冲成燃尽套餐。",
        )


def test_run_flow_and_feedback():
    with TestClient(app) as client:
        app.state.manager.runtime = FakeRuntime()

        create_response = client.post(
            "/api/runs",
            json={"question": "这个周末我要不要开始做一个小项目？我想做点能放作品集的东西。"},
        )
        assert create_response.status_code == 200

        run_id = create_response.json()["run_id"]
        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        body = run_response.json()
        assert body["run"]["status"] == "completed"
        assert body["run"]["verdict"]["verdict"] == "do it carefully"

        feedback_response = client.post(
            f"/api/runs/{run_id}/feedback",
            json={
                "actual_action": "做了一个更小的版本",
                "satisfaction_score": 4,
                "regret_score": 1,
                "note": "缩小范围后明显顺畅多了",
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
        assert run_response.json()["run"]["status"] in {"needs_clarification", "completed"}


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
            json={"question": "这个周末我要不要开始做一个小项目？我想做点能放作品集的东西。"},
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
