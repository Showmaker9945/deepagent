import sqlite3

from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from langgraph.checkpoint.sqlite import SqliteSaver

import app.agents as agents_module
from app.agents import (
    DecisionAgentRuntime,
    SkillTracingFilesystemBackend,
    begin_skill_trace,
    collect_registered_skill_catalog,
    get_skill_trace_snapshot,
    reset_skill_trace,
    select_skill_candidates,
)
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


def test_get_agent_registers_disk_backed_skills(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "agent.db")
    storage.init_db()

    runtime = DecisionAgentRuntime(Settings(CHECKPOINT_DB_PATH=tmp_path / "checkpoints.db"), storage)
    captured: dict[str, object] = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agents_module, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(runtime, "_require_model", lambda: object())

    classification = ClassificationResult(category="spending", reason="stub")
    runtime._get_agent(classification)

    assert captured["skills"] == agents_module.DEEPAGENT_SKILL_SOURCES
    assert isinstance(captured["checkpointer"], SqliteSaver)
    assert captured["checkpointer"] is runtime._require_checkpointer()

    backend_factory = captured["backend"]
    assert callable(backend_factory)

    composite_backend = backend_factory(object())
    assert isinstance(composite_backend, CompositeBackend)
    assert set(composite_backend.routes) == set(agents_module.SKILL_ROUTE_ROOTS)

    for route_prefix, route_root in agents_module.SKILL_ROUTE_ROOTS.items():
        route_backend = composite_backend.routes[route_prefix]
        assert isinstance(route_backend, FilesystemBackend)
        assert route_backend.virtual_mode is True
        assert route_backend.cwd == route_root.resolve()

    runtime.close()


def test_runtime_reuses_single_sqlite_checkpointer(tmp_path):
    storage = Storage(tmp_path / "agent.db")
    storage.init_db()
    checkpoint_path = tmp_path / "checkpoints.db"
    runtime = DecisionAgentRuntime(Settings(CHECKPOINT_DB_PATH=checkpoint_path), storage)

    checkpointer_one = runtime._require_checkpointer()
    checkpointer_two = runtime._require_checkpointer()

    assert isinstance(checkpointer_one, SqliteSaver)
    assert checkpointer_one is checkpointer_two
    assert checkpoint_path.exists()

    with sqlite3.connect(checkpoint_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {"checkpoints", "writes"} <= tables

    runtime.close()

    assert runtime._checkpointer is None
    assert runtime._checkpoint_conn is None


def test_collect_registered_skill_catalog_lists_bundled_skills():
    catalog = collect_registered_skill_catalog()
    names = {item["name"] for item in catalog}

    assert "link-first-research" in names
    assert "memory-regret-check" in names


def test_select_skill_candidates_uses_links_and_memory():
    payload = RunCreateRequest(
        question="我要不要买这个课程？",
        links=["https://example.com/course"],
    )
    classification = ClassificationResult(category="spending", reason="stub")
    memory_snapshot = {
        "profile_markdown": "Prefer smaller bets first.",
        "regret_markdown": "You regret rushing with thin facts.",
    }

    candidates = select_skill_candidates(payload, classification, memory_snapshot)

    assert candidates == ["link-first-research", "memory-regret-check"]


def test_skill_tracing_backend_records_scan_load_and_read(tmp_path):
    skill_dir = tmp_path / "memory-regret-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: memory-regret-check\ndescription: demo\n---\n", encoding="utf-8")

    token = begin_skill_trace(
        available_skills=[{"name": "memory-regret-check", "path": "/skills/project/memory-regret-check/SKILL.md", "source": "project"}],
        candidate_skill_names=["memory-regret-check"],
    )
    try:
        backend = SkillTracingFilesystemBackend(
            route_prefix="/skills/project/",
            root_dir=tmp_path,
        )

        listing = backend.ls_info("/")
        downloads = backend.download_files(["/memory-regret-check/SKILL.md"])
        content = backend.read("/memory-regret-check/SKILL.md")
        snapshot = get_skill_trace_snapshot()

        assert listing
        assert downloads[0].content is not None
        assert "memory-regret-check" in content
        assert snapshot is not None
        assert "/skills/project/" in snapshot.metadata_scan_paths
        assert "/skills/project/memory-regret-check/SKILL.md" in snapshot.metadata_load_paths
        assert snapshot.metadata_load_names == ["memory-regret-check"]
        assert snapshot.read_names == ["memory-regret-check"]
        assert "skill_read:memory-regret-check" in snapshot.to_tags()
    finally:
        reset_skill_trace(token)
