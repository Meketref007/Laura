from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import PRODUCT_CATALOG


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _split_terms(value: Any) -> list[str]:
    text = _normalize_text(value)
    if not text:
        return []
    return [token for token in re.split(r"[^a-z0-9áàâãéêíóôõúç]+", text) if token]


@dataclass
class CatalogItem:
    item_id: str
    item_name: str
    description: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    current_price: float | None = None
    weekly_sales: float | None = None
    weekly_growth_pct: float | None = None
    image_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ListingInsight:
    item_id: str
    item_name: str
    score: float
    signals: list[str]
    recommendations: list[str]
    cross_sell_candidates: list[str]
    upsell_candidates: list[str]
    seo_terms: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BrandingGrowthSnapshot:
    generated_at: str
    total_items: int
    average_score: float
    top_items: list[dict[str, Any]]
    weak_items: list[dict[str, Any]]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BrandingGrowthAnalyzer:
    """Simple listing and growth analyzer for Phase 42."""

    def __init__(self, catalog_path: str = str(PRODUCT_CATALOG)):
        self.catalog_path = Path(catalog_path)

    def load_catalog(self, limit: int | None = None) -> list[CatalogItem]:
        path = self.catalog_path
        if not path.exists():
            return []

        items: list[CatalogItem] = []
        raw_text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(raw_text)
            except Exception:
                return []
            rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                items.append(self._item_from_payload(row))
                if limit is not None and len(items) >= limit:
                    break
            return items

        for raw_line in raw_text.splitlines():
            if limit is not None and len(items) >= limit:
                break
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            items.append(self._item_from_payload(payload))
        return items

    def _item_from_payload(self, payload: dict[str, Any]) -> CatalogItem:
        return CatalogItem(
            item_id=str(payload.get("item_id") or payload.get("id") or ""),
            item_name=str(payload.get("item_name") or payload.get("name") or payload.get("title") or ""),
            description=str(payload.get("description") or payload.get("desc") or ""),
            category=str(payload.get("category") or payload.get("item_category") or ""),
            tags=[str(tag) for tag in payload.get("tags", []) if str(tag).strip()] if isinstance(payload.get("tags"), list) else [],
            current_price=self._float_or_none(payload.get("current_price") or payload.get("sale_price") or payload.get("price")),
            weekly_sales=self._float_or_none(payload.get("weekly_sales") or payload.get("sales_weekly") or payload.get("units_sold_weekly")),
            weekly_growth_pct=self._float_or_none(payload.get("weekly_growth_pct") or payload.get("growth_pct")),
            image_count=self._int_or_none(payload.get("image_count") or payload.get("images_count") or payload.get("photos_count")),
        )

    def analyze(self, limit: int | None = None) -> list[ListingInsight]:
        items = self.load_catalog(limit=limit)
        insights: list[ListingInsight] = []
        for item in items:
            insights.append(self._analyze_item(item))
        return insights

    def snapshot(self, limit: int | None = None) -> BrandingGrowthSnapshot:
        insights = self.analyze(limit=limit)
        scores = [insight.score for insight in insights]
        recommendations: list[str] = []
        for insight in insights[:5]:
            recommendations.extend(insight.recommendations[:2])

        return BrandingGrowthSnapshot(
            generated_at=_utc_now().isoformat(),
            total_items=len(insights),
            average_score=sum(scores) / len(scores) if scores else 0.0,
            top_items=[insight.to_dict() for insight in sorted(insights, key=lambda item: item.score, reverse=True)[:5]],
            weak_items=[insight.to_dict() for insight in sorted(insights, key=lambda item: item.score)[:5]],
            recommendations=list(dict.fromkeys(recommendations)),
        )

    def _analyze_item(self, item: CatalogItem) -> ListingInsight:
        title_terms = _split_terms(item.item_name)
        description_terms = _split_terms(item.description)
        tags = [_normalize_text(tag) for tag in item.tags if _normalize_text(tag)]
        all_terms = title_terms + description_terms + tags

        signals: list[str] = []
        recommendations: list[str] = []
        seo_terms: list[str] = []
        score = 50.0

        if len(title_terms) >= 4:
            score += 10.0
        else:
            score -= 8.0
            recommendations.append("Expandir o titulo com atributos principais e beneficio")
            signals.append("short_title")

        if len(description_terms) >= 20:
            score += 10.0
        elif description_terms:
            score += 3.0
            recommendations.append("Aumentar a descricao com usos, tamanho e prova social")
        else:
            score -= 10.0
            recommendations.append("Adicionar descricao detalhada com palavras-chave e beneficio")
            signals.append("missing_description")

        if item.image_count is not None:
            if item.image_count >= 4:
                score += 8.0
            else:
                score -= 4.0
                recommendations.append("Adicionar mais imagens do produto e detalhes visuais")
                signals.append("few_images")

        if item.weekly_growth_pct is not None:
            if item.weekly_growth_pct >= 10:
                score += 8.0
                recommendations.append("Aproveitar o crescimento com bundles e upsell")
                signals.append("growth_candidate")
            elif item.weekly_growth_pct < 0:
                score -= 6.0
                recommendations.append("Revisar posicionamento e prova de valor do listing")
                signals.append("declining_listing")

        if item.current_price is not None:
            if item.current_price >= 100:
                score += 2.0
                recommendations.append("Criar oferta de upgrade ou bundle premium")
            else:
                recommendations.append("Criar cross-sell de entrada com acessorios ou kits")

        if item.category:
            seo_terms.extend(_split_terms(item.category))

        if tags:
            seo_terms.extend(tags[:5])

        if len(all_terms) < 15:
            seo_terms.extend(["beneficio", "qualidade", "oferta"])

        cross_sell_candidates = self._cross_sell_candidates(item, all_terms)
        upsell_candidates = self._upsell_candidates(item, all_terms)

        if cross_sell_candidates:
            score += 4.0
        if upsell_candidates:
            score += 4.0

        score = max(0.0, min(100.0, score))
        if not recommendations:
            recommendations.append("Manter o listing atual e testar variantes de titulo")

        return ListingInsight(
            item_id=item.item_id,
            item_name=item.item_name,
            score=score,
            signals=signals,
            recommendations=list(dict.fromkeys(recommendations)),
            cross_sell_candidates=cross_sell_candidates,
            upsell_candidates=upsell_candidates,
            seo_terms=list(dict.fromkeys(term for term in seo_terms if term)),
        )

    def _cross_sell_candidates(self, item: CatalogItem, terms: list[str]) -> list[str]:
        candidates: list[str] = []
        if any(term in terms for term in {"case", "capa", "cover", "kit", "bundle"}):
            candidates.extend(["acessorios complementares", "reposicao", "kits de presente"])
        elif item.current_price is not None and item.current_price < 80:
            candidates.extend(["frete combinado", "produto de entrada", "complemento de pedido"])
        else:
            candidates.extend(["acessorio complementar", "bundle com item principal"])
        return list(dict.fromkeys(candidates))

    def _upsell_candidates(self, item: CatalogItem, terms: list[str]) -> list[str]:
        candidates: list[str] = []
        if item.current_price is not None and item.current_price < 120:
            candidates.append("versao premium")
        if any(term in terms for term in {"basic", "basico", "entry", "simples"}):
            candidates.append("versao advanced ou premium")
        if item.weekly_growth_pct is not None and item.weekly_growth_pct >= 8:
            candidates.append("bundle de maior valor")
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except Exception:
            return None
