from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import COMPETITIVE_OFFERS


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class CompetitorOffer:
    competitor_name: str
    item_id: str
    item_name: str
    competitor_price: float
    source: str = "manual"
    observed_at: str = field(default_factory=lambda: _utc_now().isoformat())
    our_price: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompetitiveSignal:
    item_id: str
    item_name: str
    signal_type: str
    our_price: float | None
    reference_price: float
    best_competitor_price: float
    gap_pct: float
    competitor_name: str
    observed_at: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompetitiveSnapshot:
    generated_at: str
    total_offers: int
    threat_count: int
    opportunity_count: int
    threats: list[dict[str, Any]]
    opportunities: list[dict[str, Any]]
    item_count: int
    average_gap_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CompetitiveIntelligence:
    """Minimal competitive intelligence store for Phase 41."""

    def __init__(self, path: str = str(COMPETITIVE_OFFERS)):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_offer(
        self,
        competitor_name: str,
        item_id: str,
        item_name: str,
        competitor_price: float,
        *,
        our_price: float | None = None,
        source: str = "manual",
        notes: list[str] | None = None,
    ) -> CompetitorOffer:
        offer = CompetitorOffer(
            competitor_name=competitor_name,
            item_id=item_id,
            item_name=item_name,
            competitor_price=float(competitor_price),
            our_price=float(our_price) if our_price is not None else None,
            source=source,
            notes=list(notes or []),
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(offer.to_dict(), ensure_ascii=False) + "\n")
        return offer

    def load_offers(self, limit: int | None = None) -> list[CompetitorOffer]:
        if not self.path.exists():
            return []

        offers: list[CompetitorOffer] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if limit is not None and len(offers) >= limit:
                    break
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue

                try:
                    offers.append(
                        CompetitorOffer(
                            competitor_name=str(payload.get("competitor_name", "")),
                            item_id=str(payload.get("item_id", "")),
                            item_name=str(payload.get("item_name", "")),
                            competitor_price=float(payload.get("competitor_price", 0.0)),
                            source=str(payload.get("source", "manual")),
                            observed_at=str(payload.get("observed_at", _utc_now().isoformat())),
                            our_price=float(payload["our_price"]) if payload.get("our_price") is not None else None,
                            notes=list(payload.get("notes", [])),
                        )
                    )
                except Exception:
                    continue
        return offers

    def snapshot(self, our_prices: dict[str, float] | None = None, limit: int | None = None) -> CompetitiveSnapshot:
        offers = self.load_offers(limit=limit)
        grouped: dict[str, list[CompetitorOffer]] = {}
        for offer in offers:
            if not offer.item_id:
                continue
            grouped.setdefault(offer.item_id, []).append(offer)

        threats: list[dict[str, Any]] = []
        opportunities: list[dict[str, Any]] = []
        gap_samples: list[float] = []

        for item_id, item_offers in grouped.items():
            prices = [offer.competitor_price for offer in item_offers if offer.competitor_price > 0]
            if not prices:
                continue

            item_name = next((offer.item_name for offer in item_offers if offer.item_name), item_id)
            competitor_name = min(item_offers, key=lambda offer: offer.competitor_price).competitor_name
            best_competitor_price = min(prices)
            median_price = statistics.median(prices)
            our_price = None if our_prices is None else our_prices.get(item_id)

            if our_price is not None and our_price > 0:
                reference_price = float(our_price)
                gap_pct = (reference_price - best_competitor_price) / reference_price
                gap_samples.append(gap_pct)
                if gap_pct >= 0.05:
                    threats.append(
                        CompetitiveSignal(
                            item_id=item_id,
                            item_name=item_name,
                            signal_type="threat",
                            our_price=reference_price,
                            reference_price=reference_price,
                            best_competitor_price=best_competitor_price,
                            gap_pct=gap_pct,
                            competitor_name=competitor_name,
                            observed_at=_utc_now().isoformat(),
                            reason="Competitor is materially cheaper than our price",
                        ).to_dict()
                    )
                elif gap_pct <= -0.08:
                    opportunities.append(
                        CompetitiveSignal(
                            item_id=item_id,
                            item_name=item_name,
                            signal_type="opportunity",
                            our_price=reference_price,
                            reference_price=reference_price,
                            best_competitor_price=best_competitor_price,
                            gap_pct=abs(gap_pct),
                            competitor_name=competitor_name,
                            observed_at=_utc_now().isoformat(),
                            reason="Our price is below the competitor baseline",
                        ).to_dict()
                    )
                continue

            # Fallback when our own price snapshot is unavailable.
            if len(prices) >= 2:
                threat_gap = (median_price - best_competitor_price) / median_price if median_price > 0 else 0.0
                if threat_gap >= 0.05:
                    threats.append(
                        CompetitiveSignal(
                            item_id=item_id,
                            item_name=item_name,
                            signal_type="threat",
                            our_price=None,
                            reference_price=median_price,
                            best_competitor_price=best_competitor_price,
                            gap_pct=threat_gap,
                            competitor_name=competitor_name,
                            observed_at=_utc_now().isoformat(),
                            reason="A competitor is undercutting the observed market median",
                        ).to_dict()
                    )

                max_price = max(prices)
                opportunity_gap = (max_price - median_price) / median_price if median_price > 0 else 0.0
                if opportunity_gap >= 0.08:
                    opportunities.append(
                        CompetitiveSignal(
                            item_id=item_id,
                            item_name=item_name,
                            signal_type="opportunity",
                            our_price=None,
                            reference_price=median_price,
                            best_competitor_price=max_price,
                            gap_pct=opportunity_gap,
                            competitor_name=competitor_name,
                            observed_at=_utc_now().isoformat(),
                            reason="Observed market spread suggests room for a premium or bundle move",
                        ).to_dict()
                    )

        average_gap_pct = sum(gap_samples) / len(gap_samples) if gap_samples else 0.0
        return CompetitiveSnapshot(
            generated_at=_utc_now().isoformat(),
            total_offers=len(offers),
            threat_count=len(threats),
            opportunity_count=len(opportunities),
            threats=sorted(threats, key=lambda item: item["gap_pct"], reverse=True),
            opportunities=sorted(opportunities, key=lambda item: item["gap_pct"], reverse=True),
            item_count=len(grouped),
            average_gap_pct=average_gap_pct,
        )

    def _scrape_via_cdp(
        self,
        keyword: str,
        max_items: int = 5,
    ) -> list[dict]:
        """Fallback scraper via CDP when direct API is blocked."""
        import json as _json
        import ssl as _ssl
        import time
        import urllib.parse as _parse

        import requests as _req
        import websocket as _ws

        ws = None
        try:
            resp = _req.get("http://127.0.0.1:9222/json/version", timeout=5)
            if resp.status_code != 200:
                return []

            resp2 = _req.put("http://127.0.0.1:9222/json/new", timeout=10)
            if resp2.status_code != 200:
                return []
            tab = resp2.json()
            ws_url = tab.get("webSocketDebuggerUrl", "")
            if not ws_url:
                return []

            ws = _ws.create_connection(
                ws_url, timeout=30,
                sslopt={"cert_reqs": _ssl.CERT_NONE} if ws_url.startswith("wss") else {},
            )
            ws.settimeout(10)

            _msg_id = 0
            def _cdp(method: str, params: dict | None = None) -> dict | None:
                nonlocal _msg_id
                _msg_id += 1
                ws.send(_json.dumps({"id": _msg_id, "method": method, "params": params or {}}))
                while True:
                    raw = ws.recv()
                    try:
                        data = _json.loads(raw)
                        if data.get("id") == _msg_id:
                            return data
                    except Exception:
                        continue

            _cdp("Page.enable")
            search_url = f"https://shopee.com.br/search?keyword={_parse.quote(keyword)}"
            _cdp("Page.navigate", {"url": search_url})
            time.sleep(5)
            ws.settimeout(0.3)
            while True:
                try: ws.recv()
                except: break
            ws.settimeout(10)

            # Navigate directly to API URL in browser
            api_url = f'https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword={_parse.quote(keyword)}&limit={max_items}&newest=0&order=desc&page_type=search&version=2'
            _cdp("Page.navigate", {"url": api_url})
            time.sleep(3)
            ws.settimeout(0.3)
            while True:
                try: ws.recv()
                except: break
            ws.settimeout(10)

            result = _cdp("Runtime.evaluate", {
                "expression": "document.body ? document.body.innerText : '{}'",
                "awaitPromise": False,
            })
            inner = result.get("result", {}).get("result", {})
            raw_val = inner.get("value", "{}")
            data = _json.loads(raw_val) if isinstance(raw_val, str) else raw_val
            if isinstance(data, dict) and data.get("error") == 90309999:
                return []
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            return []

        except Exception:
            return []
        finally:
            if ws:
                try: ws.close()
                except: pass

    def scrape_competitors(
        self,
        our_items: list[dict] | None = None,
        keywords: list[str] | None = None,
        max_per_item: int = 5,
    ) -> int:
        """
        Scrape competitor prices from Shopee search API (fallback: ML).

        Shopee public search API and Mercado Livre API are often
        blocked by anti-bot protection. When blocked, returns 0 gracefully.
        """
        import urllib.parse as _parse

        import requests as _req

        from shopee_agent.logger import warning as _warn

        if our_items is None:
            try:
                from shopee_agent.client import ShopeeClient
                from shopee_agent.config import load_config
                cfg = load_config()
                client = ShopeeClient(cfg)
                token = cfg.default_access_token
                shop = cfg.default_shop_id
                if token and shop:
                    resp = client.get_item_list(access_token=token, shop_id=shop, offset=0, page_size=100)
                    if resp and hasattr(resp, "data"):
                        raw = resp.data if isinstance(resp.data, dict) else {}
                        our_items = raw.get("item", []) or raw.get("item_list", [])
            except Exception:
                pass
        if not our_items:
            return 0

        total = 0
        for item in our_items[:20]:
            if not isinstance(item, dict):
                continue
            item_name = str(item.get("item_name", item.get("name", "")))
            item_id = str(item.get("item_id", item.get("id", "")))
            our_price_raw = item.get("price", item.get("price_info", 0))
            try:
                our_price = float(our_price_raw) / 100000 if isinstance(our_price_raw, int) and our_price_raw > 1000 else float(our_price_raw)
            except Exception:
                our_price = 0.0
            if not item_name:
                continue
            kw_list = keywords or [item_name[:60]]
            for kw in kw_list:
                try:
                    url = f"https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword={_parse.quote(kw)}&limit={max_per_item}&newest=0&order=desc&page_type=search&version=2"
                    r = _req.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://shopee.com.br/"})
                    if r.status_code == 200:
                        data = r.json()
                        items = data.get("items", [])
                        if items:
                            for entry in items:
                                shopee_item = entry.get("item_basic", entry)
                                comp_name = str(shopee_item.get("shop_location", "unknown"))[:30]
                                comp_item_id = str(shopee_item.get("itemid", ""))
                                comp_item_name = str(shopee_item.get("name", ""))[:80]
                                comp_price = float(shopee_item.get("price", 0)) / 100000
                                if comp_price <= 0 or comp_item_id == item_id:
                                    continue
                                self.record_offer(
                                    competitor_name=comp_name,
                                    item_id=comp_item_id,
                                    item_name=comp_item_name or kw[:60],
                                    competitor_price=comp_price,
                                    our_price=our_price if our_price > 0 else None,
                                    source="shopee_search",
                                )
                                total += 1
                            break
                    else:
                        _warn(f"Shopee search blocked for '{kw[:30]}'")
                except Exception:
                    continue
                break
        if total == 0:
            _warn("All search sources blocked. Competitive data unavailable.")
        return total
