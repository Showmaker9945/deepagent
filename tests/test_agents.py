from app.agents import DecisionAgentRuntime
from app.config import Settings
from app.schemas import ClassificationResult, RunCreateRequest
from app.storage import Storage


class FakeStreamingAgent:
    def __init__(self) -> None:
        self.prompt: str | None = None

    def stream(self, payload, config, stream_mode, subgraphs):
        self.prompt = payload["messages"][0]["content"]
        yield (
            "updates",
            {
                "structured_response": {
                    "category": "work_learning",
                    "verdict": "可以先小步试试",
                    "confidence": 0.61,
                    "why_yes": ["有长期收益"],
                    "why_no": ["需要控制范围"],
                    "top_risks": ["高估周末精力"],
                    "best_alternative": "先做一个最小版本",
                    "recommended_next_step": "今晚先列出最小范围",
                    "follow_up_question": None,
                    "punchline": None,
                }
            },
        )


def test_run_streaming_includes_feedback_memory_in_prompt(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "agent.db")
    storage.init_db()
    storage.upsert_preference("work_learning:positive", "Prefer a smaller first step.", delta=2)
    storage.upsert_regret_pattern("work_learning:regret", "Regret overcommitting before validating.", delta=1)

    runtime = DecisionAgentRuntime(Settings(), storage)
    fake_agent = FakeStreamingAgent()
    monkeypatch.setattr(runtime, "_get_agent", lambda classification: fake_agent)

    payload = RunCreateRequest(question="这个周末要不要开始做一个 AI 小工具？")
    classification = ClassificationResult(category="work_learning", reason="stub")

    events = list(
        runtime.run_streaming(
            "run-1",
            payload,
            classification,
            timeout_seconds=5,
            should_cancel=lambda: False,
        )
    )

    assert any(event.event_type == "verdict_ready" for event in events)
    assert fake_agent.prompt is not None
    assert "memory_snapshot" in fake_agent.prompt
    assert "Prefer a smaller first step." in fake_agent.prompt
    assert "Regret overcommitting before validating." in fake_agent.prompt
