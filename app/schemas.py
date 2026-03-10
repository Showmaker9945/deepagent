from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.text_utils import extract_urls


Category = Literal["spending", "travel", "work_learning", "social", "unsupported"]
RunStatus = Literal["queued", "running", "needs_clarification", "completed", "failed"]
EventType = Literal[
    "classified",
    "clarification_needed",
    "research_started",
    "skeptic_started",
    "verdict_ready",
    "error",
]


class RunCreateRequest(BaseModel):
    question: str = Field(min_length=3, max_length=3000)
    budget: str | None = None
    deadline: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)
    notes: str | None = None
    user_id: str | None = None

    @field_validator("links")
    @classmethod
    def normalize_links(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned[:5]

    @model_validator(mode="after")
    def enrich_links_from_freeform_text(self) -> "RunCreateRequest":
        merged: list[str] = []
        seen: set[str] = set()
        for candidate in [*self.links, *extract_urls(self.question), *extract_urls(self.notes or "")]:
            if candidate not in seen:
                merged.append(candidate)
                seen.add(candidate)
        self.links = merged[:5]
        return self


class ClarificationRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class FeedbackRequest(BaseModel):
    actual_action: str = Field(min_length=1, max_length=100)
    satisfaction_score: int = Field(ge=1, le=5)
    regret_score: int = Field(ge=1, le=5)
    note: str | None = Field(default=None, max_length=1000)


class ClassificationResult(BaseModel):
    category: Category
    reason: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    humor_allowed: bool = True


class ResearchSummary(BaseModel):
    summary: str
    supporting_evidence: list[str] = Field(default_factory=list)
    factual_observations: list[str] = Field(default_factory=list)
    relevant_links: list[str] = Field(default_factory=list)
    tool_notes: list[str] = Field(default_factory=list)


class SkepticSummary(BaseModel):
    summary: str
    risks: list[str] = Field(default_factory=list)
    reasons_not_to_do: list[str] = Field(default_factory=list)
    cheaper_or_lower_risk_options: list[str] = Field(default_factory=list)
    boundary_flags: list[str] = Field(default_factory=list)


class RunVerdict(BaseModel):
    category: Category
    verdict: str
    confidence: float = Field(ge=0, le=1)
    why_yes: list[str] = Field(default_factory=list)
    why_no: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    best_alternative: str
    recommended_next_step: str
    follow_up_question: str | None = None
    punchline: str | None = None


class RunEvent(BaseModel):
    id: int
    run_id: str
    event_type: EventType
    payload: dict[str, Any]
    created_at: datetime


class RunRecord(BaseModel):
    id: str
    user_id: str
    status: RunStatus
    question: str
    input_payload: dict[str, Any]
    category: Category | None = None
    clarification_count: int = 0
    clarification_question: str | None = None
    classification: ClassificationResult | None = None
    research_summary: ResearchSummary | None = None
    skeptic_summary: SkepticSummary | None = None
    verdict: RunVerdict | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RunEnvelope(BaseModel):
    run: RunRecord
    events: list[RunEvent] = Field(default_factory=list)


class PreferenceSnapshot(BaseModel):
    profile_markdown: str
    regret_markdown: str
