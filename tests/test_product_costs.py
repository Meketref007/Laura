import json

import pytest

import shopee_agent.cli as cli


def test_save_and_load_product_costs(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    product_costs_path = reports_dir / "product_costs.json"

    # Monkeypatch the module constant to point to our temp path
    monkeypatch.setattr(cli, "_PRODUCT_COSTS_PATH", product_costs_path)

    # Ensure clean start
    if product_costs_path.exists():
        product_costs_path.unlink()

    # Save a cost and verify file created
    cli._save_product_cost("12345", 12.34)
    assert product_costs_path.exists()

    data = json.loads(product_costs_path.read_text(encoding="utf-8"))
    assert data.get("12345") == 12.34

    # Load via helper
    loaded = cli._load_product_costs()
    assert isinstance(loaded, dict)
    assert loaded.get("12345") == pytest.approx(12.34)

    # get cost for item
    cost = cli._get_cost_for_item("12345")
    assert cost == pytest.approx(12.34)

    # non-existing returns None
    assert cli._get_cost_for_item("99999") is None


def test_load_cost_source_rows_and_sync(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    product_costs_path = reports_dir / "product_costs.json"
    monkeypatch.setattr(cli, "_PRODUCT_COSTS_PATH", product_costs_path)

    csv_path = tmp_path / "costs.csv"
    csv_path.write_text(
        "sku,item_name,cost\nSKU-001,Produto A,11.25\nSKU-002,Produto B,9.90\n",
        encoding="utf-8",
    )

    rows = cli._load_cost_source_rows(csv_path)
    assert len(rows) == 2

    lookup = {
        "sku:sku-001": "12345",
        "name:produto b": "67890",
    }

    summary = cli._sync_product_cost_rows(rows, lookup=lookup, dry_run=False)
    assert summary["saved"] == 2
    assert summary["unmatched"] == 0

    loaded = cli._load_product_costs()
    assert loaded["12345"] == pytest.approx(11.25)
    assert loaded["67890"] == pytest.approx(9.90)


def test_load_cost_source_rows_from_json_dict(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    product_costs_path = reports_dir / "product_costs.json"
    monkeypatch.setattr(cli, "_PRODUCT_COSTS_PATH", product_costs_path)

    json_path = tmp_path / "costs.json"
    json_path.write_text(
        json.dumps({
            "111": 7.5,
            "222": {"cost": 8.75, "item_name": "Produto C"},
        }),
        encoding="utf-8",
    )

    rows = cli._load_cost_source_rows(json_path)
    assert len(rows) == 2

    summary = cli._sync_product_cost_rows(rows, dry_run=False)
    assert summary["saved"] == 2

    loaded = cli._load_product_costs()
    assert loaded["111"] == pytest.approx(7.5)
    assert loaded["222"] == pytest.approx(8.75)


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeCatalogClient:
    def __init__(self):
        self.calls = []

    def get_item_list(self, *, access_token, shop_id, offset=0, page_size=50, item_status="NORMAL"):
        self.calls.append(("list", offset, page_size))
        if offset > 0:
            return _FakeResponse({"response": {"item": [], "has_next_page": False}})
        return _FakeResponse({
            "response": {
                "item": [
                    {"item_id": 1001, "item_name": "Produto A"},
                    {"item_id": 1002, "item_name": "Produto B"},
                ],
                "has_next_page": False,
            }
        })

    def get_item_detail(self, *, access_token, shop_id, item_id):
        self.calls.append(("detail", item_id))
        if item_id == 1001:
            return _FakeResponse({
                "response": {
                    "variation_list": [
                        {"variation_id": 11, "variation_name": "P A", "current_price": 25.0},
                            {"variation_id": 12, "variation_name": "P A 2", "current_price": 12.0},
                    ]
                }
            })
        return _FakeResponse({
            "response": {
                "current_price": 30.0,
            }
        })


def test_margin_review_report_flags_low_margin_and_missing_cost(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    product_costs_path = reports_dir / "product_costs.json"
    monkeypatch.setattr(cli, "_PRODUCT_COSTS_PATH", product_costs_path)
    monkeypatch.chdir(tmp_path)

    cli._save_product_cost("1001", 10.0)

    client = _FakeCatalogClient()
    report = cli._build_margin_review_report(
        client,
        access_token="token",
        shop_id=1,
        low_margin_threshold=0.20,
        target_margin_floor=0.25,
        max_items=10,
        page_size=50,
    )

    assert report["items_seen"] == 2
    assert report["reviewed_count"] == 3
    assert report["low_margin_count"] == 1
    assert report["missing_cost_count"] == 1
    assert report["missing_price_count"] == 0

    risky = report["top_risks"][0]
    assert risky["item_id"] == "1001"
    assert risky["variation_id"] == "12"
    assert risky["status"] == "low_margin"
    assert risky["margin_pct"] == pytest.approx(16.67, rel=1e-2)
    assert risky["recommended_price"] == pytest.approx(13.33, rel=1e-2)


def test_create_margin_remediation_case_writes_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    report = {
        "items_seen": 2,
        "reviewed_count": 2,
        "low_margin_count": 1,
        "missing_cost_count": 0,
        "missing_price_count": 0,
        "top_risks": [
            {
                "item_id": "1001",
                "variation_id": "12",
                "variation_name": "P A 2",
                "price": 12.0,
                "cost": 10.0,
                "margin_pct": 16.67,
                "recommended_price": 13.33,
            }
        ],
    }

    case = cli._create_margin_remediation_case(report, reports_dir=reports_dir)

    cases_file = reports_dir / "laura_remediation_cases.jsonl"
    audit_file = reports_dir / "laura_remediation_audit.jsonl"
    assert cases_file.exists()
    assert audit_file.exists()

    saved = json.loads(cases_file.read_text(encoding="utf-8").strip())
    assert saved["action_key"] == "protect_margin"
    assert saved["execute_on_approve"] is True
    assert saved["payload"][0]["item_id"] == "1001"
    assert case["case_id"].startswith("protect_margin-")
