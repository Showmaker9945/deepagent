from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit

from langchain_core.tracers.langchain import wait_for_all_tracers
from langsmith import Client, trace

from app.config import Settings

DEFAULT_TEXT_LIMIT = 250
URL_LIMIT = 180
TRACE_TEXT_LIMITS = {
    "question": 600,
    "prompt": 900,
    "content": 800,
    "notes": 320,
    "note": 320,
    "message": 600,
    "reason": 400,
    "summary": 400,
    "snippet": 320,
    "actual_action": 120,
}
URL_KEYS = {"url", "links", "source_url", "source_urls"}
SECRET_FIELD_MARKERS = ("api_key", "authorization", "password", "secret", "token")

_CLIENT_CACHE: Client | None = None
_CLIENT_CACHE_KEY: tuple[str, ...] | None = None
TraceRunType = Literal["tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"]


@dataclass(slots=True, frozen=True)
class LangSmithStatus:
    enabled: bool
    message: str


def configure_langsmith(settings: Settings) -> LangSmithStatus:
    _set_env("LANGSMITH_TRACING", "true" if settings.langsmith_tracing else "false")
    _set_env("LANGSMITH_OTEL_ENABLED", "true" if settings.langsmith_otel_enabled else "false")
    _set_env("LANGSMITH_PROJECT", settings.langsmith_project)
    _set_env("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
    _set_env("LANGSMITH_WORKSPACE_ID", settings.langsmith_workspace_id)

    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    elif not settings.langsmith_tracing:
        os.environ.pop("LANGSMITH_API_KEY", None)

    if not settings.langsmith_tracing:
        return LangSmithStatus(False, "LangSmith tracing is disabled.")
    if not settings.langsmith_api_key:
        return LangSmithStatus(False, "LangSmith tracing is enabled, but LANGSMITH_API_KEY is missing.")
    return LangSmithStatus(True, f"LangSmith tracing is enabled for project `{settings.langsmith_project}`.")


def is_langsmith_enabled(settings: Settings) -> bool:
    return settings.langsmith_tracing and bool(settings.langsmith_api_key)


def get_langsmith_client(settings: Settings) -> Client | None:
    if not is_langsmith_enabled(settings):
        return None

    global _CLIENT_CACHE, _CLIENT_CACHE_KEY
    cache_key = (
        settings.langsmith_api_key or "",
        settings.langsmith_endpoint,
        settings.langsmith_workspace_id or "",
        settings.langsmith_project,
        "1" if settings.langsmith_otel_enabled else "0",
    )
    if _CLIENT_CACHE is not None and _CLIENT_CACHE_KEY == cache_key:
        return _CLIENT_CACHE

    _CLIENT_CACHE = Client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint,
        workspace_id=settings.langsmith_workspace_id or None,
        otel_enabled=settings.langsmith_otel_enabled,
        hide_inputs=sanitize_trace_dict,
        hide_outputs=sanitize_trace_dict,
        hide_metadata=sanitize_trace_dict,
    )
    _CLIENT_CACHE_KEY = cache_key
    return _CLIENT_CACHE


def flush_langsmith_traces(settings: Settings) -> None:
    client = get_langsmith_client(settings)
    if client is not None:
        client.flush()
    wait_for_all_tracers()


def make_trace_tags(settings: Settings, *tags: str) -> list[str]:
    return _dedupe_tags(["app:do-or-not", f"env:{settings.app_env}", *tags])


def build_root_trace_metadata(
    settings: Settings,
    *,
    run_id: str,
    user_id: str,
    clarification_count: int,
    payload: Any,
) -> dict[str, Any]:
    sanitized_payload = sanitize_trace_value(payload)
    links = payload.links if hasattr(payload, "links") else []
    return {
        "thread_id": run_id,
        "run_id": run_id,
        "app_env": settings.app_env,
        "user_id": hash_identifier(user_id),
        "clarification_count": clarification_count,
        "question_length": len(getattr(payload, "question", "").strip()),
        "has_links": bool(links),
        "links_count": len(links),
        "has_budget": bool(getattr(payload, "budget", None)),
        "has_deadline": bool(getattr(payload, "deadline", None)),
        "has_location": bool(getattr(payload, "location", None)),
        "payload_preview": sanitized_payload,
    }


@contextmanager
def traced_span(
    settings: Settings,
    *,
    name: str,
    run_type: TraceRunType = "chain",
    inputs: Any | None = None,
    tags: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Any | None]:
    client = get_langsmith_client(settings)
    if client is None:
        yield None
        return

    with trace(
        name=name,
        run_type=run_type,
        inputs=_as_trace_dict(sanitize_trace_value(inputs)) if inputs is not None else None,
        metadata=sanitize_trace_dict(dict(metadata or {})),
        tags=_dedupe_tags(tags or []),
        client=client,
        project_name=settings.langsmith_project,
    ) as run_tree:
        yield run_tree


def annotate_traced_span(
    span: Any | None,
    *,
    tags: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    if span is None:
        return

    if metadata:
        sanitized_metadata = sanitize_trace_dict(dict(metadata))
        if hasattr(span, "add_metadata"):
            span.add_metadata(sanitized_metadata)
        else:
            existing_metadata = dict(getattr(span, "metadata", {}) or {})
            existing_metadata.update(sanitized_metadata)
            current_metadata = getattr(span, "metadata", None)
            if isinstance(current_metadata, dict):
                current_metadata.update(existing_metadata)
    if tags:
        incoming_tags = _dedupe_tags(tags)
        existing_tags = list(getattr(span, "tags", []) or [])
        missing_tags = [tag for tag in incoming_tags if tag not in existing_tags]
        if not missing_tags:
            return
        if hasattr(span, "add_tags"):
            span.add_tags(missing_tags)
        else:
            span.tags = _dedupe_tags([*existing_tags, *missing_tags])


def end_traced_span(
    span: Any | None,
    *,
    outputs: Any | None = None,
    error: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    if span is None:
        return
    span.end(
        outputs=_as_trace_dict(sanitize_trace_value(outputs)) if outputs is not None else None,
        error=shorten_text(error, 400) if error else None,
        metadata=sanitize_trace_dict(dict(metadata or {})) if metadata else None,
    )


def sanitize_trace_dict(payload: Any) -> dict[str, Any]:
    return _as_trace_dict(sanitize_trace_value(payload))


def sanitize_trace_value(value: Any, *, key: str | None = None) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, Mapping):
        return {str(item_key): sanitize_trace_value(item_value, key=str(item_key)) for item_key, item_value in value.items()}

    if isinstance(value, (list, tuple, set)):
        sanitized_items = [sanitize_trace_value(item, key=key) for item in value]
        return sanitized_items[:5] if key and key.lower() in {"links", "urls"} else sanitized_items

    if isinstance(value, str):
        return _sanitize_string(value, key)

    return shorten_text(repr(value), DEFAULT_TEXT_LIMIT)


def shorten_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(limit - 15, 0)]}...[truncated]"


def sanitize_url(url: str) -> str:
    candidate = url.strip()
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return shorten_text(candidate, URL_LIMIT) or ""

    if not parsed.scheme or not parsed.netloc:
        return shorten_text(candidate, URL_LIMIT) or ""

    sanitized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return shorten_text(sanitized, URL_LIMIT) or ""


def hash_identifier(value: str | None) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"


def _sanitize_string(value: str, key: str | None) -> str:
    lowered_key = (key or "").lower()
    if lowered_key == "user_id" or lowered_key.endswith("_user_id"):
        return hash_identifier(value) or ""
    if any(marker in lowered_key for marker in SECRET_FIELD_MARKERS):
        return "[REDACTED]"
    if lowered_key in URL_KEYS or (lowered_key.endswith("_url") and value.startswith(("http://", "https://"))):
        return sanitize_url(value)
    if value.startswith(("http://", "https://")) and lowered_key in {"value", "link"}:
        return sanitize_url(value)
    limit = TRACE_TEXT_LIMITS.get(lowered_key, DEFAULT_TEXT_LIMIT)
    return shorten_text(value, limit) or ""


def _dedupe_tags(tags: list[str]) -> list[str]:
    unique_tags: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not tag or tag in seen:
            continue
        seen.add(tag)
        unique_tags.append(tag)
    return unique_tags


def _as_trace_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


def _set_env(key: str, value: str | None) -> None:
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
