from datetime import datetime, timezone


from shopee_agent.decision_memory import MemoryLayer, DecisionOutcome


def test_memory_remember_and_list(tmp_path):
    p = tmp_path / "outcomes.jsonl"
    mem = MemoryLayer(path=str(p))

    # Ensure empty initially
    assert mem.list_outcomes() == []

    outcome = DecisionOutcome(
        decision_id="dec_test1",
        rule_id="pricing_margin_protect",
        executed_at=datetime.now(timezone.utc),
        outcome_type="success",
        impact_realized=0.025,
        margin_change=0.5,
    )

    mem.remember_outcome(outcome)

    outs = mem.list_outcomes()
    assert len(outs) == 1
    assert outs[0].decision_id == "dec_test1"
    assert abs(outs[0].impact_realized - 0.025) < 1e-6


def test_get_rule_effectiveness(tmp_path):
    p = tmp_path / "outcomes.jsonl"
    mem = MemoryLayer(path=str(p))

    # Create mixed outcomes
    mem.remember_outcome(DecisionOutcome(decision_id="d1", rule_id="r1", outcome_type="success"))
    mem.remember_outcome(DecisionOutcome(decision_id="d2", rule_id="r1", outcome_type="partial"))
    mem.remember_outcome(DecisionOutcome(decision_id="d3", rule_id="r1", outcome_type="failure"))

    eff = mem.get_rule_effectiveness("r1")
    # success (1) + partial (0.5) + failure (0) => 1.5 / 3 = 0.5
    assert abs(eff - 0.5) < 1e-6

    # Unknown rule -> neutral 0.5
    assert abs(mem.get_rule_effectiveness("unknown") - 0.5) < 1e-6
