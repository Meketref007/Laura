from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.cross_selling import CrossSellingEngine, CrossSellingSkill


@pytest.fixture
def sample_orders():
    return [
        {
            "item_list": [
                {"item_id": "101", "name": "Item A"},
                {"item_id": "102", "name": "Item B"},
            ]
        },
        {
            "item_list": [
                {"item_id": "101", "name": "Item A"},
                {"item_id": "103", "name": "Item C"},
            ]
        },
        {
            "item_list": [
                {"item_id": "102", "name": "Item B"},
                {"item_id": "103", "name": "Item C"},
            ]
        },
    ]


@pytest.fixture
def engine():
    return CrossSellingEngine()


class TestCrossSellingEngine:
    def test_build_product_graph(self, engine, sample_orders):
        engine._orders = sample_orders
        graph = engine.build_product_graph()
        assert "101" in graph
        assert "102" in graph
        assert "103" in graph
        assert graph["101"]["102"] >= 1
        assert graph["101"]["103"] >= 1

    def test_build_product_graph_no_orders(self, engine):
        engine._orders = []
        assert engine.build_product_graph() == {}

    def test_get_recommendations(self, engine):
        engine._graph = {
            "101": {"102": 3, "103": 1},
            "102": {"101": 3},
            "103": {"101": 1},
        }
        recs = engine.get_recommendations("101", top_n=2)
        assert len(recs) == 2
        assert recs[0]["product_id"] == "102"
        assert recs[0]["co_occurrence_count"] == 3

    def test_get_recommendations_empty_graph(self, engine):
        assert engine.get_recommendations("999", top_n=5) == []

    def test_get_bundle_recommendations(self, engine):
        engine._graph = {
            "101": {"102": 2, "103": 5},
            "102": {"101": 2, "104": 3},
            "103": {"101": 5, "104": 1},
        }
        recs = engine.get_bundle_recommendations(["101", "102"], top_n=3)
        assert len(recs) >= 1
        pids = {r["product_id"] for r in recs}
        assert "103" in pids or "104" in pids
        assert "101" not in pids
        assert "102" not in pids

    def test_get_bundle_recommendations_empty_cart(self, engine):
        assert engine.get_bundle_recommendations([], top_n=3) == []

    def test_get_category_cross_sell(self, engine, tmp_path):
        catalog_path = tmp_path / "product_catalog.jsonl"
        catalog_path.write_text(
            json.dumps({"item_id": 1, "category_id": 10, "name": "Prod1", "sales_count": 50}) + "\n" +
            json.dumps({"item_id": 2, "category_id": 10, "name": "Prod2", "sales_count": 100}) + "\n" +
            json.dumps({"item_id": 3, "category_id": 20, "name": "Prod3", "sales_count": 200}) + "\n",
            encoding="utf-8",
        )
        with patch("shopee_agent.cross_selling.PRODUCT_CATALOG_PATH", catalog_path):
            results = engine.get_category_cross_sell(10, top_n=5)
            assert len(results) == 2
            assert results[0]["product_id"] == "2"

    def test_get_category_cross_sell_empty(self, engine, tmp_path):
        catalog_path = tmp_path / "product_catalog.jsonl"
        catalog_path.write_text("", encoding="utf-8")
        with patch("shopee_agent.cross_selling.PRODUCT_CATALOG_PATH", catalog_path):
            assert engine.get_category_cross_sell(10) == []

    def test_calculate_affinity(self, engine):
        engine._graph = {"101": {"102": 4, "103": 1}}
        score = engine.calculate_affinity("101", "102")
        assert 0.0 < score <= 1.0

    def test_calculate_affinity_no_relation(self, engine):
        engine._graph = {"101": {"102": 4}}
        assert engine.calculate_affinity("101", "999") == 0.0

    def test_calculate_affinity_same_product(self, engine):
        assert engine.calculate_affinity("101", "101") == 1.0

    def test_get_top_selling_pairs(self, engine):
        engine._graph = {"101": {"102": 5, "103": 2}, "102": {"101": 5}}
        pairs = engine.get_top_selling_pairs(top_n=10)
        assert len(pairs) == 2
        assert pairs[0]["product_a"] < pairs[0]["product_b"]

    def test_get_top_selling_pairs_empty(self, engine, tmp_path):
        graph_path = tmp_path / "cross_sell_graph.json"
        with patch("shopee_agent.cross_selling.CROSS_SELL_GRAPH", graph_path):
            assert engine.get_top_selling_pairs() == []

    def test_cross_selling_skill_run_recommend(self, sample_orders):
        skill = CrossSellingSkill()
        with patch.object(skill, "_client") as mock_client:
            mock_client.get_order_list.return_value = MagicMock(
                data={"response": {"order_list": sample_orders, "next_cursor": ""}}
            )
            result = skill.run(
                access_token="tok",
                shop_id=1,
                product_id="101",
                action="recommend",
                top_n=3,
            )
            assert result["orders_loaded"] == 3
            assert "recommendations" in result
            assert "graph_stats" in result

    def test_cross_selling_skill_run_bundle(self, sample_orders):
        skill = CrossSellingSkill()
        with patch.object(skill, "_client") as mock_client:
            mock_client.get_order_list.return_value = MagicMock(
                data={"response": {"order_list": sample_orders, "next_cursor": ""}}
            )
            result = skill.run(
                access_token="tok",
                shop_id=1,
                cart_items=["101"],
                action="bundle",
                top_n=3,
            )
            assert "bundle_recommendations" in result

    def test_cross_selling_skill_run_no_orders(self):
        skill = CrossSellingSkill()
        mock_cache = MagicMock()
        mock_cache.exists.return_value = False
        with patch.object(skill, "_client") as mock_client:
            mock_client.get_order_list.return_value = MagicMock(
                data={"response": {"order_list": [], "next_cursor": ""}}
            )
            with patch("shopee_agent.cross_selling.ORDER_HISTORY_CACHE", mock_cache):
                result = skill.run(access_token="tok", shop_id=1, product_id="101")
                assert "error" in result
                assert result["orders_loaded"] == 0

    def test_cross_selling_skill_run_all(self, sample_orders):
        skill = CrossSellingSkill()
        with patch.object(skill, "_client") as mock_client:
            mock_client.get_order_list.return_value = MagicMock(
                data={"response": {"order_list": sample_orders, "next_cursor": ""}}
            )
            result = skill.run(
                access_token="tok",
                shop_id=1,
                product_id="101",
                cart_items=["102"],
                category_id=10,
                action="all",
            )
            assert "recommendations" in result
            assert "bundle_recommendations" in result
            assert "category_recommendations" in result
            assert "top_pairs" in result
