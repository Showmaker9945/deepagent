from __future__ import annotations

import json
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.prompts import RESEARCHER_PROMPT, SKEPTIC_PROMPT, build_main_prompt
from app.schemas import (
    ClassificationResult,
    ResearchSummary,
    RunCreateRequest,
    RunVerdict,
    SkepticSummary,
)
from app.tools import ToolFactory


class AgentConfigurationError(RuntimeError):
    pass


class DecisionAgentRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tools = ToolFactory(settings).build()
        self._model: ChatOpenAI | None = None
        self._researcher_agent = None
        self._skeptic_agent = None
        self._decider_agents: dict[tuple[str, bool], Any] = {}

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
            timeout=35,
            max_retries=1,
        )
        return self._model

    def _memory_files(self, snapshot: dict[str, str]) -> dict[str, Any]:
        return {
            "/memories/profile.md": create_file_data(snapshot["profile_markdown"]),
            "/memories/regret_patterns.md": create_file_data(snapshot["regret_markdown"]),
        }

    def _get_researcher_agent(self):
        if self._researcher_agent is None:
            self._researcher_agent = create_deep_agent(
                model=self._require_model(),
                tools=self.tools,
                system_prompt=RESEARCHER_PROMPT,
                response_format=ToolStrategy(ResearchSummary),
                backend=StateBackend,
                name="do-or-not-researcher",
            )
        return self._researcher_agent

    def _get_skeptic_agent(self):
        if self._skeptic_agent is None:
            self._skeptic_agent = create_deep_agent(
                model=self._require_model(),
                tools=[],
                system_prompt=SKEPTIC_PROMPT,
                response_format=ToolStrategy(SkepticSummary),
                backend=StateBackend,
                name="do-or-not-skeptic",
            )
        return self._skeptic_agent

    def _get_decider_agent(self, classification: ClassificationResult):
        key = (classification.category, classification.humor_allowed)
        agent = self._decider_agents.get(key)
        if agent is None:
            researcher = CompiledSubAgent(
                name="researcher",
                description="当证据不够、需要查公开信息、解析链接、查天气或补事实时，交给这个代理。",
                runnable=self._get_researcher_agent(),
            )
            skeptic = CompiledSubAgent(
                name="skeptic",
                description="当需要找隐藏成本、机会成本、边界风险和更便宜替代方案时，交给这个代理。",
                runnable=self._get_skeptic_agent(),
            )
            agent = create_deep_agent(
                model=self._require_model(),
                tools=[],
                system_prompt=build_main_prompt(classification.category, classification.humor_allowed),
                subagents=[researcher, skeptic],
                response_format=ToolStrategy(RunVerdict),
                backend=StateBackend,
                name=f"do-or-not-decider-{classification.category}",
            )
            self._decider_agents[key] = agent
        return agent

    def run_researcher(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        snapshot: dict[str, str],
    ) -> ResearchSummary:
        prompt = self._build_context_prompt(payload, classification, snapshot)
        result = self._get_researcher_agent().invoke(
            {
                "messages": [{"role": "user", "content": prompt}],
                "files": self._memory_files(snapshot),
            }
        )
        return result["structured_response"]

    def run_skeptic(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        snapshot: dict[str, str],
        research: ResearchSummary,
    ) -> SkepticSummary:
        prompt = "\n\n".join(
            [
                self._build_context_prompt(payload, classification, snapshot),
                "Researcher 已经查到的内容：",
                research.model_dump_json(indent=2),
                "优先基于现有材料判断。除非有明显缺口，否则不要再额外调工具。",
            ]
        )
        result = self._get_skeptic_agent().invoke(
            {
                "messages": [{"role": "user", "content": prompt}],
                "files": self._memory_files(snapshot),
            }
        )
        return result["structured_response"]

    def run_decider(
        self,
        run_id: str,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        snapshot: dict[str, str],
        research: ResearchSummary,
        skeptic: SkepticSummary,
    ) -> RunVerdict:
        agent = self._get_decider_agent(classification)
        prompt = "\n\n".join(
            [
                self._build_context_prompt(payload, classification, snapshot),
                "Researcher 报告：",
                research.model_dump_json(indent=2),
                "Skeptic 报告：",
                skeptic.model_dump_json(indent=2),
                (
                    "优先基于已经拿到的 researcher / skeptic 结果直接给结论。"
                    "只有在证据明显不足、而且补一手信息能显著提升判断质量时，才调用 task 去找子代理。"
                ),
            ]
        )
        result = agent.invoke(
            {
                "messages": [{"role": "user", "content": prompt}],
                "files": self._memory_files(snapshot),
            },
            config={"configurable": {"thread_id": run_id}},
        )
        return result["structured_response"]

    def _build_context_prompt(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        snapshot: dict[str, str],
    ) -> str:
        context = {
            "question": payload.question,
            "budget": payload.budget,
            "deadline": payload.deadline,
            "location": payload.location,
            "links": payload.links,
            "notes": payload.notes,
            "classification": classification.model_dump(),
            "memory_files": [
                "/memories/profile.md",
                "/memories/regret_patterns.md",
            ],
            "memory_headlines": {
                "profile": snapshot["profile_markdown"][:300],
                "regrets": snapshot["regret_markdown"][:300],
            },
        }
        return (
            "请分析下面这个决策问题。\n"
            "你正在一个 Deep Agent 运行时里工作，必要时可以读 memory 文件或调子代理，但别过度开工。\n"
            "优先理解用户自然语言里已经给出的线索，包括预算、时间、地点、链接和犹豫点。\n"
            "如果信息已经足够，就直接判断；如果信息有限，也先给出尽力而为的答案。\n\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )
