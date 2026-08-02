"""Precificacao automatica - ML-based dynamic pricing engine com fallback rule-based."""
from __future__ import annotations

import json
import os
import pickle
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from shopee_agent.logger import info, warning

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
PRICING_FILE = REPORTS_DIR / "pricing_suggestions.json"
COMPETITOR_CACHE = REPORTS_DIR / "pricing_competitor_cache.json"
PRICING_HISTORY_FILE = REPORTS_DIR / "pricing_history.json"


# ── helpers ──────────────────────────────────────────────────────────────────

def _cached_competitor_prices() -> dict:
    try:
        if COMPETITOR_CACHE.exists():
            return json.loads(COMPETITOR_CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_competitor_prices(data: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    COMPETITOR_CACHE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_pricing_history() -> list[dict]:
    try:
        if PRICING_HISTORY_FILE.exists():
            return json.loads(PRICING_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _append_pricing_history(entry: dict) -> None:
    history = _load_pricing_history()
    history.append(entry)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PRICING_HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── feature engineering ──────────────────────────────────────────────────────

FEATURE_NAMES = [
    "competitor_avg_price",
    "competitor_min_price",
    "competitor_max_price",
    "cost",
    "margin_pct",
    "sales_velocity",
    "stock_level",
    "days_since_last_sale",
    "product_age_days",
    "review_count",
    "rating",
]


def _extract_features(item: dict, competitor_prices: list[float], cost: float = 0) -> dict:
    """Extract feature vector from an item dict."""
    avg_comp = float(np.mean(competitor_prices)) if competitor_prices else 0.0
    min_comp = float(np.min(competitor_prices)) if competitor_prices else 0.0
    max_comp = float(np.max(competitor_prices)) if competitor_prices else 0.0
    price = item.get("price", item.get("original_price", 0))
    margin_pct = ((price - cost) / price * 100) if price > 0 else 0
    sales_velocity = float(item.get("sales_velocity", item.get("daily_sales", 0)))
    stock_level = float(item.get("stock", item.get("stock_level", 0)))
    now = datetime.now(UTC)
    last_sale_str = item.get("last_sale_date", "")
    if last_sale_str:
        try:
            last_sale = datetime.fromisoformat(last_sale_str)
            if last_sale.tzinfo is None:
                last_sale = last_sale.replace(tzinfo=UTC)
            days_since = (now - last_sale).days
        except Exception:
            days_since = 999
    else:
        days_since = 999
    created_str = item.get("created_at", item.get("ctime", ""))
    if created_str:
        try:
            if "T" in created_str:
                created = datetime.fromisoformat(created_str)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
            else:
                created = datetime.fromtimestamp(int(created_str), tz=UTC)
            product_age = (now - created).days
        except Exception:
            product_age = 0
    else:
        product_age = 0
    review_count = float(item.get("review_count", item.get("cmt_count", 0)))
    rating = float(item.get("rating", item.get("item_rating", {}).get("rating_avg", 0)))
    return {
        "competitor_avg_price": avg_comp,
        "competitor_min_price": min_comp,
        "competitor_max_price": max_comp,
        "cost": float(cost),
        "margin_pct": margin_pct,
        "sales_velocity": sales_velocity,
        "stock_level": stock_level,
        "days_since_last_sale": float(days_since),
        "product_age_days": float(product_age),
        "review_count": review_count,
        "rating": rating,
    }


# ── PricingModel (ML-based) ──────────────────────────────────────────────────

class PricingModel:
    """Modelo de precificacao baseado em ML (RandomForest / regressao linear)."""

    def __init__(self, model_path: str | Path = "reports/pricing_model.pkl") -> None:
        self.model_path = Path(model_path)
        self._model: Any = None
        self._feature_importance: dict[str, float] = {}
        self._trained = False
        self._sklearn_available = False
        self._check_sklearn()

    def _check_sklearn(self) -> None:
        try:
            import sklearn  # noqa: F401
            self._sklearn_available = True
        except ImportError:
            self._sklearn_available = False

    def train(self, historical_data: list[dict]) -> dict:
        """Treina o modelo com dados historicos de precificacao.

        Cada dict deve conter as features + chave 'actual_sale_price'.
        Retorna metrica de erro (RMSE).
        """
        if len(historical_data) < 5:
            return {"error": "poucos dados para treino", "samples": len(historical_data)}

        X_list, y_list = [], []
        for row in historical_data:
            vec = [row.get(f, 0) for f in FEATURE_NAMES]
            X_list.append(vec)
            y_list.append(row.get("actual_sale_price", 0))

        X = np.array(X_list, dtype=np.float64)
        y = np.array(y_list, dtype=np.float64)

        if self._sklearn_available:
            return self._train_sklearn(X, y)
        return self._train_numpy(X, y)

    def _train_sklearn(self, X: np.ndarray, y: np.ndarray) -> dict:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.metrics import mean_squared_error
        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        self._model = RandomForestRegressor(
            n_estimators=100, max_depth=10, random_state=42, n_jobs=-1
        )
        self._model.fit(X_train, y_train)
        preds = self._model.predict(X_test)
        rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
        self._feature_importance = dict(
            zip(FEATURE_NAMES, self._model.feature_importances_, strict=False)
        )
        self._trained = True
        return {"model": "RandomForestRegressor", "rmse": round(rmse, 4), "samples": len(y)}

    def _train_numpy(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Regressao linear via numpy (pseudoinversa)."""
        X_aug = np.c_[np.ones(X.shape[0]), X]
        try:
            coeffs = np.linalg.pinv(X_aug.T @ X_aug) @ X_aug.T @ y
        except np.linalg.LinAlgError:
            coeffs = np.zeros(X_aug.shape[1])
        self._model = coeffs
        preds = X_aug @ coeffs
        rmse = float(np.sqrt(np.mean((y - preds) ** 2)))
        # feature importance = absolute coefficient magnitude (normalized)
        abs_coeff = np.abs(coeffs[1:])
        total = abs_coeff.sum()
        self._feature_importance = dict(
            zip(FEATURE_NAMES, (abs_coeff / total).tolist() if total > 0 else [], strict=False)
        )
        self._trained = True
        return {"model": "LinearRegression_numpy", "rmse": round(rmse, 4), "samples": len(y)}

    def predict(self, features: dict) -> float:
        """Prediz o preco otimo baseado nas features."""
        if not self._trained or self._model is None:
            return 0.0
        vec = np.array([[features.get(f, 0) for f in FEATURE_NAMES]], dtype=np.float64)
        if self._sklearn_available and hasattr(self._model, "predict"):
            pred = float(self._model.predict(vec)[0])
        else:
            coeffs = self._model
            pred = float((coeffs[0] + vec @ coeffs[1:]).item())
        return round(max(pred, 0.01), 2)

    def get_feature_importance(self) -> dict[str, float]:
        return dict(self._feature_importance)

    def save(self) -> str:
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model": self._model,
            "feature_importance": self._feature_importance,
            "trained": self._trained,
            "sklearn": self._sklearn_available,
        }
        with open(self.model_path, "wb") as f:
            pickle.dump(data, f)
        return str(self.model_path)

    def load(self) -> bool:
        if not self.model_path.exists():
            return False
        try:
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._feature_importance = data["feature_importance"]
            self._trained = data["trained"]
            self._sklearn_available = data.get("sklearn", False)
            return True
        except Exception:
            return False


# ── original rule-based functions (preserved) ───────────────────────────────

def get_min_price(item: dict) -> float:
    """Retorna o menor preco valido considerando variacoes."""
    variants = item.get("variations", [])
    if variants:
        return min(v.get("price", v.get("original_price", 0)) for v in variants)
    return item.get("price", item.get("original_price", 0))


def get_max_price(item: dict) -> float:
    variants = item.get("variations", [])
    if variants:
        return max(v.get("price", v.get("original_price", 0)) for v in variants)
    return item.get("price", item.get("original_price", 0))


def suggest_optimal_price(
    my_price: float,
    competitor_prices: list[float],
    my_cost: float = 0,
    target_margin_pct: float = 20.0,
    min_margin_pct: float = 10.0,
) -> dict:
    """Sugere preco otimo baseado em concorrencia e margem."""
    if not competitor_prices:
        return {"suggested": my_price, "reason": "sem dados de concorrentes"}

    avg_comp = sum(competitor_prices) / len(competitor_prices)
    min_comp = min(competitor_prices)
    max_comp = max(competitor_prices)

    suggested = round((my_price + avg_comp) / 2, 2)
    reason = ""

    if my_cost > 0:
        margin = (suggested - my_cost) / suggested * 100 if suggested > 0 else 0
        if margin < min_margin_pct:
            suggested = round(my_cost / (1 - min_margin_pct / 100), 2)
            reason = "margem minima"
        elif margin > target_margin_pct * 2:
            suggested = round(my_price * 0.95, 2)
            reason = "preco muito acima da media"
        else:
            reason = f"preco competitivo (media concorrentes: {avg_comp})"
    else:
        reason = "custo desconhecido, baseado em concorrencia"

    direction = "subir" if suggested > my_price else "descer" if suggested < my_price else "manter"
    return {
        "suggested": suggested,
        "current": my_price,
        "difference": round(suggested - my_price, 2),
        "direction": direction,
        "reason": reason,
        "competitor_avg": round(avg_comp, 2),
        "competitor_min": round(min_comp, 2),
        "competitor_max": round(max_comp, 2),
    }


def update_competitor_data(seller_client) -> dict:
    """Atualiza dados de concorrentes para todos os produtos via search scraper."""
    from shopee_agent.shopee_search_scraper import batch_update
    try:
        getter = getattr(seller_client, "get_products", None) or getattr(seller_client, "get_item_list", None)
        raw = getter(limit=200)
        all_items = raw if isinstance(raw, list) else raw.get("item_list", raw.get("items", []))
        results = batch_update(all_items)
        return {
            "updated": len(results),
            "total_competitors": sum(r.get("competitors_found", 0) for r in results),
        }
    except Exception as e:
        return {"error": str(e)}


# ── DynamicPricingEngine ────────────────────────────────────────────────────

class DynamicPricingEngine:
    """Motor de precificacao dinamica com suporte a ML."""

    def __init__(self, client=None, data_dir: str = "reports") -> None:
        self.client = client
        self.data_dir = Path(data_dir)
        self.model = PricingModel(model_path=str(self.data_dir / "pricing_model.pkl"))
        self.model.load()
        self.max_price_change_pct = 20  # safety limit: never change price by more than 20%

    # ── analise individual ──────────────────────────────────────────────────

    def analyze_item(
        self,
        item: dict,
        competitor_prices: list[float],
        cost: float = 0,
    ) -> dict:
        """Analise completa com ML + rule-based fallback."""
        item_id = item.get("item_id")
        name = item.get("item_name", item.get("name", "?"))
        my_price = get_min_price(item)
        if not my_price:
            return {"item_id": item_id, "name": name, "error": "sem preco"}

        features = _extract_features(item, competitor_prices, cost)
        ml_price = self.model.predict(features) if self.model._trained else 0.0

        if ml_price > 0 and competitor_prices:
            suggested = round(ml_price, 2)
            reason = "preco otimizado por ML"
        else:
            rule = suggest_optimal_price(my_price, competitor_prices, cost)
            suggested = rule["suggested"]
            reason = rule["reason"]

        direction = "subir" if suggested > my_price else "descer" if suggested < my_price else "manter"
        avg_comp = float(np.mean(competitor_prices)) if competitor_prices else 0.0

        result = {
            "item_id": item_id,
            "name": name,
            "current_price": my_price,
            "suggested_price": suggested,
            "direction": direction,
            "difference": round(suggested - my_price, 2),
            "reason": reason,
            "competitor_avg": round(avg_comp, 2),
            "competitor_min": round(min(competitor_prices), 2) if competitor_prices else 0,
            "competitor_max": round(max(competitor_prices), 2) if competitor_prices else 0,
            "features": features,
            "ml_used": bool(ml_price > 0 and self.model._trained),
        }

        if cost > 0:
            margin = (suggested - cost) / suggested * 100 if suggested > 0 else 0
            result["estimated_margin_pct"] = round(margin, 2)

        return result

    # ── analise batch ───────────────────────────────────────────────────────

    def analyze_all_items(
        self,
        items: list[dict],
        competitor_data: dict | None = None,
    ) -> list[dict]:
        """Analisa todos os itens com dados de concorrentes."""
        if competitor_data is None:
            competitor_data = _cached_competitor_prices()
        results = []
        for item in items:
            item_id = str(item.get("item_id", ""))
            comp_prices = competitor_data.get(item_id, [])
            cost = float(item.get("cost", item.get("cost_price", 0)))
            analysis = self.analyze_item(item, comp_prices, cost)
            results.append(analysis)
        return results

    # ── geracao de relatorio ────────────────────────────────────────────────

    def generate_report(
        self, analysis_results: list[dict]
    ) -> dict:
        """Gera relatorio estruturado a partir dos resultados de analise."""
        total = len(analysis_results)
        if total == 0:
            return {"total_items": 0, "message": "nenhum item analisado"}

        directions = defaultdict(int)
        total_discount = 0.0
        discount_count = 0
        opportunity_value = 0.0
        analyzed = 0
        top_opportunities: list[dict] = []

        for r in analysis_results:
            if "error" in r:
                continue
            analyzed += 1
            directions[r.get("direction", "manter")] += 1
            diff = r.get("difference", 0)
            if diff < 0:
                total_discount += abs(diff)
                discount_count += 1
                opportunity_value += abs(diff) * 30  # estimativa 30d de ganho
                top_opportunities.append(r)

        top_opportunities.sort(key=lambda x: abs(x.get("difference", 0)), reverse=True)

        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_items": total,
            "analyzed_items": analyzed,
            "items_by_direction": dict(directions),
            "avg_suggested_discount": round(total_discount / discount_count, 2)
            if discount_count > 0
            else 0.0,
            "total_opportunity_value": round(opportunity_value, 2),
            "top_opportunities": top_opportunities[:10],
            "ml_model_trained": self.model._trained,
        }
        return report

    # ── aplicar precos ──────────────────────────────────────────────────────

    def apply_pricing_suggestion(
        self, item_id: int, new_price: float, variation_id: int | None = None
    ) -> dict:
        """Aplica o preco sugerido via client API (efeito real se dry-run=false)."""
        if self.client is None:
            return {
                "success": False,
                "error": "cliente nao configurado",
                "dry_run": True,
            }
        try:
            from shopee_agent.seller_center_actions import SellerCenterActions
            actions = SellerCenterActions(self.client)
            result = actions.update_price(item_id, new_price, variation_id)
            if result.get("success"):
                _append_pricing_history({
                    "item_id": item_id,
                    "old_price": None,
                    "new_price": new_price,
                    "variation_id": variation_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "source": "dynamic_pricing_engine",
                })
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── apply all suggestions ──────────────────────────────────────────────

    def apply_all_suggestions(self, items=None, competitor_data=None, dry_run=True) -> dict:
        """Analyze all items and apply price suggestions.
        If dry_run=True (default), only logs what would be done.
        If dry_run=False, actually applies the prices via client API.
        Safety: never changes price by more than max_price_change_pct.
        Returns summary dict with applied/skipped/errors counts.
        """
        if competitor_data is None:
            competitor_data = _cached_competitor_prices()
        if items is None:
            items = []
        suggestions = self.analyze_all_items(items, competitor_data)

        applied = 0
        skipped = 0
        errors = 0
        total_revenue_impact = 0.0

        for sug in suggestions:
            if "error" in sug:
                skipped += 1
                continue
            item_id = sug.get("item_id")
            current_price = sug.get("current_price", 0)
            suggested_price = sug.get("suggested_price", 0)
            if current_price <= 0 or suggested_price <= 0:
                skipped += 1
                continue

            change_pct = abs((suggested_price - current_price) / current_price) * 100
            if change_pct > self.max_price_change_pct:
                clamped = current_price * (1 + (self.max_price_change_pct / 100) * (1 if suggested_price > current_price else -1))
                info(
                    f"Price change {change_pct:.1f}% exceeds safety limit {self.max_price_change_pct}% for item {item_id}, "
                    f"clamping {current_price} -> {clamped:.2f} (was {suggested_price})"
                )
                suggested_price = round(clamped, 2)
                change_pct = self.max_price_change_pct

            if dry_run:
                info(
                    f"[DRY RUN] Would update item {item_id}: {current_price} -> {suggested_price} "
                    f"(change: {change_pct:.1f}%, reason: {sug.get('reason', '')})"
                )
                applied += 1
                total_revenue_impact += (suggested_price - current_price) * 30
            else:
                try:
                    result = self.apply_pricing_suggestion(int(item_id), suggested_price)
                    if result.get("success"):
                        applied += 1
                        total_revenue_impact += (suggested_price - current_price) * 30
                        info(f"Applied price for item {item_id}: {current_price} -> {suggested_price}")
                    else:
                        errors += 1
                        warning(f"Failed to apply price for item {item_id}: {result.get('error', 'unknown')}")
                except Exception as exc:
                    errors += 1
                    warning(f"Error applying price for item {item_id}: {exc}")

        summary = {
            "applied": applied,
            "skipped": skipped,
            "errors": errors,
            "total": len(suggestions),
            "estimated_revenue_impact": round(total_revenue_impact, 2),
            "dry_run": dry_run,
        }
        return summary

    # ── dashboard ──────────────────────────────────────────────────────────

    def get_pricing_dashboard_data(self) -> dict:
        """Retorna dados formatados para dashboard React."""
        history = _cached_competitor_prices()
        items = list(history.values())
        total_items = len(items)

        results = self.analyze_all_items(
            [{"item_id": k, "price": 0} for k in history],
            history,
        ) if total_items > 0 else []

        if results:
            report = self.generate_report(results)
        else:
            report = {
                "total_items": 0,
                "analyzed_items": 0,
                "items_by_direction": {},
                "avg_suggested_discount": 0.0,
                "total_opportunity_value": 0.0,
                "top_opportunities": [],
                "ml_model_trained": self.model._trained,
            }

        return {
            "total_items": total_items,
            "analyzed_items": report["analyzed_items"],
            "avg_suggested_discount": report["avg_suggested_discount"],
            "total_opportunity_value": report["total_opportunity_value"],
            "items_by_direction": report["items_by_direction"],
            "top_opportunities": report["top_opportunities"],
            "ml_model_trained": self.model._trained,
            "feature_importance": self.model.get_feature_importance(),
        }

    def get_pricing_history(self, days: int = 30) -> list[dict]:
        """Retorna historico de alteracoes de precos dos ultimos N dias."""
        all_history = _load_pricing_history()
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = []
        for entry in all_history:
            try:
                ts = datetime.fromisoformat(entry.get("timestamp", ""))
                if ts >= cutoff:
                    filtered.append(entry)
            except Exception:
                continue
        return filtered


# ── funcoes de compatibilidade (mantidas para API existente) ────────────────

def analyze_item_pricing(
    item: dict,
    competitor_prices: list[float],
    cost: float = 0,
    target_margin: float = 20.0,
) -> dict | None:
    """Analisa precificacao de um item (wrapper de compatibilidade)."""
    item_id = item.get("item_id")
    name = item.get("item_name", item.get("name", "?"))
    my_price = get_min_price(item)
    if not my_price:
        return None
    suggestion = suggest_optimal_price(my_price, competitor_prices, cost, target_margin)
    return {
        "item_id": item_id,
        "name": name,
        "current_price": my_price,
        "suggested_price": suggestion["suggested"],
        "direction": suggestion["direction"],
        "reason": suggestion["reason"],
        "competitor_avg": suggestion["competitor_avg"],
    }


def generate_pricing_report(seller_client) -> list[dict]:
    """Gera relatorio com sugestoes de precificacao (wrapper compatibilidade)."""
    engine = DynamicPricingEngine(client=seller_client)
    suggestions = []
    try:
        items = seller_client.get_item_list(limit=200)
        all_items = items.get("item_list", items.get("items", []))
        comp_cache = _cached_competitor_prices()
        for item in all_items:
            item_id = str(item.get("item_id", ""))
            comp_prices = comp_cache.get(item_id, [])
            cost = float(item.get("cost", item.get("cost_price", 0)))
            sug = engine.analyze_item(item, comp_prices, cost)
            if "error" not in sug:
                suggestions.append(sug)
    except Exception as e:
        print(f"[PricingAutomation] error: {e}")
    return suggestions


def apply_pricing_suggestion(
    seller_client, item_id: int, new_price: float,
    variation_id: int | None = None, dry_run: bool = True,
) -> dict:
    """Aplica sugestao de preco via API do seller center."""
    if dry_run:
        return {
            "dry_run": True,
            "message": f"Preco de {item_id} para {new_price} (dry-run ativo)",
        }
    engine = DynamicPricingEngine(client=seller_client)
    return engine.apply_pricing_suggestion(item_id, new_price, variation_id)


def get_pricing_dashboard_data(seller_client=None) -> dict:
    """Retorna dados de dashboard (wrapper de compatibilidade)."""
    engine = DynamicPricingEngine(client=seller_client)
    return engine.get_pricing_dashboard_data()


def get_pricing_history(days: int = 30) -> list[dict]:
    """Retorna historico de alteracoes de precos (wrapper)."""
    all_history = _load_pricing_history()
    cutoff = datetime.now(UTC) - timedelta(days=days)
    filtered = []
    for entry in all_history:
        try:
            ts = datetime.fromisoformat(entry.get("timestamp", ""))
            if ts >= cutoff:
                filtered.append(entry)
        except Exception:
            continue
    return filtered
