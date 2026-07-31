"""Scraper de busca da Shopee - coleta precos de concorrentes por palavra-chave."""
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import requests

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
SEARCH_CACHE = REPORTS_DIR / "search_cache.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Shopee domains by region
SHOPEE_DOMAINS = {
    "br": "shopee.com.br",
    "id": "shopee.co.id",
    "sg": "shopee.sg",
    "my": "shopee.com.my",
    "th": "shopee.co.th",
    "ph": "shopee.ph",
    "vn": "shopee.vn",
    "tw": "shopee.tw",
}


def _search_url(keyword: str, region: str = "br", page: int = 0) -> str:
    """Monta URL da API de busca da Shopee."""
    encoded = quote(keyword)
    return (
        f"https://{SHOPEE_DOMAINS.get(region, 'shopee.com.br')}"
        f"/api/v4/search/search_items"
        f"?by=relevance&keyword={encoded}"
        f"&limit=20&newest={page * 20}"
        f"&order=desc&page_type=search"
        f"&scenario=PAGE_GLOBAL_SEARCH&version=2"
    )


def _search_url_web(keyword: str, region: str = "br", page: int = 0) -> str:
    """URL da pagina web para fallback."""
    encoded = quote(keyword)
    return (
        f"https://{SHOPEE_DOMAINS.get(region, 'shopee.com.br')}"
        f"/search?keyword={encoded}&page={page}"
    )


def scrape_search(
    keyword: str,
    region: str = "br",
    max_pages: int = 3,
    max_results: int = 50,
    timeout: int = 15,
) -> list[dict]:
    """Busca produtos na Shopee por palavra-chave e retorna precos."""
    results = []
    seen_ids = set()

    for page in range(max_pages):
        if len(results) >= max_results:
            break

        url = _search_url(keyword, region, page)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": f"https://{SHOPEE_DOMAINS.get(region, 'shopee.com.br')}/",
            "x-requested-with": "XMLHttpRequest",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                break

            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item_wrapper in items:
                item = item_wrapper.get("item_basic", item_wrapper)
                item_id = item.get("itemid", item.get("item_id"))
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                price_min = item.get("price_min", 0) / 100000
                price_max = item.get("price_max", 0) / 100000
                price = item.get("price", 0) / 100000

                results.append({
                    "item_id": item_id,
                    "name": item.get("name", ""),
                    "image": item.get("image", ""),
                    "price": price or price_min,
                    "price_min": price_min,
                    "price_max": price_max,
                    "currency": "BRL",
                    "shop_id": item.get("shopid", item.get("shop_id")),
                    "shop_name": item.get("shop_name", item.get("shop_location", "")),
                    "location": item.get("shop_location", ""),
                    "historical_sold": item.get("historical_sold", 0),
                    "rating_star": item.get("item_rating", {}).get("rating_star", 0),
                    "cmt_count": item.get("cmt_count", 0),
                    "keyword": keyword,
                    "region": region,
                    "scraped_at": datetime.now(UTC).isoformat(),
                })

                if len(results) >= max_results:
                    break

            time.sleep(0.5)

        except requests.RequestException as e:
            print(f"[ShopeeSearch] Page {page} error: {e}")
            break

    return results


def get_competitor_prices(keyword: str, region: str = "br") -> list[float]:
    """Atalho: retorna so os precos dos concorrentes para um keyword."""
    results = scrape_search(keyword, region, max_pages=1, max_results=20)
    return [r["price"] for r in results if r["price"] > 0]


def update_competitor_cache(product_name: str, item_id: str) -> dict:
    """Atualiza o cache de precos de concorrentes para um produto."""
    results = scrape_search(product_name, max_pages=2, max_results=30)
    prices = [r["price"] for r in results if r["price"] > 0]

    cache = {}
    cache_path = REPORTS_DIR / "pricing_competitor_cache.json"
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    cache[str(item_id)] = prices
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "item_id": item_id,
        "product_name": product_name,
        "competitors_found": len(prices),
        "avg_price": round(sum(prices) / len(prices), 2) if prices else 0,
        "min_price": round(min(prices), 2) if prices else 0,
        "max_price": round(max(prices), 2) if prices else 0,
    }


def batch_update(all_products: list[dict]) -> list[dict]:
    """Atualiza cache para todos os produtos da loja."""
    results = []
    for p in all_products:
        name = p.get("item_name", p.get("name", ""))
        iid = str(p.get("item_id", ""))
        if name and iid:
            r = update_competitor_cache(name, iid)
            results.append(r)
            time.sleep(1)
    return results


# ── Tracked competitors persistence ──────────────────────────────────────────

_TRACKED_FILE = REPORTS_DIR / "tracked_competitors.json"


def _load_tracked() -> list[dict]:
    try:
        if _TRACKED_FILE.exists():
            return json.loads(_TRACKED_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_tracked(data: list[dict]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _TRACKED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def track_competitor(item_id: str, name: str = "", price: float = 0.0) -> dict:
    tracked = _load_tracked()
    existing = [t for t in tracked if t.get("item_id") == item_id]
    if existing:
        existing[0]["last_seen"] = datetime.now(UTC).isoformat()
        if name:
            existing[0]["name"] = name
        if price:
            existing[0]["price"] = price
    else:
        tracked.append({
            "item_id": item_id,
            "name": name or item_id,
            "price": price,
            "tracked_at": datetime.now(UTC).isoformat(),
            "last_seen": datetime.now(UTC).isoformat(),
        })
    _save_tracked(tracked)
    return {"tracked": item_id, "total_tracked": len(tracked)}


def list_tracked() -> list[dict]:
    return _load_tracked()


def compare_product(my_item_id: str, competitor_item_id: str) -> dict:
    """Compare your product with a competitor product by item_id."""
    try:
        my_results = scrape_search(my_item_id, max_pages=1, max_results=5)
        comp_results = scrape_search(competitor_item_id, max_pages=1, max_results=5)
        my_product = next((r for r in my_results if str(r.get("item_id")) == my_item_id), None)
        comp_product = next((r for r in comp_results if str(r.get("item_id")) == competitor_item_id), None)
        return {
            "my_product": my_product,
            "competitor": comp_product,
            "price_diff": (my_product.get("price", 0) - comp_product.get("price", 0)) if my_product and comp_product else None,
            "rating_diff": (my_product.get("rating_star", 0) - comp_product.get("rating_star", 0)) if my_product and comp_product else None,
            "sold_diff": (my_product.get("historical_sold", 0) - comp_product.get("historical_sold", 0)) if my_product and comp_product else None,
        }
    except Exception as exc:
        return {"error": str(exc)}


def generate_competitive_report() -> dict:
    tracked = _load_tracked()
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_tracked": len(tracked),
        "competitors": [],
        "summary": {},
    }
    prices = []
    ratings = []
    for t in tracked:
        results = scrape_search(t.get("name", ""), max_pages=1, max_results=10)
        prices.extend(r["price"] for r in results if r.get("price", 0) > 0)
        ratings.extend(r["rating_star"] for r in results if r.get("rating_star", 0) > 0)
        report["competitors"].append({
            "item_id": t["item_id"],
            "name": t.get("name", ""),
            "competitors_found": len(results),
            "avg_price": round(sum(r["price"] for r in results if r.get("price")) / max(len([x for x in results if x.get("price")]), 1), 2),
            "scraped_at": datetime.now(UTC).isoformat(),
        })
    report["summary"] = {
        "avg_price": round(sum(prices) / len(prices), 2) if prices else 0,
        "min_price": round(min(prices), 2) if prices else 0,
        "max_price": round(max(prices), 2) if prices else 0,
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
        "total_competitors_found": sum(c["competitors_found"] for c in report["competitors"]),
    }
    return report


def build_parser(subparsers) -> None:
    comp_parser = subparsers.add_parser("competitors", help="Monitor and analyze competitor products")
    comp_sub = comp_parser.add_subparsers(dest="competitors_action", required=True)

    search_parser = comp_sub.add_parser("search", help="Search competitors by keyword")
    search_parser.add_argument("keyword", help="Search keyword")

    track_parser = comp_sub.add_parser("track", help="Start tracking a competitor product")
    track_parser.add_argument("item_id", help="Competitor item ID")
    track_parser.add_argument("--name", default="", help="Product name")
    track_parser.add_argument("--price", type=float, default=0.0, help="Current price")

    comp_sub.add_parser("list", help="List tracked competitors")

    compare_parser = comp_sub.add_parser("compare", help="Compare your product with a competitor")
    compare_parser.add_argument("item_id", help="Your product item ID")
    compare_parser.add_argument("--competitor-id", default="", help="Competitor item ID (optional, compares with first tracked if omitted)")

    comp_sub.add_parser("report", help="Generate competitive analysis report")
