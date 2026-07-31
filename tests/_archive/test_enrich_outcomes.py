import json
from datetime import datetime, timedelta, timezone

import pytest

from shopee_agent.decision_memory import DecisionOutcome, MemoryLayer
from shopee_agent.enrich_outcomes import enrich_outcomes


def write_profit_history(tmp_path, before_margin=10.0, after_margin=12.0, decision_time=None):
    p = tmp_path / "laura_profitability_history.jsonl"
    if decision_time is None:
        decision_time = datetime.now(timezone.utc)

    before = decision_time - timedelta(hours=1)
    after = decision_time + timedelta(hours=2)

    with open(p, "w") as f:
        f.write(json.dumps({
            "recorded_at": before.isoformat(),
            "metrics": {"margin_pct": before_margin}
        }) + "\n")
        f.write(json.dumps({
            "recorded_at": after.isoformat(),
            "metrics": {"margin_pct": after_margin}
        }) + "\n")

    return p


def test_enrich_single_outcome(tmp_path, monkeypatch):
    # Prepare fake reports paths
    ph = tmp_path / "laura_profitability_history.jsonl"
    dl = tmp_path / "decision_log.jsonl"
    out = tmp_path / "decision_outcomes.jsonl"

    decision_time = datetime.now(timezone.utc) - timedelta(hours=8)

    # write profit history
    with open(ph, "w") as f:
        f.write(json.dumps({
            "recorded_at": (decision_time - timedelta(minutes=10)).isoformat(),
            "metrics": {"margin_pct": 15.0}
        }) + "\n")
        f.write(json.dumps({
            "recorded_at": (decision_time + timedelta(hours=4)).isoformat(),
            "metrics": {"margin_pct": 17.0}
        }) + "\n")

    # write decision log with estimate impact
    decision_id = "dec_test_enrich"
    with open(dl, "w") as f:
        f.write(json.dumps({
            "decision_id": decision_id,
            "impact_score": 0.02
        }) + "\n")

    # write outcomes (executed)
    outcome = DecisionOutcome(
        decision_id=decision_id,
        rule_id="pricing_margin_protect",
        executed_at=decision_time,
        outcome_type="executed",
    )
    with open(out, "w") as f:
        f.write(json.dumps(outcome.to_dict()) + "\n")

    # point the module paths to tmp files via monkeypatch
    monkeypatch.setenv("PWD", str(tmp_path))
    # patch constants in module
    from shopee_agent import enrich_outcomes as eo
    eo.PROFIT_HISTORY = ph
    eo.DECISION_LOG = dl
    eo.OUTCOMES_PATH = out

    # run enrichment
    updated = enrich_outcomes(hours=6)
    assert updated == 1

    # reload outcomes and check values
    mem = MemoryLayer(path=str(out))
    outs = mem.list_outcomes()
    assert len(outs) == 1
    o = outs[0]
    assert o.impact_realized == pytest.approx(2.0)
    assert o.outcome_type in ("success", "partial", "failure")
