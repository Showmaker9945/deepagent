from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.memory import compile_memory_snapshot
from app.schemas import (
    ClassificationResult,
    PreferenceSnapshot,
    ResearchSummary,
    RunCreateRequest,
    RunEnvelope,
    RunEvent,
    RunRecord,
    RunSource,
    RunSourceType,
    RunStatus,
    RunVerdict,
    SkepticSummary,
)
from app.text_utils import extract_urls


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA foreign_keys=ON;")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    question TEXT NOT NULL,
                    input_payload TEXT NOT NULL,
                    category TEXT,
                    clarification_count INTEGER NOT NULL DEFAULT 0,
                    clarification_question TEXT,
                    classification_json TEXT,
                    research_json TEXT,
                    skeptic_json TEXT,
                    verdict_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS run_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT,
                    url TEXT,
                    snippet TEXT,
                    source_meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    actual_action TEXT NOT NULL,
                    satisfaction_score INTEGER NOT NULL,
                    regret_score INTEGER NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS user_preferences (
                    key TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    weight INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS regret_patterns (
                    key TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_runs_status_updated_at
                ON runs(status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_run_events_run_id_id
                ON run_events(run_id, id);

                CREATE INDEX IF NOT EXISTS idx_run_sources_run_id_id
                ON run_sources(run_id, id);

                CREATE INDEX IF NOT EXISTS idx_feedback_run_id_created_at
                ON feedback(run_id, created_at DESC);
                """
            )
            self._ensure_column(connection, "runs", "cancel_requested", "INTEGER NOT NULL DEFAULT 0")

    def _ensure_column(self, connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        columns = {row["name"] for row in rows}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def create_run(self, payload: RunCreateRequest, user_id: str) -> str:
        run_id = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, user_id, status, question, input_payload, cancel_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    user_id,
                    "queued",
                    payload.question,
                    payload.model_dump_json(),
                    0,
                    now,
                    now,
                ),
            )
        return run_id

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def list_events(self, run_id: str, after_id: int = 0) -> list[RunEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (run_id, after_id),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_sources(self, run_id: str) -> list[RunSource]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM run_sources
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_source(row) for row in rows]

    def get_run_envelope(self, run_id: str) -> RunEnvelope | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return RunEnvelope(run=run, events=self.list_events(run_id), sources=self.list_sources(run_id))

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO run_events (run_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, event_type, json.dumps(payload, ensure_ascii=False), utcnow()),
            )

    def add_source(
        self,
        run_id: str,
        source_type: RunSourceType,
        *,
        title: str | None = None,
        url: str | None = None,
        snippet: str | None = None,
        source_meta: dict[str, Any] | None = None,
    ) -> int:
        safe_meta = source_meta or {}
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM run_sources
                WHERE run_id = ?
                  AND source_type = ?
                  AND COALESCE(title, '') = ?
                  AND COALESCE(url, '') = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (run_id, source_type, title or "", url or ""),
            ).fetchone()
            if existing:
                if snippet or safe_meta:
                    connection.execute(
                        """
                        UPDATE run_sources
                        SET snippet = COALESCE(?, snippet),
                            source_meta_json = ?,
                            created_at = created_at
                        WHERE id = ?
                        """,
                        (snippet, json.dumps(safe_meta, ensure_ascii=False), existing["id"]),
                    )
                return int(existing["id"])

            cursor = connection.execute(
                """
                INSERT INTO run_sources (run_id, source_type, title, url, snippet, source_meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source_type,
                    title,
                    url,
                    snippet,
                    json.dumps(safe_meta, ensure_ascii=False),
                    utcnow(),
                ),
            )
            lastrowid = cursor.lastrowid
            if lastrowid is None:
                raise RuntimeError("Failed to insert run source.")
            return int(lastrowid)

    def request_cancel(self, run_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET cancel_requested = 1, updated_at = ?
                WHERE id = ?
                  AND status IN ('queued', 'running', 'needs_clarification')
                """,
                (utcnow(), run_id),
            )
            return cursor.rowcount > 0

    def is_cancel_requested(self, run_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return bool(row["cancel_requested"]) if row else False

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        category: str | None = None,
        clarification_question: str | None = None,
        clarification_count: int | None = None,
        cancel_requested: bool | None = None,
        error_message: str | None = None,
        classification: ClassificationResult | None = None,
        research_summary: ResearchSummary | None = None,
        skeptic_summary: SkepticSummary | None = None,
        verdict: RunVerdict | None = None,
        input_payload: RunCreateRequest | None = None,
    ) -> None:
        updates: dict[str, Any] = {
            "status": status,
            "updated_at": utcnow(),
        }
        if category is not None:
            updates["category"] = category
        if clarification_question is not None:
            updates["clarification_question"] = clarification_question
        if clarification_count is not None:
            updates["clarification_count"] = clarification_count
        if cancel_requested is not None:
            updates["cancel_requested"] = 1 if cancel_requested else 0
        if error_message is not None:
            updates["error_message"] = error_message
        if classification is not None:
            updates["classification_json"] = classification.model_dump_json()
        if research_summary is not None:
            updates["research_json"] = research_summary.model_dump_json()
        if skeptic_summary is not None:
            updates["skeptic_json"] = skeptic_summary.model_dump_json()
        if verdict is not None:
            updates["verdict_json"] = verdict.model_dump_json()
        if input_payload is not None:
            updates["input_payload"] = input_payload.model_dump_json()
            updates["question"] = input_payload.question

        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [run_id]
        with self.connect() as connection:
            connection.execute(f"UPDATE runs SET {assignments} WHERE id = ?", values)

    def add_clarification_answer(self, run_id: str, answer: str) -> RunRecord | None:
        run = self.get_run(run_id)
        if not run:
            return None
        payload = RunCreateRequest.model_validate(run.input_payload)
        discovered_links = extract_urls(answer)
        updated_payload = RunCreateRequest(
            question=payload.question,
            budget=payload.budget,
            deadline=payload.deadline,
            location=payload.location,
            links=[*payload.links, *discovered_links],
            notes="\n".join(part for part in [payload.notes or "", f"Clarification: {answer}"] if part).strip(),
            user_id=payload.user_id,
        )
        self.update_status(
            run_id,
            "queued",
            clarification_count=run.clarification_count + 1,
            clarification_question="",
            cancel_requested=False,
            error_message="",
            input_payload=updated_payload,
        )
        return self.get_run(run_id)

    def store_feedback(
        self,
        run_id: str,
        category: str,
        actual_action: str,
        satisfaction_score: int,
        regret_score: int,
        note: str | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO feedback (
                    run_id, category, actual_action, satisfaction_score, regret_score, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, category, actual_action, satisfaction_score, regret_score, note, utcnow()),
            )

    def upsert_preference(self, key: str, summary: str, delta: int = 1) -> None:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT weight FROM user_preferences WHERE key = ?",
                (key,),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE user_preferences
                    SET summary = ?, weight = ?, updated_at = ?
                    WHERE key = ?
                    """,
                    (summary, existing["weight"] + delta, utcnow(), key),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO user_preferences (key, summary, weight, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key, summary, max(delta, 1), utcnow()),
                )

    def upsert_regret_pattern(self, key: str, summary: str, delta: int = 1) -> None:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT count FROM regret_patterns WHERE key = ?",
                (key,),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE regret_patterns
                    SET summary = ?, count = ?, updated_at = ?
                    WHERE key = ?
                    """,
                    (summary, existing["count"] + delta, utcnow(), key),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO regret_patterns (key, summary, count, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key, summary, max(delta, 1), utcnow()),
                )

    def get_preferences(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT key, summary, weight, updated_at FROM user_preferences ORDER BY weight DESC, updated_at DESC LIMIT 10"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_regret_patterns(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT key, summary, count, updated_at FROM regret_patterns ORDER BY count DESC, updated_at DESC LIMIT 10"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_memory_snapshot(self) -> PreferenceSnapshot:
        return compile_memory_snapshot(self.get_preferences(), self.get_regret_patterns())

    def check_ready(self) -> tuple[bool, str | None]:
        try:
            with self.connect() as connection:
                connection.execute("SELECT 1").fetchone()
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            return True, None
        except sqlite3.Error as exc:
            return False, str(exc)

    def _row_to_event(self, row: sqlite3.Row) -> RunEvent:
        return RunEvent(
            id=row["id"],
            run_id=row["run_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_source(self, row: sqlite3.Row) -> RunSource:
        return RunSource(
            id=row["id"],
            run_id=row["run_id"],
            source_type=row["source_type"],
            title=row["title"],
            url=row["url"],
            snippet=row["snippet"],
            source_meta=json.loads(row["source_meta_json"]) if row["source_meta_json"] else {},
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_run(self, row: sqlite3.Row) -> RunRecord:
        classification_json = row["classification_json"]
        research_json = row["research_json"]
        skeptic_json = row["skeptic_json"]
        verdict_json = row["verdict_json"]
        return RunRecord(
            id=row["id"],
            user_id=row["user_id"],
            status=row["status"],
            question=row["question"],
            input_payload=json.loads(row["input_payload"]),
            category=row["category"],
            clarification_count=row["clarification_count"],
            clarification_question=row["clarification_question"] or None,
            cancel_requested=bool(row["cancel_requested"]) if "cancel_requested" in row.keys() else False,
            classification=ClassificationResult.model_validate_json(classification_json) if classification_json else None,
            research_summary=ResearchSummary.model_validate_json(research_json) if research_json else None,
            skeptic_summary=SkepticSummary.model_validate_json(skeptic_json) if skeptic_json else None,
            verdict=RunVerdict.model_validate_json(verdict_json) if verdict_json else None,
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
