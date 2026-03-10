from __future__ import annotations

from app.agents import AgentConfigurationError, DecisionAgentRuntime, RuntimeStreamEvent
from app.classifier import classify_request
from app.config import Settings
from app.schemas import FeedbackRequest, RunCreateRequest, RunVerdict
from app.storage import Storage


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out"}


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
        if not run or run.status in TERMINAL_STATUSES:
            return
        if run.cancel_requested:
            self._mark_cancelled(run_id, "分析在开始前就被你叫停了。")
            return

        payload = RunCreateRequest.model_validate(run.input_payload)
        classification = classify_request(payload)
        self.storage.update_status(
            run_id,
            "running",
            category=classification.category,
            classification=classification,
            cancel_requested=False,
            error_message="",
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
                cancel_requested=False,
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
                verdict="先别让模型替你硬猜",
                confidence=0.94,
                why_yes=[],
                why_no=[
                    "这属于高风险问题，靠通用模型拍板很容易把谨慎感搞丢。",
                    "真正重要的细节，还是要让合格专业人士来判断。",
                ],
                top_risks=["把不确定的建议误当成专业意见。"],
                best_alternative="先整理事实、症状、限制条件或证据，再去问对应的专业人士。",
                recommended_next_step="把你最需要确认的 3 个具体问题写下来，带着去咨询专业人士。",
                follow_up_question="你真正需要专业人士回答的那一句话，具体是什么？",
                punchline=None,
            )
            self.storage.update_status(
                run_id,
                "completed",
                verdict=verdict,
                cancel_requested=False,
                error_message="",
            )
            self.storage.append_event(run_id, "verdict_ready", verdict.model_dump(mode="json"))
            return

        try:
            terminal_reached = False
            for event in self.runtime.run_streaming(
                run_id,
                payload,
                classification,
                timeout_seconds=self.settings.run_timeout_seconds,
                should_cancel=lambda: self.storage.is_cancel_requested(run_id),
            ):
                if self._handle_runtime_event(run_id, event):
                    terminal_reached = True
                    break

            if not terminal_reached:
                if self.storage.is_cancel_requested(run_id):
                    self._mark_cancelled(run_id, "分析被你手动停下来了。")
                else:
                    self.storage.update_status(
                        run_id,
                        "failed",
                        cancel_requested=False,
                        error_message="Deep Agent 没有返回最终结论。",
                    )
                    self.storage.append_event(
                        run_id,
                        "error",
                        {"message": "Deep Agent 没有返回最终结论。"},
                    )
        except AgentConfigurationError as exc:
            self.storage.update_status(run_id, "failed", cancel_requested=False, error_message=str(exc))
            self.storage.append_event(run_id, "error", {"message": str(exc)})
        except Exception as exc:  # pragma: no cover
            self.storage.update_status(run_id, "failed", cancel_requested=False, error_message=str(exc))
            self.storage.append_event(run_id, "error", {"message": str(exc)})

    def _handle_runtime_event(self, run_id: str, event: RuntimeStreamEvent) -> bool:
        if event.event_type == "source_captured":
            source_id = self.storage.add_source(
                run_id,
                event.payload["source_type"],
                title=event.payload.get("title"),
                url=event.payload.get("url"),
                snippet=event.payload.get("snippet"),
                source_meta=event.payload.get("source_meta") or {},
            )
            self.storage.append_event(run_id, "source_captured", {**event.payload, "source_id": source_id})
            return False

        if event.event_type == "verdict_ready":
            verdict = RunVerdict.model_validate(event.payload)
            self.storage.update_status(
                run_id,
                "completed",
                verdict=verdict,
                cancel_requested=False,
                error_message="",
            )
            self.storage.append_event(run_id, "verdict_ready", verdict.model_dump(mode="json"))
            return True

        if event.event_type == "cancelled":
            self._mark_cancelled(run_id, event.payload.get("message") or "分析已取消。")
            return True

        if event.event_type == "timeout":
            message = event.payload.get("message") or "分析超时。"
            self.storage.update_status(
                run_id,
                "timed_out",
                cancel_requested=False,
                error_message=message,
            )
            self.storage.append_event(run_id, "timeout", {"message": message})
            return True

        if event.event_type == "error":
            message = event.payload.get("message") or "运行出错。"
            self.storage.update_status(
                run_id,
                "failed",
                cancel_requested=False,
                error_message=message,
            )
            self.storage.append_event(run_id, "error", {"message": message})
            return True

        self.storage.append_event(run_id, event.event_type, event.payload)
        return False

    def _mark_cancelled(self, run_id: str, message: str) -> None:
        self.storage.update_status(
            run_id,
            "cancelled",
            cancel_requested=False,
            error_message=message,
        )
        self.storage.append_event(run_id, "cancelled", {"message": message})

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
                f"你在 {category} 类决定里，通常更适合在信息够用时稳一点出手，而不是热血开团。",
                delta=1,
            )
        if feedback.regret_score >= 4:
            self.storage.upsert_regret_pattern(
                f"{category}:regret",
                f"你在 {category} 类问题里，经常会后悔那些信息太薄、心情太急时做的决定。",
                delta=1,
            )
