from __future__ import annotations

import json


from shopee_agent import cli
from shopee_agent.competitive_intelligence import CompetitiveIntelligence
from shopee_agent.decision_engine import DecisionEngine
from shopee_agent.decision_integration import DecisionIntegrator


def test_competitive_intelligence_snapshot_detects_threats_and_opportunities(tmp_path):
    intelligence = CompetitiveIntelligence(path=str(tmp_path / "reports" / "competitive_offers.jsonl"))
    intelligence.record_offer("Competitor A", "item-1", "Item One", 95.0, our_price=105.0)
    intelligence.record_offer("Competitor B", "item-1", "Item One", 90.0, our_price=105.0)
    intelligence.record_offer("Competitor C", "item-2", "Item Two", 120.0, our_price=100.0)
    intelligence.record_offer("Competitor D", "item-2", "Item Two", 135.0, our_price=100.0)

    snapshot = intelligence.snapshot(our_prices={"item-1": 105.0, "item-2": 100.0})

    assert snapshot.total_offers == 4
    assert snapshot.threat_count >= 1
    assert snapshot.opportunity_count >= 1
    assert any(signal["item_id"] == "item-1" for signal in snapshot.threats)
    assert any(signal["item_id"] == "item-2" for signal in snapshot.opportunities)


def test_decision_integrator_includes_competitive_snapshot(tmp_path, monkeypatch):
    intelligence = CompetitiveIntelligence(path=str(tmp_path / "reports" / "competitive_offers.jsonl"))
    intelligence.record_offer("Competitor A", "item-1", "Item One", 95.0, our_price=105.0)

    (tmp_path / "reports" / "product_prices.json").write_text(json.dumps({"item-1": 105.0}), encoding="utf-8")

    integrator = DecisionIntegrator(
        engine=DecisionEngine(store_id="test_store"),
        store_id="test_store",
        metrics_dir=str(tmp_path / "reports"),
        competitive_intelligence=intelligence,
    )

    monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])

    result = integrator.process_cycle()

    assert result["competitive_intelligence"] is not None
    assert result["competitive_intelligence"]["threat_count"] >= 1
    assert integrator.last_competitive_snapshot is not None


def test_build_parser_includes_competitive_intel_command():
    parser = cli.build_parser()
    args = parser.parse_args([
        "competitive-intel-summary",
        "--offers-file",
        "reports/competitive_offers.jsonl",
        "--our-prices-file",
        "reports/product_prices.json",
    ])

    assert args.command == "competitive-intel-summary"
    assert args.offers_file == "reports/competitive_offers.jsonl"
    assert args.our_prices_file == "reports/product_prices.json"


def test_main_dispatches_competitive_intel_summary_without_loading_shopee_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    intelligence = CompetitiveIntelligence(path=str(tmp_path / "reports" / "competitive_offers.jsonl"))
    intelligence.record_offer("Competitor A", "item-1", "Item One", 95.0, our_price=105.0)
    (tmp_path / "reports" / "product_prices.json").write_text(json.dumps({"item-1": 105.0}), encoding="utf-8")

    monkeypatch.setattr(cli, "initialize_default_circuit_breakers", lambda: None)
    monkeypatch.setattr(cli.sys, "argv", [
        "laura",
        "competitive-intel-summary",
        "--offers-file",
        str(tmp_path / "reports" / "competitive_offers.jsonl"),
        "--our-prices-file",
        str(tmp_path / "reports" / "product_prices.json"),
    ])

    exit_code = cli.main()

    assert exit_code == 0
