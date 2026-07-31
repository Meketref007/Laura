from __future__ import annotations

import json
import importlib

from click.testing import CliRunner

from shopee_agent.decision_cli import decision_cli
from shopee_agent.decision_memory import DecisionOutcome


def test_memory_summary_command(tmp_path, monkeypatch):
    """Override the default outcomes/notes paths so the CLI creates fresh files."""
    outcomes_file = tmp_path / "outcomes.json"
    notes_file = tmp_path / "notes.json"

    # Patch the paths module BEFORE any LongTermMemory is imported
    import shopee_agent.paths as paths_mod
    monkeypatch.setattr(paths_mod, "DECISION_OUTCOMES", outcomes_file)
    monkeypatch.setattr(paths_mod, "LONG_TERM_MEMORY_NOTES", notes_file)

    # Reload modules that import these paths so they pick up the new values
    import shopee_agent.cognitive_memory as cm
    importlib.reload(cm)

    # Also reload decision_cli since it has LongTermMemory at module level
    import shopee_agent.decision_cli as dc
    importlib.reload(dc)

    from shopee_agent.cognitive_memory import LongTermMemory
    memory = LongTermMemory()
    memory.remember_outcome(DecisionOutcome(decision_id="d1", rule_id="r1", outcome_type="success", impact_realized=0.1))
    memory.remember_note("ops", "Inventory watch", "Track low stock items")

    runner = CliRunner()
    result = runner.invoke(dc.decision_cli, ["memory-summary"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["outcome_count"] == 1
    assert payload["note_count"] == 1


def test_memory_reflect_command(tmp_path, monkeypatch):
    outcomes_file = tmp_path / "outcomes.json"
    notes_file = tmp_path / "notes.json"

    import shopee_agent.paths as paths_mod
    monkeypatch.setattr(paths_mod, "DECISION_OUTCOMES", outcomes_file)
    monkeypatch.setattr(paths_mod, "LONG_TERM_MEMORY_NOTES", notes_file)

    import shopee_agent.cognitive_memory as cm
    importlib.reload(cm)
    import shopee_agent.decision_cli as dc
    importlib.reload(dc)

    from shopee_agent.cognitive_memory import LongTermMemory
    memory = LongTermMemory()
    memory.remember_outcome(DecisionOutcome(decision_id="d1", rule_id="weak_rule", outcome_type="failure", impact_realized=-0.1))
    memory.remember_note("ops", "Inventory watch", "Track low stock items")

    runner = CliRunner()
    result = runner.invoke(dc.decision_cli, ["memory-reflect"])

    assert result.exit_code == 0
