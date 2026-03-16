from __future__ import annotations

import logging
import time

from app.agents import AgentConfigurationError, DecisionAgentRuntime, RuntimeStreamEvent
from app.classifier import classify_request
from app.config import Settings
from app.fallbacks import build_fallback_verdict
from app.schemas import ClassificationResult, FeedbackRequest, RunCreateRequest, RunVerdict
from app.scoring import score_tradeoff
from app.storage import Storage

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out"}
logger = logging.getLogger(__name__)


class RunManager:
    def __init__(self, settings: Settings, storage: Storage, runtime: DecisionAgentRuntime) -> None:
        self.settings = settings
        self.storage = storage
        self.runtime = runtime

    def start_run(self, payload: RunCreateRequest) -> str:
        user_id = payload.user_id or self.settings.default_user_id
        run_id = self.storage.create_run(payload, user_id)
        logger.info("Queued run", extra={"run_id": run_id, "status": "queued"})
        return run_id

    def process_run(self, run_id: str) -> None:
        run = self.storage.get_run(run_id)
        if not run or run.status in TERMINAL_STATUSES:
            return

        started_at = time.monotonic()
        logger.info("Processing run", extra={"run_id": run_id, "status": run.status})

        try:
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
            logger.info(
                "Classified run",
                extra={
                    "run_id": run_id,
                    "category": classification.category,
                    "status": "classified",
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
                logger.info(
                    "Run needs clarification",
                    extra={
                        "run_id": run_id,
                        "category": classification.category,
                        "status": "needs_clarification",
                    },
                )
                return

            if classification.category == "unsupported":
                verdict = RunVerdict(
                    category="unsupported",
                    verdict="先别让模型替你硬猜。",
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
                logger.info(
                    "Completed unsupported run without agent",
                    extra={
                        "run_id": run_id,
                        "category": classification.category,
                        "status": "completed",
                    },
                )
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
                        self._complete_with_fallback(
                            run_id,
                            payload,
                            classification,
                            reason="主 Deep Agent 没有稳定产出结构化结论，已切到本地保守兜底。",
                        )
            except AgentConfigurationError as exc:
                logger.exception(
                    "Run failed because model configuration is missing",
                    extra={
                        "run_id": run_id,
                        "category": classification.category,
                        "status": "failed",
                    },
                )
                self.storage.update_status(run_id, "failed", cancel_requested=False, error_message=str(exc))
                self.storage.append_event(run_id, "error", {"message": str(exc)})
            except Exception as exc:  # pragma: no cover
                logger.exception(
                    "Run failed inside deep agent execution",
                    extra={
                        "run_id": run_id,
                        "category": classification.category,
                        "status": "fallback",
                    },
                )
                self._complete_with_fallback(
                    run_id,
                    payload,
                    classification,
                    reason=f"主 Deep Agent 运行时翻车了，已切到本地保守兜底：{exc}",
                    emit_error_event=True,
                )
        finally:
            final_run = self.storage.get_run(run_id)
            logger.info(
                "Finished processing run",
                extra={
                    "run_id": run_id,
                    "category": final_run.category if final_run else None,
                    "status": final_run.status if final_run else "missing",
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )

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
            logger.info("Persisted verdict", extra={"run_id": run_id, "status": "completed"})
            return True

        if event.event_type == "cancelled":
            self._mark_cancelled(run_id, event.payload.get("message") or "分析已取消。")
            return True

        if event.event_type == "timeout":
            message = event.payload.get("message") or "分析超时。"
            run = self.storage.get_run(run_id)
            if run:
                payload = RunCreateRequest.model_validate(run.input_payload)
                classification = run.classification or classify_request(payload)
                self._complete_with_fallback(
                    run_id,
                    payload,
                    classification,
                    reason=f"{message} 已切到本地保守兜底。",
                    append_verdict_event=False,
                )
            self.storage.append_event(run_id, "timeout", {"message": message})
            logger.warning("Run timed out", extra={"run_id": run_id, "status": "timeout"})
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
            logger.error("Run emitted error event", extra={"run_id": run_id, "status": "failed"})
            return True

        self.storage.append_event(run_id, event.event_type, event.payload)
        return False

    def _complete_with_fallback(
        self,
        run_id: str,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        *,
        reason: str,
        emit_error_event: bool = False,
        append_verdict_event: bool = True,
    ) -> None:
        score_result = score_tradeoff(classification.category, payload)
        verdict = build_fallback_verdict(classification.category, payload, classification, score_result)
        self.storage.add_source(
            run_id,
            "tool_note",
            title="本地保守兜底",
            snippet=reason,
            source_meta=score_result,
        )
        self.storage.update_status(
            run_id,
            "completed",
            verdict=verdict,
            cancel_requested=False,
            error_message=reason if emit_error_event else "",
        )
        if emit_error_event:
            self.storage.append_event(run_id, "error", {"message": reason})
        elif append_verdict_event:
            self.storage.append_event(run_id, "verdict_ready", verdict.model_dump(mode="json"))
        logger.warning(
            "Completed run with fallback verdict",
            extra={
                "run_id": run_id,
                "category": classification.category,
                "status": "fallback",
            },
        )

    def _mark_cancelled(self, run_id: str, message: str) -> None:
        self.storage.update_status(
            run_id,
            "cancelled",
            cancel_requested=False,
            error_message=message,
        )
        self.storage.append_event(run_id, "cancelled", {"message": message})
        logger.info("Cancelled run", extra={"run_id": run_id, "status": "cancelled"})

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
        logger.info(
            "Stored run feedback",
            extra={
                "run_id": run_id,
                "category": run.category,
                "status": "feedback_recorded",
            },
        )

    def _update_memory_from_feedback(self, category: str, feedback: FeedbackRequest) -> None:
        if feedback.satisfaction_score >= 4 and feedback.regret_score <= 2:
            self.storage.upsert_preference(
                f"{category}:positive",
                f"你在 {category} 类决策里，通常更适合在信息够用时稳一点出手，而不是热血开团。",
                delta=1,
            )
        if feedback.regret_score >= 4:
            self.storage.upsert_regret_pattern(
                f"{category}:regret",
                f"你在 {category} 类问题里，经常会后悔那些信息太薄、心情太急时做的决定。",
                delta=1,
            )
