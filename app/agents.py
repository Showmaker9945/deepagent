from __future__ import annotations

import contextvars
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import SecretStr

from app.config import Settings
from app.langsmith_utils import (
    annotate_traced_span,
    configure_langsmith,
    end_traced_span,
    make_trace_tags,
    traced_span,
)
from app.prompts import build_main_prompt
from app.schemas import ClassificationResult, RunCreateRequest, RunImage, RunVerdict, VisualReport
from app.scoring import score_tradeoff
from app.storage import Storage
from app.tools import ToolFactory, reset_tool_context, set_tool_context
from app.visual import VisualAnalyzer, visual_report_status

logger = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DEEPAGENT_SKILL_SOURCES = ["/skills/base/", "/skills/project/"]
SKILL_ROUTE_ROOTS = {
    "/skills/base/": PROJECT_ROOT / "skills" / "base",
    "/skills/project/": PROJECT_ROOT / "skills" / "project",
}
EMPTY_PROFILE_MEMORY = "No persistent preferences yet."
EMPTY_REGRET_MEMORY = "No regret patterns recorded yet."
SKILL_INTERFACE_KEYS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}
CURRENT_SKILL_TRACE: contextvars.ContextVar["SkillTraceSnapshot | None"] = contextvars.ContextVar(
    "do_or_not_skill_trace",
    default=None,
)


@dataclass(slots=True)
class SkillTraceSnapshot:
    available_skills: list[dict[str, Any]]
    candidate_skill_names: list[str]
    metadata_scan_paths: list[str] = field(default_factory=list)
    metadata_load_paths: list[str] = field(default_factory=list)
    metadata_load_names: list[str] = field(default_factory=list)
    read_paths: list[str] = field(default_factory=list)
    read_names: list[str] = field(default_factory=list)

    def record_scan(self, path: str) -> None:
        _append_unique(self.metadata_scan_paths, path)

    def record_metadata_load(self, path: str) -> None:
        _append_unique(self.metadata_load_paths, path)
        _append_unique(self.metadata_load_names, PurePosixPath(path).parent.name)

    def record_read(self, path: str) -> None:
        _append_unique(self.read_paths, path)
        _append_unique(self.read_names, PurePosixPath(path).parent.name)

    def to_metadata(self) -> dict[str, Any]:
        available_skill_metadata = _summarize_skill_catalog(self.available_skills)
        candidate_skill_metadata = _summarize_skill_catalog(
            self.available_skills,
            self.candidate_skill_names,
        )
        return {
            "skill_sources": list(DEEPAGENT_SKILL_SOURCES),
            "available_skill_names": [item["name"] for item in self.available_skills],
            "available_skills": self.available_skills,
            "available_skill_metadata": available_skill_metadata,
            "available_skill_ui_metadata_count": sum(
                1 for item in available_skill_metadata if item["has_openai_yaml"]
            ),
            "candidate_skill_names": list(self.candidate_skill_names),
            "candidate_skill_metadata": candidate_skill_metadata,
            "metadata_scan_paths": list(self.metadata_scan_paths),
            "metadata_load_paths": list(self.metadata_load_paths),
            "metadata_load_names": list(self.metadata_load_names),
            "skill_read_paths": list(self.read_paths),
            "skill_read_names": list(self.read_names),
            "skill_read_count": len(self.read_names),
        }

    def to_tags(self) -> list[str]:
        tags = [f"skill_candidate:{name}" for name in self.candidate_skill_names]
        tags.extend(f"skill_read:{name}" for name in self.read_names)
        if self.read_names:
            tags.append("skills:read")
        elif self.candidate_skill_names:
            tags.append("skills:candidate_only")
        else:
            tags.append("skills:none")
        return tags


def collect_registered_skill_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for source_path, route_root in SKILL_ROUTE_ROOTS.items():
        if not route_root.exists():
            continue
        source_name = PurePosixPath(source_path.rstrip("/")).name
        for skill_dir in sorted(route_root.iterdir(), key=lambda item: item.name):
            skill_file = skill_dir / "SKILL.md"
            if not skill_dir.is_dir() or not skill_file.exists():
                continue
            interface = _read_skill_interface_metadata(skill_dir)
            item: dict[str, Any] = {
                "name": skill_dir.name,
                "path": f"{source_path}{skill_dir.name}/SKILL.md",
                "source": source_name,
                "has_openai_yaml": bool(interface),
            }
            if interface:
                item["metadata_path"] = f"{source_path}{skill_dir.name}/agents/openai.yaml"
                item["interface"] = interface
                item["display_name"] = interface.get("display_name", skill_dir.name)
                if interface.get("short_description"):
                    item["short_description"] = interface["short_description"]
                if interface.get("default_prompt"):
                    item["default_prompt"] = interface["default_prompt"]
            catalog.append(item)
    return catalog


def select_skill_candidates(
    payload: RunCreateRequest,
    classification: ClassificationResult,
    memory_snapshot: dict[str, str],
) -> list[str]:
    candidates: list[str] = []
    has_memory = (
        memory_snapshot.get("profile_markdown", "").strip() != EMPTY_PROFILE_MEMORY
        or memory_snapshot.get("regret_markdown", "").strip() != EMPTY_REGRET_MEMORY
    )
    if payload.image_ids:
        candidates.append("image-evidence-intake")
    if payload.links or (classification.category == "travel" and bool(payload.location)):
        candidates.append("link-first-research")
    if classification.category != "unsupported" and has_memory:
        candidates.append("memory-regret-check")
    return candidates


def begin_skill_trace(
    available_skills: list[dict[str, Any]],
    candidate_skill_names: list[str],
) -> contextvars.Token:
    return CURRENT_SKILL_TRACE.set(
        SkillTraceSnapshot(
            available_skills=available_skills,
            candidate_skill_names=candidate_skill_names,
        )
    )


def get_skill_trace_snapshot() -> SkillTraceSnapshot | None:
    return CURRENT_SKILL_TRACE.get()


def reset_skill_trace(token: contextvars.Token) -> None:
    CURRENT_SKILL_TRACE.reset(token)


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _read_skill_interface_metadata(skill_dir: Path) -> dict[str, str]:
    metadata_path = skill_dir / "agents" / "openai.yaml"
    if not metadata_path.exists():
        return {}

    interface: dict[str, str] = {}
    in_interface = False
    interface_indent = 0

    for raw_line in metadata_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = raw_line.rstrip()

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = line.strip()

        if not in_interface:
            if stripped == "interface:":
                in_interface = True
                interface_indent = indent
            continue

        if indent <= interface_indent:
            break

        key, separator, raw_value = stripped.partition(":")
        if not separator:
            continue

        normalized_key = key.strip()
        if normalized_key not in SKILL_INTERFACE_KEYS:
            continue

        value = _parse_yaml_string(raw_value.strip())
        if value:
            interface[normalized_key] = value

    return interface


def _parse_yaml_string(value: str) -> str:
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _summarize_skill_catalog(
    skills: list[dict[str, Any]],
    selected_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    if selected_names is None:
        return [_build_skill_metadata_summary(item) for item in skills]

    by_name = {str(item["name"]): item for item in skills}
    return [_build_skill_metadata_summary(by_name[name]) for name in selected_names if name in by_name]


def _build_skill_metadata_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "name": item["name"],
        "source": item["source"],
        "path": item["path"],
        "display_name": item.get("display_name", item["name"]),
        "has_openai_yaml": bool(item.get("has_openai_yaml")),
    }
    if item.get("short_description"):
        summary["short_description"] = item["short_description"]
    if item.get("default_prompt"):
        summary["default_prompt"] = item["default_prompt"]
    if item.get("metadata_path"):
        summary["metadata_path"] = item["metadata_path"]
    return summary


class SkillTracingFilesystemBackend(FilesystemBackend):
    def __init__(self, *, route_prefix: str, root_dir: Path) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True)
        self.route_prefix = route_prefix

    def ls_info(self, path: str) -> list[dict[str, Any]]:
        snapshot = get_skill_trace_snapshot()
        if snapshot is not None:
            snapshot.record_scan(self._restore_virtual_path(path))
        return super().ls_info(path)

    def download_files(self, paths: list[str]) -> list[Any]:
        snapshot = get_skill_trace_snapshot()
        if snapshot is not None:
            for path in paths:
                restored = self._restore_virtual_path(path)
                if restored.endswith("/SKILL.md"):
                    snapshot.record_metadata_load(restored)
        return super().download_files(paths)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        snapshot = get_skill_trace_snapshot()
        if snapshot is not None:
            restored = self._restore_virtual_path(file_path)
            if restored.endswith("/SKILL.md"):
                snapshot.record_read(restored)
        return super().read(file_path, offset=offset, limit=limit)

    def _restore_virtual_path(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        if normalized == "/":
            return self.route_prefix
        return f"{self.route_prefix.rstrip('/')}{normalized}"


def build_deepagent_backend(runtime: Any) -> CompositeBackend:
    return CompositeBackend(
        default=StateBackend(runtime),
        routes={
            route_prefix: SkillTracingFilesystemBackend(route_prefix=route_prefix, root_dir=route_root)
            for route_prefix, route_root in SKILL_ROUTE_ROOTS.items()
        },
    )


class AgentConfigurationError(RuntimeError):
    pass


@dataclass(slots=True)
class RuntimeStreamEvent:
    event_type: str
    payload: dict[str, Any]


class DecisionAgentRuntime:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage
        self.langsmith_status = configure_langsmith(settings)
        self.tools = ToolFactory(settings).build()
        self.visual_analyzer = VisualAnalyzer(settings)
        self._model: ChatOpenAI | None = None
        self._checkpoint_conn: sqlite3.Connection | None = None
        self._checkpointer: SqliteSaver | None = None
        self._agents: dict[tuple[str, bool], Any] = {}

    def _require_model(self) -> ChatOpenAI:
        if self._model is not None:
            return self._model
        if self.settings.dashscope_config_issue is not None:
            raise AgentConfigurationError(self.settings.dashscope_config_issue)
        api_key = SecretStr(self.settings.dashscope_api_key)
        self._model = ChatOpenAI(
            api_key=api_key,
            base_url=self.settings.dashscope_base_url,
            model=self.settings.model_name,
            temperature=0.1,
            timeout=self.settings.model_timeout_seconds,
            max_retries=0,
            streaming=True,
        )
        return self._model

    def _require_checkpointer(self) -> SqliteSaver:
        if self._checkpointer is not None:
            return self._checkpointer

        checkpoint_path = self.settings.checkpoint_db_path
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL;")
        checkpointer = SqliteSaver(connection)
        checkpointer.setup()
        self._checkpoint_conn = connection
        self._checkpointer = checkpointer
        return checkpointer

    def close(self) -> None:
        self._agents.clear()
        self._checkpointer = None
        if self._checkpoint_conn is None:
            return
        try:
            self._checkpoint_conn.close()
        finally:
            self._checkpoint_conn = None

    def _get_agent(self, classification: ClassificationResult):
        key = (classification.category, classification.humor_allowed)
        agent = self._agents.get(key)
        if agent is None:
            agent = create_deep_agent(
                model=self._require_model(),
                tools=self.tools,
                system_prompt=build_main_prompt(classification.category, classification.humor_allowed),
                skills=DEEPAGENT_SKILL_SOURCES,
                response_format=ToolStrategy(RunVerdict),
                checkpointer=self._require_checkpointer(),
                backend=build_deepagent_backend,
                name=f"do-or-not-{classification.category}",
            )
            self._agents[key] = agent
            logger.info(
                "Created deep agent",
                extra={
                    "category": classification.category,
                    "status": "created",
                },
            )
        return agent

    def run_streaming(
        self,
        run_id: str,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        *,
        timeout_seconds: int,
        should_cancel: Callable[[], bool],
    ) -> Iterator[RuntimeStreamEvent]:
        agent = self._get_agent(classification)
        with traced_span(
            self.settings,
            name="preflight_tradeoff",
            inputs=payload.model_dump(mode="json"),
            tags=make_trace_tags(
                self.settings,
                "component:scoring",
                f"category:{classification.category}",
            ),
            metadata={
                "run_id": run_id,
                "thread_id": run_id,
                "category": classification.category,
            },
        ) as score_span:
            preflight_tradeoff = score_tradeoff(classification.category, payload)
            end_traced_span(score_span, outputs=preflight_tradeoff)

        images = self.storage.list_images(run_id)
        visual_report: VisualReport | None = None
        memory_snapshot = self.storage.get_memory_snapshot().model_dump(mode="json")
        available_skills = collect_registered_skill_catalog()
        candidate_skill_names = select_skill_candidates(payload, classification, memory_snapshot)
        start_time = time.monotonic()
        logger.info(
            "Starting deep agent stream",
            extra={
                "run_id": run_id,
                "category": classification.category,
                "status": "running",
            },
        )
        token_buffer = ""
        agent_result: dict[str, Any] = {
            "status": "running",
            "category": classification.category,
            "preflight_average": preflight_tradeoff.get("average"),
            "links_count": len(payload.links),
            "image_count": len(images),
            "model_name": self.settings.model_name,
        }
        context_token = set_tool_context(
            {
                "run_id": run_id,
                "category": classification.category,
                "links": payload.links,
                "image_ids": payload.image_ids,
                "preflight_tradeoff": preflight_tradeoff,
            }
        )
        skill_trace_token = begin_skill_trace(available_skills, candidate_skill_names)

        try:
            with traced_span(
                self.settings,
                name="deepagent_stream",
                inputs={
                    "question": payload.question,
                    "classification": classification.model_dump(mode="json"),
                    "context_hints": self._build_context_hints(payload, classification),
                    "preflight_tradeoff": preflight_tradeoff,
                    "memory_snapshot": memory_snapshot,
                    "image_inputs": self._serialize_image_inputs(images),
                    "visual_report": visual_report.model_dump(mode="json") if visual_report is not None else None,
                },
                tags=make_trace_tags(
                    self.settings,
                    "component:deepagent",
                    f"category:{classification.category}",
                ),
                metadata={
                    "run_id": run_id,
                    "thread_id": run_id,
                    "category": classification.category,
                    "ls_provider": "dashscope",
                    "ls_model_name": self.settings.model_name,
                    "humor_allowed": classification.humor_allowed,
                    "image_count": len(images),
                    "image_names": [image.file_name for image in images],
                    "visual_report_present": visual_report is not None,
                    "available_skill_names": [item["name"] for item in available_skills],
                    "candidate_skill_names": candidate_skill_names,
                },
            ) as agent_span:
                annotate_traced_span(
                    agent_span,
                    metadata={
                        "memory_profile_present": "No persistent preferences yet." not in memory_snapshot["profile_markdown"],
                        "memory_regret_present": "No regret patterns recorded yet." not in memory_snapshot["regret_markdown"],
                        "visual_uncertainty_count": len(visual_report.uncertainties) if visual_report is not None else 0,
                    },
                )
                try:
                    yield RuntimeStreamEvent(
                        "source_captured",
                        {
                            "source_type": "tool_note",
                            "title": "本地预打分",
                            "url": None,
                            "snippet": preflight_tradeoff.get("summary"),
                            "source_meta": {
                                "average": preflight_tradeoff.get("average"),
                                "scores": preflight_tradeoff.get("scores", {}),
                            },
                        },
                    )
                    if images:
                        yield RuntimeStreamEvent(
                            "tool_started",
                            {
                                "tool_name": "image_evidence_intake",
                                "summary": f"正在整理你上传的 {len(images)} 张图片证据。",
                            },
                        )
                        visual_report = self._build_visual_report(run_id, payload, classification, images)
                        if visual_report is not None:
                            current_visual_status = visual_report_status(visual_report)
                            self.storage.update_status(run_id, "running", visual_report=visual_report)
                            annotate_traced_span(
                                agent_span,
                                metadata={
                                    "visual_report_present": True,
                                    "visual_uncertainty_count": len(visual_report.uncertainties),
                                    "visual_analysis_status": current_visual_status,
                                },
                            )
                            yield RuntimeStreamEvent(
                                "source_captured",
                                {
                                    "source_type": "tool_note",
                                    "title": "图片证据摘要",
                                    "url": None,
                                    "snippet": visual_report.summary,
                                    "source_meta": {
                                        "status": current_visual_status,
                                        "image_count": visual_report.image_count,
                                        "facts": visual_report.extracted_facts,
                                        "uncertainties": visual_report.uncertainties,
                                    },
                                },
                            )
                        yield RuntimeStreamEvent(
                            "tool_finished",
                            {
                                "tool_name": "image_evidence_intake",
                                "status": visual_report_status(visual_report) if visual_report is not None else "ok",
                                "summary": (
                                    "图片证据摘要已准备好，会一起送进这轮判断。"
                                    if visual_report is not None and visual_report_status(visual_report) == "ok"
                                    else "图片已收录，但视觉分析这轮没有稳定产出硬证据，我会按弱证据处理。"
                                ),
                            },
                        )
                    prompt = self._build_context_prompt(
                        payload,
                        classification,
                        preflight_tradeoff,
                        memory_snapshot,
                        images,
                        visual_report,
                    )
                    yield RuntimeStreamEvent(
                        "agent_started",
                        {
                            "category": classification.category,
                            "mode": "deep_agent",
                            "message": "Deep Agent 已接管，我会先参考本地预打分，再决定是否需要联网。",
                        },
                    )

                    if should_cancel():
                        agent_result["status"] = "cancelled"
                        yield RuntimeStreamEvent("cancelled", {"message": "分析已取消。"})
                        return

                    stream = agent.stream(
                        {"messages": [{"role": "user", "content": prompt}]},
                        config={"configurable": {"thread_id": run_id}},
                        stream_mode=["updates", "messages", "custom"],
                        subgraphs=True,
                    )

                    for item in stream:
                        if should_cancel():
                            if token_buffer.strip():
                                yield RuntimeStreamEvent("agent_token", {"text": token_buffer})
                                token_buffer = ""
                            agent_result["status"] = "cancelled"
                            yield RuntimeStreamEvent("cancelled", {"message": "用户主动停止了这轮分析。"})
                            return

                        if time.monotonic() - start_time > timeout_seconds:
                            if token_buffer.strip():
                                yield RuntimeStreamEvent("agent_token", {"text": token_buffer})
                                token_buffer = ""
                            agent_result["status"] = "timed_out"
                            yield RuntimeStreamEvent(
                                "timeout",
                                {"message": f"本轮分析超过 {timeout_seconds} 秒，系统已自动收手。"},
                            )
                            return

                        _, mode, data = self._normalize_stream_item(item)

                        if mode == "messages":
                            text = self._extract_message_text(data[0])
                            if text:
                                token_buffer += text
                                if len(token_buffer) >= 80 or token_buffer.endswith(("。", "！", "？", "\n")):
                                    yield RuntimeStreamEvent("agent_token", {"text": token_buffer})
                                    token_buffer = ""
                            continue

                        if mode == "custom":
                            custom_event = self._parse_custom_event(data)
                            if custom_event is not None:
                                yield custom_event
                            continue

                        if mode == "updates":
                            structured = self._extract_structured_response(data)
                            if structured is not None:
                                if token_buffer.strip():
                                    yield RuntimeStreamEvent("agent_token", {"text": token_buffer})
                                    token_buffer = ""
                                verdict = RunVerdict.model_validate(structured)
                                agent_result["status"] = "completed"
                                agent_result["verdict"] = verdict.model_dump(mode="json")
                                yield RuntimeStreamEvent("verdict_ready", verdict.model_dump(mode="json"))
                                return

                    if token_buffer.strip():
                        yield RuntimeStreamEvent("agent_token", {"text": token_buffer})

                    agent_result["status"] = "no_structured_output"
                except Exception as exc:
                    agent_result["status"] = "error"
                    agent_result["error"] = str(exc)
                    raise
                finally:
                    skill_snapshot = get_skill_trace_snapshot()
                    if skill_snapshot is not None:
                        agent_result["available_skill_names"] = [item["name"] for item in skill_snapshot.available_skills]
                        agent_result["candidate_skill_names"] = list(skill_snapshot.candidate_skill_names)
                        agent_result["metadata_load_names"] = list(skill_snapshot.metadata_load_names)
                        agent_result["skill_read_names"] = list(skill_snapshot.read_names)
                        annotate_traced_span(
                            agent_span,
                            metadata=skill_snapshot.to_metadata(),
                            tags=skill_snapshot.to_tags(),
                        )
                    agent_result["visual_report_present"] = visual_report is not None
                    if visual_report is not None:
                        agent_result["visual_uncertainty_count"] = len(visual_report.uncertainties)
                    agent_result["duration_ms"] = int((time.monotonic() - start_time) * 1000)
                    end_traced_span(
                        agent_span,
                        outputs=agent_result,
                        error=agent_result.get("error"),
                    )
        finally:
            reset_skill_trace(skill_trace_token)
            reset_tool_context(context_token)
            logger.info(
                "Deep agent stream finished",
                extra={
                    "run_id": run_id,
                    "category": classification.category,
                    "status": "finished",
                    "duration_ms": int((time.monotonic() - start_time) * 1000),
                },
            )

    def _normalize_stream_item(self, item: Any) -> tuple[tuple[Any, ...], str, Any]:
        if isinstance(item, tuple) and len(item) == 3:
            namespace, mode, data = item
            return tuple(namespace) if isinstance(namespace, tuple) else (namespace,), mode, data
        if isinstance(item, tuple) and len(item) == 2:
            mode, data = item
            return tuple(), mode, data
        raise ValueError(f"Unexpected stream payload: {item!r}")

    def _parse_custom_event(self, data: Any) -> RuntimeStreamEvent | None:
        if not isinstance(data, dict):
            return None
        event_type = data.get("event_type")
        payload = data.get("payload")
        if isinstance(event_type, str) and isinstance(payload, dict):
            return RuntimeStreamEvent(event_type, payload)
        return None

    def _extract_structured_response(self, data: Any) -> dict[str, Any] | None:
        if isinstance(data, dict):
            if "structured_response" in data:
                structured = data["structured_response"]
                if hasattr(structured, "model_dump"):
                    return structured.model_dump(mode="json")
                if isinstance(structured, dict):
                    return structured
            for value in data.values():
                structured = self._extract_structured_response(value)
                if structured is not None:
                    return structured
        if isinstance(data, (list, tuple)):
            for item in data:
                structured = self._extract_structured_response(item)
                if structured is not None:
                    return structured
        return None

    def _extract_message_text(self, message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") in {"text", "text_delta"}:
                    parts.append(str(block.get("text") or ""))
            return "".join(parts)
        return ""

    def _build_visual_report(
        self,
        run_id: str,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        images: list[RunImage],
    ) -> VisualReport | None:
        if not images:
            return None

        with traced_span(
            self.settings,
            name="visual_evidence",
            inputs={
                "question": payload.question,
                "category": classification.category,
                "image_files": [image.file_name for image in images],
                "image_count": len(images),
            },
            tags=make_trace_tags(
                self.settings,
                "component:vision",
                f"category:{classification.category}",
            ),
            metadata={
                "run_id": run_id,
                "thread_id": run_id,
                "category": classification.category,
                "image_count": len(images),
                "image_names": [image.file_name for image in images],
            },
        ) as visual_span:
            report = self.visual_analyzer.analyze(payload, classification, images)
            end_traced_span(
                visual_span,
                outputs=report.model_dump(mode="json"),
                metadata={
                    "image_count": len(images),
                    "uncertainty_count": len(report.uncertainties),
                },
            )
        return report

    def _serialize_image_inputs(self, images: list[RunImage]) -> list[dict[str, Any]]:
        return [
            {
                "id": image.id,
                "file_name": image.file_name,
                "mime_type": image.mime_type,
                "size_bytes": image.size_bytes,
            }
            for image in images
        ]

    def _build_context_prompt(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        preflight_tradeoff: dict[str, Any],
        memory_snapshot: dict[str, str],
        images: list[RunImage],
        visual_report: VisualReport | None,
    ) -> str:
        context = {
            "question": payload.question,
            "budget": payload.budget,
            "deadline": payload.deadline,
            "location": payload.location,
            "links": payload.links,
            "image_inputs": self._serialize_image_inputs(images),
            "notes": payload.notes,
            "classification": classification.model_dump(mode="json"),
            "memory_snapshot": memory_snapshot,
            "visual_report": visual_report.model_dump(mode="json") if visual_report is not None else None,
            "context_hints": self._build_context_hints(payload, classification),
            "preflight_tradeoff": preflight_tradeoff,
        }
        return (
            "请帮我判断这件事到底做还是不做。必要时可以使用工具补充事实，但不要过度开工。"
            "你已经拿到一份本地预打分，请先基于它思考；只有它解决不了的问题，再考虑工具。"
            "如果证据还不完整，也要先给出尽力而为的判断。以下是上下文：\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

    def _build_context_hints_legacy(self, payload: RunCreateRequest, classification: ClassificationResult) -> dict[str, Any]:
        hints = {
            "question_length": len(payload.question.strip()),
            "has_links": bool(payload.links),
            "has_budget": bool(payload.budget),
            "has_deadline": bool(payload.deadline),
            "has_location": bool(payload.location),
            "missing_fields": classification.missing_fields,
            "suggested_tool_policy": [],
        }
        if payload.links:
            hints["suggested_tool_policy"].append("优先读取用户给的链接，而不是先做公开网页搜索。")
        if classification.category == "social":
            hints["suggested_tool_policy"].append("社交类问题默认不联网，只基于用户提供的背景判断。")
        if classification.category == "travel" and payload.location:
            hints["suggested_tool_policy"].append("如果需要补事实，优先地理编码和天气，不要先盲搜。")
        if not payload.links and classification.category in {"spending", "work_learning"}:
            hints["suggested_tool_policy"].append("如果现有上下文已经够用，就直接判断，不要为了联网而联网。")
        return hints

    def _build_context_hints(self, payload: RunCreateRequest, classification: ClassificationResult) -> dict[str, Any]:
        hints = {
            "question_length": len(payload.question.strip()),
            "has_links": bool(payload.links),
            "has_images": bool(payload.image_ids),
            "has_budget": bool(payload.budget),
            "has_deadline": bool(payload.deadline),
            "has_location": bool(payload.location),
            "missing_fields": classification.missing_fields,
            "suggested_tool_policy": [],
        }
        if payload.links:
            hints["suggested_tool_policy"].append("优先读取用户给的链接，而不是先做公开网页搜索。")
        if payload.image_ids:
            hints["suggested_tool_policy"].append("如果已经有图片摘要，先消化可见事实和不确定点，不要脑补图片里没出现的信息。")
        if classification.category == "social":
            hints["suggested_tool_policy"].append("社交类问题默认不联网，只基于用户提供的背景判断。")
        if classification.category == "travel" and payload.location:
            hints["suggested_tool_policy"].append("如果需要补事实，优先地理编码和天气，不要先盲搜。")
        if not payload.links and classification.category in {"spending", "work_learning"}:
            hints["suggested_tool_policy"].append("如果现有上下文已经够用，就直接判断，不要为了联网而联网。")
        return hints
