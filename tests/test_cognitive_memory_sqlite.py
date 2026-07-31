from __future__ import annotations

from shopee_agent.cognitive_memory import LongTermMemory, ReflectionSystem
from shopee_agent.decision_memory import DecisionOutcome


def test_long_term_memory_persists_in_sqlite(tmp_path):
    db_path = tmp_path / "memory.sqlite3"

    memory = LongTermMemory(database_path=str(db_path))
    memory.remember_outcome(
        DecisionOutcome(
            decision_id="d1",
            rule_id="pricing_rule",
            outcome_type="success",
            impact_realized=0.2,
            metadata={"metric": "margin_drop"},
        )
    )
    memory.remember_note("strategy", "Improve margin", "Review pricing and bundles", metadata={"topic": "pricing"})

    reloaded = LongTermMemory(database_path=str(db_path))

    overview = reloaded.overview(limit=5)
    results = reloaded.search("pricing margin", limit=5)
    reflection = ReflectionSystem(reloaded).reflect(limit=5)

    assert overview["outcome_count"] == 1
    assert overview["note_count"] == 1
    assert results
    assert any(result["type"] == "note" for result in results)
    assert reflection["status"] == "ok"
