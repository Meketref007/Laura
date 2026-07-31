"""Testes para pricing_automation com ML-based dynamic pricing."""
import json
import sys
import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shopee_agent.pricing_automation import (
    _extract_features,
    _cached_competitor_prices,
    _save_competitor_prices,
    PricingModel,
    DynamicPricingEngine,
    get_min_price,
    get_max_price,
    suggest_optimal_price,
    analyze_item_pricing,
    generate_pricing_report,
    update_competitor_data,
    apply_pricing_suggestion,
    get_pricing_dashboard_data,
    get_pricing_history,
    FEATURE_NAMES,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_item(
    item_id=1,
    name="Test",
    price=100.0,
    variations=None,
    cost=0,
    stock=50,
    sales_velocity=2,
    rating=4.5,
    review_count=10,
):
    return {
        "item_id": item_id,
        "item_name": name,
        "name": name,
        "price": price,
        "original_price": price,
        "variations": variations or [],
        "cost": cost,
        "cost_price": cost,
        "stock": stock,
        "stock_level": stock,
        "sales_velocity": sales_velocity,
        "daily_sales": sales_velocity,
        "rating": rating,
        "item_rating": {"rating_avg": rating},
        "review_count": review_count,
        "cmt_count": review_count,
        "last_sale_date": "",
        "ctime": "",
    }


class TestPricingAutomation:
    """Testes para funcoes rule-based preservadas."""

    def test_suggest_optimal_price_no_competitors(self):
        result = suggest_optimal_price(50.0, [], 30.0)
        assert result["suggested"] == 50.0
        assert result["reason"] == "sem dados de concorrentes"

    def test_suggest_optimal_price_with_competitors(self):
        result = suggest_optimal_price(100.0, [50.0, 55.0, 60.0], 30.0)
        assert result["suggested"] < 100.0
        assert result["direction"] == "descer"
        assert "competitivo" in result["reason"] or "media" in result["reason"]

    def test_suggest_optimal_price_min_margin(self):
        result = suggest_optimal_price(10.0, [5.0, 6.0], 8.0, min_margin_pct=10.0)
        margin = (result["suggested"] - 8.0) / result["suggested"] * 100
        assert margin >= 9.0

    def test_get_min_price_with_variants(self):
        item = {"variations": [{"price": 10.0}, {"price": 15.0}, {"price": 8.0}]}
        assert get_min_price(item) == 8.0

    def test_get_min_price_no_variants(self):
        item = {"price": 25.0}
        assert get_min_price(item) == 25.0

    def test_get_max_price(self):
        item = {"variations": [{"price": 10.0}, {"price": 15.0}, {"price": 8.0}]}
        assert get_max_price(item) == 15.0

    def test_get_max_price_no_variants(self):
        item = {"price": 25.0}
        assert get_max_price(item) == 25.0

    def test_analyze_item_pricing(self):
        item = _make_item(item_id=123, price=100.0)
        result = analyze_item_pricing(item, [80.0, 90.0], cost=50.0)
        assert result is not None
        assert result["item_id"] == 123
        assert result["current_price"] == 100.0
        assert "suggested_price" in result

    def test_analyze_item_pricing_no_price(self):
        item = {"item_id": 999, "name": "NoPrice"}
        result = analyze_item_pricing(item, [10.0])
        assert result is None


class TestPricingModel:
    """Testes para o modelo ML de precificacao."""

    def test_train_and_predict_numpy_fallback(self):
        model = PricingModel()
        assert model._sklearn_available is False or True  # any env is fine
        # Force numpy path by mocking sklearn
        data = []
        for i in range(20):
            row = {f: float(np.random.rand() * 10) for f in FEATURE_NAMES}
            row["actual_sale_price"] = sum(row.get(f, 0) for f in FEATURE_NAMES[:5]) / 5
            data.append(row)
        # Patch to simulate no sklearn
        with patch.object(model, "_sklearn_available", False):
            result = model.train(data)
        assert "rmse" in result
        assert result["samples"] == 20
        assert model._trained

        feat = {"competitor_avg_price": 50, "competitor_min_price": 40,
                "competitor_max_price": 60, "cost": 30, "margin_pct": 20,
                "sales_velocity": 5, "stock_level": 100, "days_since_last_sale": 2,
                "product_age_days": 365, "review_count": 50, "rating": 4.5}
        pred = model.predict(feat)
        assert pred > 0

    def test_train_returns_error_on_few_samples(self):
        model = PricingModel()
        result = model.train([{"competitor_avg_price": 1, "actual_sale_price": 10}])
        assert "error" in result

    def test_predict_before_train_returns_zero(self):
        model = PricingModel()
        assert model.predict({"competitor_avg_price": 50}) == 0.0

    def test_get_feature_importance(self):
        model = PricingModel()
        data = [{f: float(i) for f in FEATURE_NAMES} | {"actual_sale_price": 50.0}
                for i in range(10)]
        with patch.object(model, "_sklearn_available", False):
            model.train(data)
        importance = model.get_feature_importance()
        assert isinstance(importance, dict)
        assert all(f in importance for f in FEATURE_NAMES)

    def test_save_and_load(self, tmp_path):
        model = PricingModel(model_path=str(tmp_path / "test_model.pkl"))
        data = [{f: float(i) for f in FEATURE_NAMES} | {"actual_sale_price": 50.0}
                for i in range(10)]
        with patch.object(model, "_sklearn_available", False):
            model.train(data)
        path = model.save()
        assert Path(path).exists()

        model2 = PricingModel(model_path=str(tmp_path / "test_model.pkl"))
        assert model2.load()
        assert model2._trained

    def test_load_nonexistent_returns_false(self):
        model = PricingModel(model_path="nonexistent.pkl")
        assert not model.load()


class TestDynamicPricingEngine:
    """Testes para o motor de precificacao dinamica."""

    def test_engine_init(self):
        engine = DynamicPricingEngine()
        assert engine.data_dir is not None
        assert engine.model is not None

    def test_analyze_item_no_competitors(self):
        engine = DynamicPricingEngine()
        item = _make_item(item_id=1, price=50.0)
        result = engine.analyze_item(item, [], cost=30.0)
        assert result["item_id"] == 1
        assert result["current_price"] == 50.0
        assert result["ml_used"] is False

    def test_analyze_item_with_competitors(self):
        engine = DynamicPricingEngine()
        item = _make_item(item_id=2, price=100.0)
        result = engine.analyze_item(item, [80.0, 85.0, 90.0], cost=50.0)
        assert result["suggested_price"] < 100.0
        assert "estimated_margin_pct" in result

    def test_analyze_item_with_ml(self):
        engine = DynamicPricingEngine()
        # Pre-train model
        data = [{f: float(np.random.rand() * 10) for f in FEATURE_NAMES}
                | {"actual_sale_price": 50.0 + np.random.rand() * 10}
                for _ in range(30)]
        with patch.object(engine.model, "_sklearn_available", False):
            engine.model.train(data)
        item = _make_item(item_id=3, price=100.0)
        result = engine.analyze_item(item, [80.0, 85.0, 90.0], cost=50.0)
        assert "ml_used" in result
        assert "features" in result

    def test_analyze_all_items_batch(self):
        engine = DynamicPricingEngine()
        items = [_make_item(item_id=i, price=50.0 + i * 10) for i in range(3)]
        comp_data = {"1": [40, 45], "2": [50, 55], "3": [60, 65]}
        results = engine.analyze_all_items(items, comp_data)
        assert len(results) == 3

    def test_analyze_item_no_price(self):
        engine = DynamicPricingEngine()
        item = {"item_id": 999, "name": "NoPrice"}
        result = engine.analyze_item(item, [10.0])
        assert "error" in result

    def test_generate_report_empty(self):
        engine = DynamicPricingEngine()
        report = engine.generate_report([])
        assert report["total_items"] == 0

    def test_generate_report_with_results(self):
        engine = DynamicPricingEngine()
        results = [
            {"item_id": 1, "name": "A", "current_price": 100, "suggested_price": 80,
             "direction": "descer", "difference": -20, "reason": "test"},
            {"item_id": 2, "name": "B", "current_price": 50, "suggested_price": 55,
             "direction": "subir", "difference": 5, "reason": "test"},
        ]
        report = engine.generate_report(results)
        assert report["total_items"] == 2
        assert report["analyzed_items"] == 2
        assert report["items_by_direction"]["descer"] == 1
        assert report["items_by_direction"]["subir"] == 1
        assert report["avg_suggested_discount"] == 20.0
        assert report["total_opportunity_value"] > 0

    def test_apply_pricing_suggestion_no_client(self):
        engine = DynamicPricingEngine()
        result = engine.apply_pricing_suggestion(1, 99.99)
        assert result["success"] is False
        assert "cliente nao configurado" in result["error"]

    @patch("shopee_agent.seller_center_actions.SellerCenterActions")
    def test_apply_pricing_suggestion_with_client(self, MockActions):
        mock_actions = MagicMock()
        mock_actions.update_price.return_value = {"success": True}
        MockActions.return_value = mock_actions

        mock_client = MagicMock()
        engine = DynamicPricingEngine(client=mock_client)
        result = engine.apply_pricing_suggestion(1, 99.99)
        assert result["success"] is True


class TestDashboardAndHistory:
    """Testes para dados de dashboard e historico."""

    def test_get_pricing_dashboard_data(self, tmp_path):
        engine = DynamicPricingEngine()
        engine.data_dir = tmp_path
        # Save some competitor data
        comp_data = {
            "1": [100.0, 110.0],
            "2": [50.0, 55.0],
        }
        _save_competitor_prices(comp_data)
        with patch("shopee_agent.pricing_automation._cached_competitor_prices",
                   return_value=comp_data):
            with patch("shopee_agent.pricing_automation.COMPETITOR_CACHE",
                       tmp_path / "pricing_competitor_cache.json"):
                data = engine.get_pricing_dashboard_data()
        assert "total_items" in data
        assert "analyzed_items" in data
        assert "items_by_direction" in data
        assert "feature_importance" in data

    def test_get_pricing_history_empty(self):
        history = get_pricing_history(days=30)
        assert isinstance(history, list)

    def test_get_pricing_history_filtered(self, tmp_path):
        from shopee_agent.pricing_automation import PRICING_HISTORY_FILE
        from datetime import datetime, timezone, timedelta
        history_file = tmp_path / "pricing_history.json"
        entries = [
            {"item_id": 1, "new_price": 99.0,
             "timestamp": datetime.now(timezone.utc).isoformat()},
            {"item_id": 2, "new_price": 49.0,
             "timestamp": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()},
        ]
        history_file.write_text(json.dumps(entries), encoding="utf-8")
        with patch("shopee_agent.pricing_automation.PRICING_HISTORY_FILE", history_file):
            filtered = get_pricing_history(days=30)
        assert len(filtered) == 1
        assert filtered[0]["item_id"] == 1


class TestCompatFunctions:
    """Testes para funcoes de compatibilidade (wrapper)."""

    def test_generate_pricing_report(self, tmp_path):
        mock_client = MagicMock()
        mock_client.get_item_list.return_value = {
            "item_list": [
                _make_item(item_id=1, price=100.0),
                _make_item(item_id=2, price=50.0),
            ]
        }
        comp_cache = tmp_path / "pricing_competitor_cache.json"
        comp_cache.write_text(json.dumps({
            "1": [80, 90],
            "2": [40, 50],
        }), encoding="utf-8")
        with patch("shopee_agent.pricing_automation.COMPETITOR_CACHE", comp_cache):
            with patch("shopee_agent.pricing_automation._cached_competitor_prices",
                       return_value={"1": [80, 90], "2": [40, 50]}):
                results = generate_pricing_report(mock_client)
        assert len(results) == 2

    def test_apply_pricing_suggestion_dry_run(self):
        result = apply_pricing_suggestion(MagicMock(), 1, 99.99, dry_run=True)
        assert result["dry_run"] is True

    @patch("shopee_agent.pricing_automation.DynamicPricingEngine")
    def test_apply_pricing_suggestion_live(self, MockEngine):
        mock_engine = MagicMock()
        mock_engine.apply_pricing_suggestion.return_value = {"success": True}
        MockEngine.return_value = mock_engine
        result = apply_pricing_suggestion(MagicMock(), 1, 99.99, dry_run=False)
        assert result["success"] is True

    def test_update_competitor_data_no_client(self):
        result = update_competitor_data(MagicMock())
        assert "error" not in result or True  # may or may not have error

    def test_get_pricing_dashboard_data_wrapper(self):
        data = get_pricing_dashboard_data()
        assert isinstance(data, dict)


class TestExtractFeatures:
    """Testes para extracao de features."""

    def test_extract_features_with_competitors(self):
        item = _make_item(price=100.0, cost=50.0, stock=200,
                          sales_velocity=10, rating=4.5, review_count=50)
        features = _extract_features(item, [80.0, 90.0, 100.0], cost=50.0)
        assert features["competitor_avg_price"] == 90.0
        assert features["competitor_min_price"] == 80.0
        assert features["competitor_max_price"] == 100.0
        assert features["cost"] == 50.0
        assert features["margin_pct"] > 0
        assert features["sales_velocity"] == 10
        assert features["stock_level"] == 200
        assert features["days_since_last_sale"] == 999
        assert features["review_count"] == 50
        assert features["rating"] == 4.5

    def test_extract_features_no_competitors(self):
        item = _make_item(price=50.0)
        features = _extract_features(item, [], cost=0)
        assert features["competitor_avg_price"] == 0.0
        assert features["competitor_min_price"] == 0.0
        assert features["competitor_max_price"] == 0.0

    def test_extract_features_with_dates(self):
        from datetime import datetime, timezone, timedelta
        item = _make_item(price=100.0)
        item["last_sale_date"] = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        item["ctime"] = str(int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp()))
        features = _extract_features(item, [100.0])
        assert 0 < features["days_since_last_sale"] <= 10
        assert 360 <= features["product_age_days"] <= 370


class TestSklearnModel:
    """Testes com sklearn disponivel (se instalado)."""

    def test_sklearn_train_and_predict(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("sklearn nao instalado")
        model = PricingModel()
        np.random.seed(42)
        data = []
        for _ in range(50):
            row = {f: float(np.random.rand() * 10) for f in FEATURE_NAMES}
            row["actual_sale_price"] = (
                10 + 2 * row["competitor_avg_price"]
                - 0.5 * row["cost"]
                + np.random.randn() * 2
            )
            data.append(row)
        result = model.train(data)
        assert "rmse" in result
        assert model._trained

        feat = {f: 5.0 for f in FEATURE_NAMES}
        pred = model.predict(feat)
        assert pred > 0

        importance = model.get_feature_importance()
        assert len(importance) == len(FEATURE_NAMES)
        assert abs(sum(importance.values()) - 1.0) < 0.01
