from __future__ import annotations

import json
from datetime import datetime, timezone

from shopee_agent.cognitive_memory import LongTermMemory, ReflectionSystem, SemanticMemory
from shopee_agent.decision_memory import DecisionOutcome


def test_long_term_memory_overview_and_notes(tmp_path):
    outcomes_path = tmp_path / "decision_outcomes.jsonl"
    notes_path = tmp_path / "long_term_memory_notes.jsonl"
    memory = LongTermMemory(outcomes_path=str(outcomes_path), notes_path=str(notes_path))

    memory.remember_outcome(
        DecisionOutcome(
            decision_id="dec_1",
            rule_id="pricing_margin_protect",
            executed_at=datetime.now(timezone.utc),
            outcome_type="success",
            impact_realized=0.12,
        )
    )
    memory.remember_note("campaign", "ROAS recovery", "Paused low ROAS ads after monitoring")

    overview = memory.overview(limit=5)

    assert overview["outcome_count"] == 1
    assert overview["note_count"] == 1
    assert overview["outcome_counts"]["success"] == 1
    assert overview["recent_notes"][0]["title"] == "ROAS recovery"


def test_semantic_memory_search_finds_related_note(tmp_path):
    memory = LongTermMemory(
        outcomes_path=str(tmp_path / "decision_outcomes.jsonl"),
        notes_path=str(tmp_path / "long_term_memory_notes.jsonl"),
    )
    memory.remember_note("inventory", "Stockout risk", "Low stock detected for core SKUs")
    memory.remember_note("ads", "Budget tune-up", "Improved ROAS for search campaign")

    semantic = SemanticMemory(memory)
    results = semantic.search("stock risk", limit=5)

    assert results
    assert any(result.get("title") == "Stockout risk" for result in results)


def test_reflection_identifies_weak_rules_and_persists_report(tmp_path):
    memory = LongTermMemory(
        outcomes_path=str(tmp_path / "decision_outcomes.jsonl"),
        notes_path=str(tmp_path / "long_term_memory_notes.jsonl"),
    )
    memory.remember_outcome(DecisionOutcome(decision_id="d1", rule_id="weak_rule", outcome_type="failure", impact_realized=-0.2, executed_at=datetime.now(timezone.utc)))
    memory.remember_outcome(DecisionOutcome(decision_id="d2", rule_id="weak_rule", outcome_type="failure", impact_realized=-0.1, executed_at=datetime.now(timezone.utc)))
    memory.remember_outcome(DecisionOutcome(decision_id="d3", rule_id="strong_rule", outcome_type="success", impact_realized=0.3, executed_at=datetime.now(timezone.utc)))
    memory.remember_outcome(DecisionOutcome(decision_id="d4", rule_id="strong_rule", outcome_type="success", impact_realized=0.2, executed_at=datetime.now(timezone.utc)))

    reflection_path = tmp_path / "memory_reflections.jsonl"
    reflection = ReflectionSystem(memory=memory, reflections_path=str(reflection_path))
    report = reflection.reflect(limit=10)

    assert report["status"] == "ok"
    assert any(rule["rule_id"] == "weak_rule" for rule in report["weak_rules"])
    assert any(rule["rule_id"] == "strong_rule" for rule in report["strong_rules"])
    assert reflection_path.exists()
    persisted = reflection_path.read_text(encoding="utf-8").strip().splitlines()
    assert persisted
    assert json.loads(persisted[-1])["status"] == "ok"
