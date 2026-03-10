from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.prompts import build_main_prompt
from app.schemas import ClassificationResult, RunCreateRequest, RunVerdict
from app.tools import ToolFactory, reset_tool_context, set_tool_context


class AgentConfigurationError(RuntimeError):
    pass


@dataclass(slots=True)
class RuntimeStreamEvent:
    event_type: str
    payload: dict[str, Any]


class DecisionAgentRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tools = ToolFactory(settings).build()
        self._model: ChatOpenAI | None = None
        self._agents: dict[tuple[str, bool], Any] = {}

    def _require_model(self) -> ChatOpenAI:
        if self._model is not None:
            return self._model
        if not self.settings.dashscope_api_key:
            raise AgentConfigurationError("缺少 `DASHSCOPE_API_KEY`，请先在 `.env` 里填好再运行。")
        self._model = ChatOpenAI(
            api_key=self.settings.dashscope_api_key,
            base_url=self.settings.dashscope_base_url,
            model=self.settings.model_name,
            temperature=0.1,
            timeout=self.settings.model_timeout_seconds,
            max_retries=0,
            streaming=True,
        )
        return self._model

    def _get_agent(self, classification: ClassificationResult):
        key = (classification.category, classification.humor_allowed)
        agent = self._agents.get(key)
        if agent is None:
            agent = create_deep_agent(
                model=self._require_model(),
                tools=self.tools,
                system_prompt=build_main_prompt(classification.category, classification.humor_allowed),
                response_format=ToolStrategy(RunVerdict),
                backend=StateBackend,
                name=f"do-or-not-{classification.category}",
            )
            self._agents[key] = agent
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
        prompt = self._build_context_prompt(payload, classification)
        start_time = time.monotonic()
        token_buffer = ""
        context_token = set_tool_context(
            {
                "run_id": run_id,
                "category": classification.category,
                "links": payload.links,
            }
        )

        try:
            yield RuntimeStreamEvent(
                "agent_started",
                {
                    "category": classification.category,
                    "mode": "deep_agent",
                    "message": "主 Deep Agent 已接管，本轮会边查边吐进度。",
                },
            )

            if should_cancel():
                yield RuntimeStreamEvent("cancelled", {"message": "分析已停止。"})
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
                    yield RuntimeStreamEvent("cancelled", {"message": "用户已主动停止分析。"})
                    return

                if time.monotonic() - start_time > timeout_seconds:
                    if token_buffer.strip():
                        yield RuntimeStreamEvent("agent_token", {"text": token_buffer})
                        token_buffer = ""
                    yield RuntimeStreamEvent(
                        "timeout",
                        {"message": f"本轮分析超过 {timeout_seconds} 秒，已自动收手。"},
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
                        yield RuntimeStreamEvent("verdict_ready", verdict.model_dump(mode="json"))
                        return

            if token_buffer.strip():
                yield RuntimeStreamEvent("agent_token", {"text": token_buffer})
        finally:
            reset_tool_context(context_token)

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

    def _build_context_prompt(self, payload: RunCreateRequest, classification: ClassificationResult) -> str:
        context = {
            "question": payload.question,
            "budget": payload.budget,
            "deadline": payload.deadline,
            "location": payload.location,
            "links": payload.links,
            "notes": payload.notes,
            "classification": classification.model_dump(mode="json"),
        }
        return (
            "请帮我判断这件事到底做还是不做。必要时使用工具补充事实，但不要过度开工。"
            "如果证据不完整，也要先给出尽力而为的判断。以下是上下文：\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )
