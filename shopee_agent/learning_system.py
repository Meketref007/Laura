"""
Phase 8: Learning System.

Builds a continuous learning layer on top of decision outcomes and reflection.
The goal is to summarize feedback loops, detect failure patterns, and generate
actionable recommendations for the next operating cycle.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .cognitive_memory import LongTermMemory, ReflectionSystem, SemanticMemory
from .decision_memory import DecisionOutcome


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class LearningSignal:
    name: str
    value: float
    trend: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LearningReport:
    generated_at: str
    window_days: int
    total_outcomes: int
    recent_outcomes: int
    previous_outcomes: int
    success_rate: float
    failure_rate: float
    partial_rate: float
    learning_health: float
    signals: list[LearningSignal] = field(default_factory=list)
    weak_rules: list[dict[str, Any]] = field(default_factory=list)
    strong_rules: list[dict[str, Any]] = field(default_factory=list)
    failure_hotspots: list[dict[str, Any]] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    feedback_notes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signals"] = [signal.to_dict() for signal in self.signals]
        return payload


class LearningSystem:
    """Continuous improvement layer built on top of memory and reflection."""

    def __init__(
        self,
        memory: LongTermMemory | None = None,
        outcomes_path: str = "reports/decision_outcomes.jsonl",
        notes_path: str = "reports/long_term_memory_notes.jsonl",
        semantic_memory: SemanticMemory | None = None,
        reflection: ReflectionSystem | None = None,
    ):
        self.memory = memory or LongTermMemory(outcomes_path=outcomes_path, notes_path=notes_path)
        self.semantic_memory = semantic_memory or SemanticMemory(memory=self.memory)
        self.reflection = reflection or ReflectionSystem(memory=self.memory)

    def evaluate(self, window_days: int = 30, persist_note: bool = True) -> LearningReport:
        now = _utc_now()
        recent_cutoff = now - timedelta(days=window_days)
        previous_cutoff = now - timedelta(days=window_days * 2)

        outcomes = self.memory.recent_outcomes(limit=5000)
        dated_outcomes = [outcome for outcome in outcomes if outcome.executed_at is not None]
        recent = [outcome for outcome in dated_outcomes if outcome.executed_at >= recent_cutoff]
        previous = [outcome for outcome in dated_outcomes if previous_cutoff <= outcome.executed_at < recent_cutoff]

        success_rate = self._success_rate(recent)
        previous_success_rate = self._success_rate(previous)
        failure_rate = self._failure_rate(recent)
        partial_rate = self._partial_rate(recent)

        signal_values = [
            LearningSignal(
                name="success_rate",
                value=round(success_rate, 4),
                trend=round(success_rate - previous_success_rate, 4),
                evidence={"previous_success_rate": round(previous_success_rate, 4)},
            ),
            LearningSignal(
                name="failure_rate",
                value=round(failure_rate, 4),
                trend=round(self._failure_rate(previous) - failure_rate, 4),
                evidence={"previous_failure_rate": round(self._failure_rate(previous), 4)},
            ),
            LearningSignal(
                name="partial_rate",
                value=round(partial_rate, 4),
                trend=round(partial_rate - self._partial_rate(previous), 4),
                evidence={"previous_partial_rate": round(self._partial_rate(previous), 4)},
            ),
        ]

        rule_groups: dict[str, list[DecisionOutcome]] = defaultdict(list)
        for outcome in recent:
            rule_groups[outcome.rule_id].append(outcome)

        weak_rules: list[dict[str, Any]] = []
        strong_rules: list[dict[str, Any]] = []
        failure_hotspots: list[dict[str, Any]] = []

        for rule_id, items in sorted(rule_groups.items(), key=lambda item: len(item[1]), reverse=True):
            effectiveness = self.memory.outcomes.get_rule_effectiveness(rule_id)
            impact_values = [float(outcome.impact_realized) for outcome in items if outcome.impact_realized is not None]
            avg_impact = sum(impact_values) / len(impact_values) if impact_values else 0.0
            failures = sum(1 for outcome in items if outcome.outcome_type in {"failure", "reverted"})
            entry = {
                "rule_id": rule_id,
                "count": len(items),
                "effectiveness": round(effectiveness, 4),
                "avg_impact": round(avg_impact, 6),
                "failures": failures,
            }
            if len(items) >= 2 and effectiveness < 0.45:
                weak_rules.append(entry)
            elif len(items) >= 2 and effectiveness >= 0.75:
                strong_rules.append(entry)
            if failures >= 2:
                failure_hotspots.append(entry)

        reflection_report = self.reflection.reflect(limit=min(len(recent), 100) if recent else 100)
        insights = list(reflection_report.get("insights", []))
        recommendations = list(reflection_report.get("recommendations", []))

        if success_rate >= 0.7:
            insights.append("Recent outcomes indicate a healthy feedback loop.")
            recommendations.append("Preserve current rule templates and use them as references for new cases.")
        elif success_rate < 0.5:
            insights.append("Recent outcomes show weak adaptation quality.")
            recommendations.append("Review weak rules, tighten guardrails, and reduce priority on failing patterns.")

        if failure_rate >= 0.3:
            insights.append("Failure rate is elevated in the current learning window.")
            recommendations.append("Prioritize root-cause analysis on repeated failure hotspots.")

        if signal_values[0].trend < -0.05:
            recommendations.append("Recent success rate is trending down; run a shorter weekly learning pass.")

        learning_health = self._learning_health(success_rate, failure_rate, partial_rate, len(weak_rules), len(failure_hotspots))

        feedback_notes = [note.to_dict() for note in self.memory.recent_notes(limit=10) if note.kind in {"reflection", "learning_cycle", "feedback"}]

        report = LearningReport(
            generated_at=now.isoformat(),
            window_days=window_days,
            total_outcomes=len(dated_outcomes),
            recent_outcomes=len(recent),
            previous_outcomes=len(previous),
            success_rate=round(success_rate, 4),
            failure_rate=round(failure_rate, 4),
            partial_rate=round(partial_rate, 4),
            learning_health=round(learning_health, 2),
            signals=signal_values,
            weak_rules=weak_rules,
            strong_rules=strong_rules,
            failure_hotspots=failure_hotspots,
            insights=self._dedupe_texts(insights),
            recommendations=self._dedupe_texts(recommendations),
            feedback_notes=feedback_notes,
        )

        if persist_note:
            self.memory.remember_note(
                kind="learning_cycle",
                title=f"Learning cycle {window_days}d",
                summary=self._summarize_report(report),
                metadata={
                    "window_days": window_days,
                    "success_rate": report.success_rate,
                    "failure_rate": report.failure_rate,
                    "learning_health": report.learning_health,
                    "weak_rules": report.weak_rules,
                    "failure_hotspots": report.failure_hotspots,
                },
            )

        return report

    def record_feedback(
        self,
        *,
        title: str,
        summary: str,
        kind: str = "feedback",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        note = self.memory.remember_note(kind=kind, title=title, summary=summary, metadata=metadata or {})
        return note.to_dict()

    def search_lessons(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.semantic_memory.search(query, limit=limit)

    def weekly_report(self, persist_note: bool = True) -> LearningReport:
        return self.evaluate(window_days=7, persist_note=persist_note)

    def _success_rate(self, outcomes: list[DecisionOutcome]) -> float:
        if not outcomes:
            return 0.5
        good = sum(1 for outcome in outcomes if outcome.outcome_type in {"success", "partial"})
        return good / len(outcomes)

    def _failure_rate(self, outcomes: list[DecisionOutcome]) -> float:
        if not outcomes:
            return 0.0
        bad = sum(1 for outcome in outcomes if outcome.outcome_type in {"failure", "reverted"})
        return bad / len(outcomes)

    def _partial_rate(self, outcomes: list[DecisionOutcome]) -> float:
        if not outcomes:
            return 0.0
        partial = sum(1 for outcome in outcomes if outcome.outcome_type == "partial")
        return partial / len(outcomes)

    def _learning_health(self, success_rate: float, failure_rate: float, partial_rate: float, weak_rules: int, failure_hotspots: int) -> float:
        score = 100.0
        score -= max(0.0, (0.65 - success_rate) * 120.0)
        score -= failure_rate * 40.0
        score -= partial_rate * 10.0
        score -= min(25.0, weak_rules * 4.0)
        score -= min(20.0, failure_hotspots * 5.0)
        return max(0.0, min(100.0, score))

    def _summarize_report(self, report: LearningReport) -> str:
        top_issue = report.weak_rules[0]["rule_id"] if report.weak_rules else "none"
        return (
            f"health={report.learning_health:.1f}; success={report.success_rate:.1%}; "
            f"failure={report.failure_rate:.1%}; top_issue={top_issue}"
        )

    def _dedupe_texts(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result


def dump_learning_report(report: LearningReport, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
