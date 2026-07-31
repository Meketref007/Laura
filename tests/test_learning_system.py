from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import shopee_agent.cli as cli
from shopee_agent.decision_memory import DecisionOutcome
from shopee_agent.learning_system import LearningSystem
from shopee_agent.cognitive_memory import LongTermMemory


def _remember_outcomes(memory: LongTermMemory, entries: list[DecisionOutcome]) -> None:
    for entry in entries:
        memory.remember_outcome(entry)


def test_learning_system_generates_report_and_persists_note(tmp_path):
    outcomes_path = tmp_path / "decision_outcomes.jsonl"
    notes_path = tmp_path / "long_term_memory_notes.jsonl"
    memory = LongTermMemory(outcomes_path=str(outcomes_path), notes_path=str(notes_path))

    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=2)
    older = now - timedelta(days=10)

    _remember_outcomes(
        memory,
        [
            DecisionOutcome(decision_id="d1", rule_id="pricing_margin_protect", executed_at=recent, outcome_type="failure", impact_realized=-0.02),
            DecisionOutcome(decision_id="d2", rule_id="pricing_margin_protect", executed_at=recent, outcome_type="failure", impact_realized=-0.03),
            DecisionOutcome(decision_id="d3", rule_id="ads_pause_low_roas", executed_at=recent, outcome_type="success", impact_realized=0.04),
            DecisionOutcome(decision_id="d4", rule_id="inventory_restock", executed_at=recent, outcome_type="partial", impact_realized=0.01),
            DecisionOutcome(decision_id="d5", rule_id="pricing_margin_protect", executed_at=older, outcome_type="success", impact_realized=0.03),
            DecisionOutcome(decision_id="d6", rule_id="ads_pause_low_roas", executed_at=older, outcome_type="success", impact_realized=0.02),
        ],
    )

    system = LearningSystem(memory=memory)
    report = system.evaluate(window_days=7, persist_note=True)

    assert report.recent_outcomes == 4
    assert report.previous_outcomes == 2
    assert report.success_rate == 0.5
    assert report.failure_rate == 0.5
    assert report.learning_health < 100
    assert any(rule["rule_id"] == "pricing_margin_protect" for rule in report.weak_rules)
    assert any("failure" in insight.lower() for insight in report.insights)

    note = memory.recent_notes(limit=1)[0]
    assert note.kind == "learning_cycle"
    assert "health=" in note.summary
    assert notes_path.exists()


def test_learning_system_record_feedback_creates_note(tmp_path):
    memory = LongTermMemory(
        outcomes_path=str(tmp_path / "decision_outcomes.jsonl"),
        notes_path=str(tmp_path / "long_term_memory_notes.jsonl"),
    )
    system = LearningSystem(memory=memory)

    note = system.record_feedback(
        title="manual feedback",
        summary="Cliente relatou atraso de entrega e resposta lenta.",
        metadata={"buyer_id": "buyer_1", "channel": "support"},
    )

    assert note["kind"] == "feedback"
    assert note["title"] == "manual feedback"
    assert memory.recent_notes(limit=1)[0].summary.startswith("Cliente relatou")


def test_learning_summary_cli_outputs_json(tmp_path, monkeypatch):
    outcomes_path = tmp_path / "decision_outcomes.jsonl"
    notes_path = tmp_path / "long_term_memory_notes.jsonl"
    memory = LongTermMemory(outcomes_path=str(outcomes_path), notes_path=str(notes_path))
    now = datetime.now(timezone.utc)
    _remember_outcomes(
        memory,
        [
            DecisionOutcome(decision_id="d1", rule_id="pricing_margin_protect", executed_at=now - timedelta(days=1), outcome_type="success", impact_realized=0.02),
            DecisionOutcome(decision_id="d2", rule_id="pricing_margin_protect", executed_at=now - timedelta(days=1), outcome_type="failure", impact_realized=-0.02),
        ],
    )

    output_path = tmp_path / "learning_report.json"
    monkeypatch.setattr(cli.sys, "argv", [
        "laura",
        "learning-summary",
        "--outcomes-path",
        str(outcomes_path),
        "--notes-path",
        str(notes_path),
        "--window-days",
        "7",
        "--output",
        str(output_path),
    ])

    exit_code = cli.main()

    assert exit_code == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["window_days"] == 7
    assert payload["total_outcomes"] == 2
    assert payload["learning_health"] <= 100