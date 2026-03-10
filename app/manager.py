from __future__ import annotations

from app.agents import AgentConfigurationError, DecisionAgentRuntime
from app.classifier import classify_request
from app.config import Settings
from app.memory import compile_memory_snapshot
from app.schemas import FeedbackRequest, RunCreateRequest, RunVerdict
from app.storage import Storage


class RunManager:
    def __init__(self, settings: Settings, storage: Storage, runtime: DecisionAgentRuntime) -> None:
        self.settings = settings
        self.storage = storage
        self.runtime = runtime

    def start_run(self, payload: RunCreateRequest) -> str:
        user_id = payload.user_id or self.settings.default_user_id
        return self.storage.create_run(payload, user_id)

    def process_run(self, run_id: str) -> None:
        run = self.storage.get_run(run_id)
        if not run:
            return

        payload = RunCreateRequest.model_validate(run.input_payload)
        classification = classify_request(payload)
        self.storage.update_status(
            run_id,
            "running",
            category=classification.category,
            classification=classification,
            error_message=None,
        )
        self.storage.append_event(
            run_id,
            "classified",
            {
                "category": classification.category,
                "reason": classification.reason,
            },
        )

        if classification.needs_clarification and run.clarification_count < 2:
            self.storage.update_status(
                run_id,
                "needs_clarification",
                clarification_question=classification.clarification_question,
                classification=classification,
            )
            self.storage.append_event(
                run_id,
                "clarification_needed",
                {"question": classification.clarification_question},
            )
            return

        if classification.category == "unsupported":
            verdict = RunVerdict(
                category="unsupported",
                verdict="slow down",
                confidence=0.92,
                why_yes=[],
                why_no=[
                    "This looks like a high-stakes topic where guessing would be reckless.",
                    "A qualified professional can see details an LLM should not pretend to diagnose.",
                ],
                top_risks=["False confidence in a risky situation."],
                best_alternative="Use this app to organize your questions, then ask a qualified professional.",
                recommended_next_step="Write down the concrete facts, symptoms, or constraints you need to discuss with a professional.",
                follow_up_question="What exact question do you need to ask the professional?",
                punchline=None,
            )
            self.storage.update_status(run_id, "completed", verdict=verdict)
            self.storage.append_event(run_id, "verdict_ready", verdict.model_dump())
            return

        snapshot_model = compile_memory_snapshot(
            self.storage.get_preferences(),
            self.storage.get_regret_patterns(),
        )
        snapshot = snapshot_model.model_dump()

        try:
            self.storage.append_event(run_id, "research_started", {"agent": "researcher"})
            research = self.runtime.run_researcher(payload, classification, snapshot)
            self.storage.update_status(run_id, "running", research_summary=research)

            self.storage.append_event(run_id, "skeptic_started", {"agent": "skeptic"})
            skeptic = self.runtime.run_skeptic(payload, classification, snapshot, research)
            self.storage.update_status(run_id, "running", skeptic_summary=skeptic)

            verdict = self.runtime.run_decider(run_id, payload, classification, snapshot, research, skeptic)
            self.storage.update_status(run_id, "completed", verdict=verdict)
            self.storage.append_event(run_id, "verdict_ready", verdict.model_dump())
        except AgentConfigurationError as exc:
            self.storage.update_status(run_id, "failed", error_message=str(exc))
            self.storage.append_event(run_id, "error", {"message": str(exc)})
        except Exception as exc:  # pragma: no cover
            self.storage.update_status(run_id, "failed", error_message=str(exc))
            self.storage.append_event(run_id, "error", {"message": str(exc)})

    def submit_clarification(self, run_id: str, answer: str) -> bool:
        updated = self.storage.add_clarification_answer(run_id, answer)
        return updated is not None

    def submit_feedback(self, run_id: str, feedback: FeedbackRequest) -> None:
        run = self.storage.get_run(run_id)
        if not run or not run.category:
            raise ValueError("Run not found or missing category.")
        self.storage.store_feedback(
            run_id,
            run.category,
            feedback.actual_action,
            feedback.satisfaction_score,
            feedback.regret_score,
            feedback.note,
        )
        self._update_memory_from_feedback(run.category, feedback)

    def _update_memory_from_feedback(self, category: str, feedback: FeedbackRequest) -> None:
        if feedback.satisfaction_score >= 4 and feedback.regret_score <= 2:
            self.storage.upsert_preference(
                f"{category}:positive",
                f"You usually feel good about {category} decisions when you act with enough context instead of impulse.",
                delta=1,
            )
        if feedback.regret_score >= 4:
            self.storage.upsert_regret_pattern(
                f"{category}:regret",
                f"You often regret rushed {category} calls when the context feels thin or the vibe feels off.",
                delta=1,
            )
