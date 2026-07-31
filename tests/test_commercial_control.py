import json


import shopee_agent.cli as cli


def test_decide_commercial_strategy_prioritizes_margin():
    snapshot = {
        "financial": {"metrics": {"revenue": 120.0, "profit": 10.0, "margin_pct": 14.0, "refund_rate_pct": 1.0, "roas": 2.5}},
        "inventory": {"low_stock_count": 0},
        "margin_review": {"low_margin_count": 3, "target_margin_floor": 0.25},
        "health": {"overall_status": "HEALTHY"},
    }

    strategy = cli._decide_commercial_strategy(snapshot)

    assert strategy["primary_action_key"] == "protect_margin"
    assert strategy["commercial_mode"] == "optimize_margin"
    assert strategy["supported_for_approval"] is True
    assert any("margem" in item.lower() for item in strategy["objectives"])


def test_decide_commercial_strategy_prioritizes_scaling_when_healthy():
    snapshot = {
        "financial": {"metrics": {"revenue": 500.0, "profit": 120.0, "margin_pct": 35.0, "refund_rate_pct": 1.0, "roas": 3.5}},
        "inventory": {"low_stock_count": 0},
        "margin_review": {"low_margin_count": 0, "target_margin_floor": 0.25},
        "health": {"overall_status": "HEALTHY"},
    }

    strategy = cli._decide_commercial_strategy(snapshot)

    assert strategy["primary_action_key"] == "monitor_only"
    assert strategy["commercial_mode"] == "stabilize"
    assert strategy["supported_for_approval"] is False


def test_create_commercial_remediation_case_writes_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    snapshot = {
        "financial": {"metrics": {"revenue": 120.0, "profit": 10.0, "margin_pct": 14.0, "refund_rate_pct": 1.0, "roas": 2.5}},
        "inventory": {"low_stock_count": 0},
        "margin_review": {
            "low_margin_count": 2,
            "low_margin_entries": [
                {"item_id": "1001", "variation_id": "12", "variation_name": "P A 2", "price": 12.0, "cost": 10.0, "margin_pct": 16.67, "recommended_price": 13.33},
                {"item_id": "1002", "variation_id": "13", "variation_name": "P B", "price": 15.0, "cost": 13.0, "margin_pct": 13.33, "recommended_price": 17.33},
            ],
        },
        "health": {"overall_status": "HEALTHY"},
    }
    strategy = cli._decide_commercial_strategy(snapshot)

    case = cli._create_commercial_remediation_case(strategy, snapshot, reports_dir=reports_dir)

    assert case is not None
    cases_file = reports_dir / "laura_remediation_cases.jsonl"
    assert cases_file.exists()
    saved = json.loads(cases_file.read_text(encoding="utf-8").strip())
    assert saved["action_key"] == "protect_margin"
    assert saved["execute_on_approve"] is True
    assert len(saved["payload"]) == 2
    assert case["case_id"].startswith("protect_margin-")


def test_build_erp_state_and_persist_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    snapshot = {
        "financial": {"metrics": {"revenue": 300.0, "profit": 40.0, "margin_pct": 28.0, "refund_rate_pct": 1.0, "roas": 2.2, "orders": 8}},
        "inventory": {"low_stock_count": 2, "low_stock_items": [{"item_id": "9001"}, {"item_id": "9002"}], "items_seen": 10, "low_stock_threshold": 5},
        "margin_review": {"low_margin_count": 1, "low_margin_entries": [{"item_id": "1001", "variation_id": "12"}], "target_margin_floor": 0.25},
        "health": {"overall_status": "HEALTHY", "alerts": []},
    }
    strategy = {
        "primary_action_key": "protect_margin",
        "commercial_mode": "optimize_margin",
        "primary_reason": "margem baixa",
        "objectives": ["Proteger margem"],
        "risks": ["margem baixa"],
        "supported_for_approval": True,
    }

    state = cli._build_erp_state(snapshot, strategy)
    latest_path, history_path = cli._persist_erp_state(state, reports_dir=reports_dir)

    assert latest_path.exists()
    assert history_path.exists()
    assert state["erp_status"] in {"healthy", "watch", "at_risk", "critical"}
    assert state["erp_score"] <= 100
    assert state["next_actions"]
    assert state["modules"]["automation"]["recommended_primary_action"] == "protect_margin"

    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["erp_status"] == state["erp_status"]


def test_build_erp_state_scores_critical_when_empty():
    snapshot = {
        "financial": {"metrics": {"revenue": 0.0, "profit": 0.0, "margin_pct": 0.0, "refund_rate_pct": 0.0, "roas": None, "orders": 0}},
        "inventory": {"low_stock_count": 0, "low_stock_items": [], "items_seen": 0, "low_stock_threshold": 5},
        "margin_review": {"low_margin_count": 0, "low_margin_entries": [], "target_margin_floor": 0.25},
        "health": {"overall_status": "ATTENTION", "alerts": ["api"]},
    }
    strategy = {
        "primary_action_key": "monitor_only",
        "commercial_mode": "observe",
        "primary_reason": "sem dados",
        "objectives": ["Observar"],
        "risks": [],
        "supported_for_approval": False,
    }

    state = cli._build_erp_state(snapshot, strategy)

    assert state["erp_status"] == "critical"
    assert state["erp_score"] < 40