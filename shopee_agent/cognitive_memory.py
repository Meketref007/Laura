from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import DECISION_OUTCOMES, LONG_TERM_MEMORY_NOTES, MEMORY_REFLECTIONS

from .decision_memory import DecisionOutcome, MemoryLayer


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


class _SQLiteOutcomeLayer:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def remember_outcome(self, outcome: DecisionOutcome) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_outcomes (
                    decision_id, rule_id, executed_at, outcome_type,
                    impact_realized, margin_change, revenue_change, satisfaction_change,
                    reversals, feedback, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.decision_id,
                    outcome.rule_id,
                    outcome.executed_at.isoformat() if outcome.executed_at else None,
                    outcome.outcome_type,
                    outcome.impact_realized,
                    outcome.margin_change,
                    outcome.revenue_change,
                    outcome.satisfaction_change,
                    outcome.reversals,
                    outcome.feedback,
                    json.dumps(outcome.metadata, ensure_ascii=False),
                ),
            )
            connection.commit()

    def list_outcomes(self, limit: int = 100) -> list[DecisionOutcome]:
        outcomes: list[DecisionOutcome] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT decision_id, rule_id, executed_at, outcome_type, impact_realized, margin_change, revenue_change, satisfaction_change, reversals, feedback, metadata_json FROM memory_outcomes ORDER BY rowid ASC LIMIT ?",
                (limit,),
            ).fetchall()

        for row in rows:
            executed_at = None
            if row["executed_at"]:
                try:
                    executed_at = datetime.fromisoformat(str(row["executed_at"]))
                except Exception:
                    executed_at = None
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except Exception:
                metadata = {}
            outcomes.append(
                DecisionOutcome(
                    decision_id=str(row["decision_id"]),
                    rule_id=str(row["rule_id"]),
                    executed_at=executed_at,
                    outcome_type=str(row["outcome_type"]),
                    impact_realized=row["impact_realized"],
                    margin_change=row["margin_change"],
                    revenue_change=row["revenue_change"],
                    satisfaction_change=row["satisfaction_change"],
                    reversals=int(row["reversals"] or 0),
                    feedback=row["feedback"],
                    metadata=dict(metadata),
                )
            )
        return outcomes

    def get_rule_effectiveness(self, rule_id: str) -> float:
        relevant = [outcome for outcome in self.list_outcomes(limit=5000) if outcome.rule_id == rule_id]
        if not relevant:
            return 0.5

        score_sum = 0.0
        for outcome in relevant:
            if outcome.outcome_type == "success":
                score_sum += 1.0
            elif outcome.outcome_type == "partial":
                score_sum += 0.5
        return score_sum / len(relevant)

    def rank_similar_decisions(self, current_signal: dict[str, Any], limit: int = 10) -> list[DecisionOutcome]:
        metric = current_signal.get("metric") or current_signal.get("type")
        results: list[tuple[int, DecisionOutcome]] = []
        for outcome in self.list_outcomes(limit=5000):
            score = 0
            if metric and outcome.metadata.get("metric") == metric:
                score += 1
            if outcome.rule_id and current_signal.get("rule_id") and outcome.rule_id == current_signal.get("rule_id"):
                score += 2
            if score > 0:
                results.append((score, outcome))
        results.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in results[:limit]]

    def predict_outcome_for_rule(self, rule_id: str) -> float:
        relevant = [outcome for outcome in self.list_outcomes(limit=5000) if outcome.rule_id == rule_id and outcome.impact_realized is not None]
        if not relevant:
            return 0.0
        values = [float(outcome.impact_realized) for outcome in relevant if outcome.impact_realized is not None]
        return sum(values) / len(values) if values else 0.0


@dataclass
class MemoryNote:
    note_id: str
    kind: str
    title: str
    summary: str = ""
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat() if self.created_at else None
        return payload


class LongTermMemory:
    """Persistent memory over outcomes, notes and operational reflections."""

    def __init__(
        self,
        outcomes_path: str = str(DECISION_OUTCOMES),
        notes_path: str = str(LONG_TERM_MEMORY_NOTES),
        database_path: str | None = None,
    ):
        self.database_path = self._resolve_database_path(outcomes_path, notes_path, database_path)
        self._sqlite_mode = self.database_path is not None
        self.outcomes = _SQLiteOutcomeLayer(self.database_path) if self._sqlite_mode else MemoryLayer(path=outcomes_path)
        self.notes_path = Path(notes_path)
        if not self._sqlite_mode:
            self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()
        self._notes: list[MemoryNote] = []
        self._load_notes()

    def _resolve_database_path(
        self,
        outcomes_path: str,
        notes_path: str,
        database_path: str | None,
    ) -> Path | None:
        if database_path:
            return Path(database_path)

        for candidate in (outcomes_path, notes_path):
            suffix = Path(candidate).suffix.lower()
            if suffix in {".db", ".sqlite", ".sqlite3"}:
                return Path(candidate)

        return None

    def _connect(self) -> sqlite3.Connection:
        assert self.database_path is not None
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_sqlite(self) -> None:
        assert self.database_path is not None
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_outcomes (
                    decision_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    executed_at TEXT,
                    outcome_type TEXT NOT NULL,
                    impact_realized REAL,
                    margin_change REAL,
                    revenue_change REAL,
                    satisfaction_change REAL,
                    reversals INTEGER DEFAULT 0,
                    feedback TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_notes (
                    note_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    created_at TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()

    def _load_sqlite_notes(self) -> list[MemoryNote]:
        assert self.database_path is not None
        notes: list[MemoryNote] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT note_id, kind, title, summary, created_at, metadata_json FROM memory_notes ORDER BY created_at_utc ASC"
            ).fetchall()
        for row in rows:
            created_at = None
            created_at_text = row["created_at"]
            if created_at_text:
                try:
                    created_at = datetime.fromisoformat(str(created_at_text))
                except Exception:
                    created_at = None
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except Exception:
                metadata = {}
            notes.append(
                MemoryNote(
                    note_id=str(row["note_id"]),
                    kind=str(row["kind"]),
                    title=str(row["title"]),
                    summary=str(row["summary"] or ""),
                    created_at=created_at,
                    metadata=dict(metadata),
                )
            )
        return notes

    def _load_sqlite_outcomes(self, limit: int = 100) -> list[DecisionOutcome]:
        assert self.database_path is not None
        outcomes: list[DecisionOutcome] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT decision_id, rule_id, executed_at, outcome_type, impact_realized, margin_change, revenue_change, satisfaction_change, reversals, feedback, metadata_json FROM memory_outcomes ORDER BY rowid ASC LIMIT ?",
                (limit,),
            ).fetchall()
        for row in rows:
            executed_at = None
            if row["executed_at"]:
                try:
                    executed_at = datetime.fromisoformat(str(row["executed_at"]))
                except Exception:
                    executed_at = None
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except Exception:
                metadata = {}
            outcomes.append(
                DecisionOutcome(
                    decision_id=str(row["decision_id"]),
                    rule_id=str(row["rule_id"]),
                    executed_at=executed_at,
                    outcome_type=str(row["outcome_type"]),
                    impact_realized=row["impact_realized"],
                    margin_change=row["margin_change"],
                    revenue_change=row["revenue_change"],
                    satisfaction_change=row["satisfaction_change"],
                    reversals=int(row["reversals"] or 0),
                    feedback=row["feedback"],
                    metadata=dict(metadata),
                )
            )
        return outcomes

    def _load_notes(self) -> None:
        if self._sqlite_mode:
            self._notes = self._load_sqlite_notes()
            return

        if not self.notes_path.exists():
            return

        try:
            with self.notes_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    try:
                        obj = json.loads(raw_line)
                        created_at = None
                        if obj.get("created_at"):
                            try:
                                created_at = datetime.fromisoformat(str(obj["created_at"]))
                            except Exception:
                                created_at = None

                        self._notes.append(
                            MemoryNote(
                                note_id=str(obj.get("note_id", "")),
                                kind=str(obj.get("kind", "note")),
                                title=str(obj.get("title", "")),
                                summary=str(obj.get("summary", "")),
                                created_at=created_at,
                                metadata=dict(obj.get("metadata", {})),
                            )
                        )
                    except Exception:
                        continue
        except Exception:
            self._notes = []

    def remember_outcome(self, outcome: DecisionOutcome) -> None:
        if self._sqlite_mode:
            assert self.database_path is not None
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO memory_outcomes (
                        decision_id, rule_id, executed_at, outcome_type,
                        impact_realized, margin_change, revenue_change, satisfaction_change,
                        reversals, feedback, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outcome.decision_id,
                        outcome.rule_id,
                        outcome.executed_at.isoformat() if outcome.executed_at else None,
                        outcome.outcome_type,
                        outcome.impact_realized,
                        outcome.margin_change,
                        outcome.revenue_change,
                        outcome.satisfaction_change,
                        outcome.reversals,
                        outcome.feedback,
                        json.dumps(outcome.metadata, ensure_ascii=False),
                    ),
                )
                connection.commit()
            return

        self.outcomes.remember_outcome(outcome)

    def remember_note(
        self,
        kind: str,
        title: str,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryNote:
        note = MemoryNote(
            note_id=f"note_{len(self._notes) + 1:06d}",
            kind=kind,
            title=title,
            summary=summary,
            created_at=_utc_now(),
            metadata=dict(metadata or {}),
        )
        if self._sqlite_mode:
            assert self.database_path is not None
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO memory_notes (note_id, kind, title, summary, created_at, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note.note_id,
                        note.kind,
                        note.title,
                        note.summary,
                        note.created_at.isoformat() if note.created_at else None,
                        json.dumps(note.metadata, ensure_ascii=False),
                    ),
                )
                connection.commit()
        else:
            with self.notes_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(note.to_dict(), ensure_ascii=False) + "\n")
        self._notes.append(note)
        return note

    def recent_outcomes(self, limit: int = 100) -> list[DecisionOutcome]:
        if self._sqlite_mode:
            return self._load_sqlite_outcomes(limit=limit)
        return self.outcomes.list_outcomes(limit=limit)

    def recent_notes(self, limit: int = 50) -> list[MemoryNote]:
        if self._sqlite_mode:
            return self._load_sqlite_notes()[-limit:]
        return list(self._notes[-limit:])

    def overview(self, limit: int = 10) -> dict[str, Any]:
        outcomes = self.recent_outcomes(limit=500)
        notes = self.recent_notes(limit=limit)

        outcome_counts = Counter(outcome.outcome_type for outcome in outcomes)
        rule_counts = Counter(outcome.rule_id for outcome in outcomes)
        positive_impacts = [o.impact_realized for o in outcomes if o.impact_realized is not None and o.impact_realized > 0]
        negative_impacts = [o.impact_realized for o in outcomes if o.impact_realized is not None and o.impact_realized < 0]

        avg_positive = sum(positive_impacts) / len(positive_impacts) if positive_impacts else 0.0
        avg_negative = sum(negative_impacts) / len(negative_impacts) if negative_impacts else 0.0
        success_rate = 0.5
        if outcomes:
            success_like = sum(1 for outcome in outcomes if outcome.outcome_type in {"success", "partial"})
            success_rate = success_like / len(outcomes)

        return {
            "outcome_count": len(outcomes),
            "note_count": len(self._notes),
            "outcome_counts": dict(outcome_counts),
            "success_rate": success_rate,
            "avg_positive_impact": avg_positive,
            "avg_negative_impact": avg_negative,
            "top_rules": [rule for rule, _ in rule_counts.most_common(limit)],
            "recent_notes": [note.to_dict() for note in notes],
        }

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        needle = _normalize_text(query)
        if not needle:
            return []

        tokens = {part for part in needle.split(" ") if part}
        results: list[tuple[int, dict[str, Any]]] = []

        for note in reversed(self._notes):
            haystack = " ".join([
                _normalize_text(note.kind),
                _normalize_text(note.title),
                _normalize_text(note.summary),
                _normalize_text(note.metadata),
            ])
            score = sum(2 for token in tokens if token in haystack)
            if score:
                results.append((score, {"type": "note", **note.to_dict()}))

        for outcome in self.recent_outcomes(limit=500):
            haystack = " ".join([
                _normalize_text(outcome.rule_id),
                _normalize_text(outcome.feedback),
                _normalize_text(outcome.metadata),
            ])
            score = sum(2 for token in tokens if token in haystack)
            if score:
                results.append((score, {"type": "outcome", **outcome.to_dict()}))

        results.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in results[:limit]]


class SemanticMemory:
    """Small semantic layer over long-term memory using keyword similarity."""

    def __init__(self, memory: LongTermMemory | None = None):
        self.memory = memory or LongTermMemory()

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.memory.search(query, limit=limit)


class ReflectionSystem:
    """Produce lightweight reflections from stored outcomes and notes."""

    def __init__(self, memory: LongTermMemory | None = None, reflections_path: str = str(MEMORY_REFLECTIONS)):
        self.memory = memory or LongTermMemory()
        self.reflections_path = Path(reflections_path)
        self.reflections_path.parent.mkdir(parents=True, exist_ok=True)

    def reflect(self, limit: int = 100) -> dict[str, Any]:
        outcomes = self.memory.recent_outcomes(limit=limit)
        if not outcomes:
            report = {
                "generated_at": _utc_now().isoformat(),
                "status": "empty",
                "summary": "No decision outcomes available for reflection.",
                "insights": [],
                "recommendations": ["Collect more decision outcomes before reflecting."],
            }
            self._persist(report)
            return report

        by_rule: dict[str, list[DecisionOutcome]] = defaultdict(list)
        by_outcome = Counter()
        for outcome in outcomes:
            by_rule[outcome.rule_id].append(outcome)
            by_outcome[outcome.outcome_type] += 1

        weak_rules: list[dict[str, Any]] = []
        strong_rules: list[dict[str, Any]] = []
        for rule_id, items in by_rule.items():
            effectiveness = self.memory.outcomes.get_rule_effectiveness(rule_id)
            avg_impact = sum((item.impact_realized or 0.0) for item in items if item.impact_realized is not None)
            avg_impact = avg_impact / max(1, len([item for item in items if item.impact_realized is not None]))
            entry = {
                "rule_id": rule_id,
                "count": len(items),
                "effectiveness": effectiveness,
                "avg_impact": avg_impact,
            }
            if len(items) >= 2 and effectiveness < 0.45:
                weak_rules.append(entry)
            elif len(items) >= 2 and effectiveness >= 0.75:
                strong_rules.append(entry)

        insights: list[str] = []
        recommendations: list[str] = []
        if weak_rules:
            insights.append(f"{len(weak_rules)} rule(s) show weak execution quality.")
            recommendations.append("Review weak rules and tighten guardrails or lower priority_boost.")
        if strong_rules:
            insights.append(f"{len(strong_rules)} rule(s) are performing well and can be used as references.")
            recommendations.append("Promote strong rules as templates for similar scenarios.")
        if by_outcome.get("failure", 0) > by_outcome.get("success", 0):
            insights.append("Failures outnumber successes in the recent memory window.")
            recommendations.append("Investigate operational blockers behind repeated failures.")

        if not insights:
            insights.append("Recent memory is balanced with no obvious concentration of issues.")
            recommendations.append("Keep collecting outcomes to improve confidence.")

        report = {
            "generated_at": _utc_now().isoformat(),
            "status": "ok",
            "window_size": len(outcomes),
            "outcome_counts": dict(by_outcome),
            "weak_rules": weak_rules,
            "strong_rules": strong_rules,
            "insights": insights,
            "recommendations": recommendations,
        }
        self.memory.remember_note(
            kind="reflection",
            title="Memory reflection",
            summary="; ".join(insights[:3]),
            metadata={"weak_rules": weak_rules, "strong_rules": strong_rules},
        )
        self._persist(report)
        return report

    def _persist(self, report: dict[str, Any]) -> None:
        with self.reflections_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False) + "\n")
