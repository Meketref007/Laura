from __future__ import annotations

import json


from shopee_agent import cli
from shopee_agent.branding_growth import BrandingGrowthAnalyzer
from shopee_agent.decision_engine import DecisionEngine
from shopee_agent.decision_integration import DecisionIntegrator


def test_branding_growth_analyzer_scores_catalog_items(tmp_path):
    catalog_path = tmp_path / "reports" / "product_catalog.jsonl"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "item_id": "item-1",
                        "item_name": "Kit premium para organizacao de escritorio",
                        "description": "Kit completo com acessorios premium, suporte e garantia extendida.",
                        "category": "office premium",
                        "tags": ["kit", "premium", "office"],
                        "current_price": 149.9,
                        "weekly_growth_pct": 12.0,
                        "image_count": 5,
                    }
                ),
                json.dumps(
                    {
                        "item_id": "item-2",
                        "item_name": "Capa",
                        "description": "",
                        "category": "accessories",
                        "tags": [],
                        "current_price": 39.9,
                        "weekly_growth_pct": -3.0,
                        "image_count": 1,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    analyzer = BrandingGrowthAnalyzer(catalog_path=str(catalog_path))
    snapshot = analyzer.snapshot()

    assert snapshot.total_items == 2
    assert snapshot.average_score > 0
    assert any(item["item_id"] == "item-1" for item in snapshot.top_items)
    assert any(item["item_id"] == "item-2" for item in snapshot.weak_items)


def test_decision_integrator_includes_branding_growth_snapshot(tmp_path, monkeypatch):
    catalog_path = tmp_path / "reports" / "product_catalog.jsonl"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(
            {
                "item_id": "item-1",
                "item_name": "Kit premium para organizacao de escritorio",
                "description": "Kit completo com acessorios premium, suporte e garantia extendida.",
                "category": "office premium",
                "tags": ["kit", "premium", "office"],
                "current_price": 149.9,
                "weekly_growth_pct": 12.0,
                "image_count": 5,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    integrator = DecisionIntegrator(
        engine=DecisionEngine(store_id="test_store"),
        store_id="test_store",
        metrics_dir=str(tmp_path / "reports"),
        branding_growth=BrandingGrowthAnalyzer(catalog_path=str(catalog_path)),
    )

    monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])

    result = integrator.process_cycle()

    assert result["branding_growth"] is not None
    assert result["branding_growth"]["total_items"] == 1
    assert integrator.last_branding_growth_snapshot is not None


def test_build_parser_includes_branding_growth_command():
    parser = cli.build_parser()
    args = parser.parse_args(["branding-growth-summary", "--catalog-file", "reports/product_catalog.jsonl"])

    assert args.command == "branding-growth-summary"
    assert args.catalog_file == "reports/product_catalog.jsonl"


def test_main_dispatches_branding_growth_summary_without_loading_shopee_config(tmp_path, monkeypatch):
    catalog_path = tmp_path / "reports" / "product_catalog.jsonl"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(
            {
                "item_id": "item-1",
                "item_name": "Kit premium para organizacao de escritorio",
                "description": "Kit completo com acessorios premium, suporte e garantia extendida.",
                "category": "office premium",
                "tags": ["kit", "premium", "office"],
                "current_price": 149.9,
                "weekly_growth_pct": 12.0,
                "image_count": 5,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "initialize_default_circuit_breakers", lambda: None)
    monkeypatch.setattr(cli.sys, "argv", [
        "laura",
        "branding-growth-summary",
        "--catalog-file",
        str(catalog_path),
    ])

    exit_code = cli.main()

    assert exit_code == 0
