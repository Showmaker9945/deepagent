from langsmith.run_trees import RunTree

from app.config import Settings
from app.langsmith_utils import (
    annotate_traced_span,
    build_root_trace_metadata,
    configure_langsmith,
    hash_identifier,
    sanitize_trace_value,
)
from app.schemas import RunCreateRequest


def test_sanitize_trace_value_hashes_ids_and_redacts_secrets():
    payload = {
        "user_id": "local-user",
        "api_key": "secret-token",
        "url": "https://example.com/item?token=abc#frag",
    }

    sanitized = sanitize_trace_value(payload)

    assert sanitized["user_id"] == hash_identifier("local-user")
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["url"] == "https://example.com/item"


def test_sanitize_trace_value_truncates_large_content_and_caps_links():
    payload = {
        "content": "x" * 1200,
        "links": [
            "https://example.com/1?a=1",
            "https://example.com/2?a=1",
            "https://example.com/3?a=1",
            "https://example.com/4?a=1",
            "https://example.com/5?a=1",
            "https://example.com/6?a=1",
        ],
    }

    sanitized = sanitize_trace_value(payload)

    assert sanitized["content"].endswith("...[truncated]")
    assert len(sanitized["links"]) == 5
    assert sanitized["links"][0] == "https://example.com/1"


def test_build_root_trace_metadata_captures_request_shape(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    settings = Settings()
    payload = RunCreateRequest(
        question="要不要买这个显示器？",
        budget="2500",
        location="上海",
        links=["https://example.com/item?campaign=test"],
    )

    metadata = build_root_trace_metadata(
        settings,
        run_id="run-123",
        user_id="local-user",
        clarification_count=1,
        payload=payload,
    )

    assert metadata["thread_id"] == "run-123"
    assert metadata["run_id"] == "run-123"
    assert metadata["app_env"] == "test"
    assert metadata["user_id"] == hash_identifier("local-user")
    assert metadata["links_count"] == 1
    assert metadata["has_budget"] is True
    assert metadata["has_location"] is True
    assert metadata["payload_preview"]["links"] == ["https://example.com/item"]


def test_configure_langsmith_sets_expected_env(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "demo-project")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "ws_123")

    settings = Settings()
    status = configure_langsmith(settings)

    assert status.enabled is True
    assert "demo-project" in status.message


def test_annotate_traced_span_updates_run_tree_without_property_assignment():
    span = RunTree(name="unit-test-run")

    annotate_traced_span(
        span,
        tags=["kind:test", "kind:test"],
        metadata={
            "user_id": "local-user",
            "url": "https://example.com/item?token=abc#frag",
        },
    )
    annotate_traced_span(
        span,
        tags=["kind:test", "path:deepagent"],
        metadata={"question": "x" * 1200},
    )

    assert span.metadata["user_id"] == hash_identifier("local-user")
    assert span.metadata["url"] == "https://example.com/item"
    assert span.metadata["question"].endswith("...[truncated]")
    assert span.tags.count("kind:test") == 1
    assert "path:deepagent" in span.tags
