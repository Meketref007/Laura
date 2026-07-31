"""
Módulo de raspagem de produtos da loja Shopee.

Extrai TODOS os produtos via API, incluindo:
- Nome, descrição, SKU, preço, estoque
- Atributos (características)
- Logística (frete, dimensões, peso)
- Imagens, categorias, status

Nota: A plataforma Brazil (openplatform.shopee.com.br) não possui o endpoint
get_item_detail. Usamos get_item_base_info com item_id_list no lugar.

Armazena em SQLite com FTS5 para busca textual.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .auth import sign_request
from .client import ShopeeClient

_DB_DIR = Path(__file__).parents[1] / "data"
_DB_PATH = _DB_DIR / "shopee_products.db"

# Brazil API usa item_id_list ao invés de item_id
_BRAZIL_USE_ITEM_ID_LIST = True


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            item_id INTEGER PRIMARY KEY,
            item_name TEXT NOT NULL DEFAULT '',
            item_sku TEXT DEFAULT '',
            description TEXT DEFAULT '',
            current_price REAL DEFAULT 0,
            original_price REAL DEFAULT 0,
            stock INTEGER DEFAULT 0,
            reserved_stock INTEGER DEFAULT 0,
            category_id INTEGER DEFAULT 0,
            category_name TEXT DEFAULT '',
            weight REAL DEFAULT 0,
            dimension_json TEXT DEFAULT '{}',
            image_ids TEXT DEFAULT '',
            image_urls TEXT DEFAULT '',
            status TEXT DEFAULT 'NORMAL',
            has_variation INTEGER DEFAULT 0,
            sold INTEGER DEFAULT 0,
            historical_sold INTEGER DEFAULT 0,
            variation_json TEXT DEFAULT '[]',
            attribute_json TEXT DEFAULT '[]',
            logistic_json TEXT DEFAULT '[]',
            brand TEXT DEFAULT '',
            condition TEXT DEFAULT '',
            item_rating_json TEXT DEFAULT '{}',
            create_time INTEGER DEFAULT 0,
            update_time INTEGER DEFAULT 0,
            scraped_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);

        CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
            item_name, description, item_sku, brand,
            content=products,
            content_rowid='item_id'
        );
    """)
    conn.commit()
    conn.close()


def _product_exists(item_id: int) -> bool:
    conn = _get_db()
    row = conn.execute("SELECT 1 FROM products WHERE item_id=?", (item_id,)).fetchone()
    conn.close()
    return row is not None


def _save_product(data: dict) -> None:
    now = datetime.now(UTC).isoformat()
    conn = _get_db()

    dimension = data.get("dimension") or {}
    image_obj = data.get("image") or {}
    image_ids = ",".join(image_obj.get("image_id_list", [])) if isinstance(image_obj, dict) else ""
    image_urls = ",".join(image_obj.get("image_url_list", [])) if isinstance(image_obj, dict) else ""

    # Price: price_info is a list with {currency, current_price, original_price}
    price_info = data.get("price_info") or []
    current_price = 0.0
    original_price = 0.0
    if isinstance(price_info, list) and price_info:
        pi = price_info[0]
        current_price = float(pi.get("current_price", pi.get("price", 0)) or 0)
        original_price = float(pi.get("original_price", 0) or 0)

    # Stock: stock_info_v2.summary_info or seller_stock
    stock_info = data.get("stock_info_v2", {})
    summary = stock_info.get("summary_info", {}) if isinstance(stock_info, dict) else {}
    stock = int(summary.get("total_available_stock", summary.get("total_stock", 0)) or 0)
    reserved = int(summary.get("total_reserved_stock", 0) or 0)
    # Fallback: seller_stock array
    if not stock:
        seller_stock = stock_info.get("seller_stock", []) if isinstance(stock_info, dict) else []
        if isinstance(seller_stock, list):
            for ss in seller_stock:
                stock += int(ss.get("stock", 0) or 0)

    attribute_list = data.get("attribute_list") or []
    logistic_info = data.get("logistic_info") or []
    brand = data.get("brand") or ""
    if isinstance(brand, dict):
        brand = brand.get("original_brand_name", brand.get("name", ""))
    brand = str(brand)
    condition = str(data.get("condition") or "")
    item_status = data.get("item_status", data.get("status", "NORMAL"))
    has_model = data.get("has_model", data.get("has_variation", 0))

    # Sold info from external data (get_item_extra_info)
    sold = int(data.get("sold", 0) or 0)
    historical_sold = int(data.get("historical_sold", 0) or 0)

    conn.execute("""
        INSERT OR REPLACE INTO products
            (item_id, item_name, item_sku, description,
             current_price, original_price, stock, reserved_stock,
             category_id, category_name, weight, dimension_json,
             image_ids, image_urls, status, has_variation,
             sold, historical_sold,
             variation_json, attribute_json, logistic_json,
             brand, condition, item_rating_json,
             create_time, update_time, scraped_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("item_id") or data.get("id"),
        data.get("item_name") or data.get("name") or data.get("title") or "",
        data.get("item_sku") or data.get("sku") or "",
        data.get("description") or "",
        current_price,
        original_price,
        stock,
        reserved,
        int(data.get("category_id") or 0),
        data.get("category_name", ""),
        float(data.get("weight") or 0),
        json.dumps(dimension, ensure_ascii=False),
        image_ids,
        image_urls,
        item_status,
        1 if has_model else 0,
        sold,
        historical_sold,
        json.dumps(data.get("variation_list", data.get("model_list", data.get("variations", []))), ensure_ascii=False),
        json.dumps(attribute_list, ensure_ascii=False),
        json.dumps(logistic_info, ensure_ascii=False),
        brand,
        condition,
        json.dumps(data.get("item_rating", {}), ensure_ascii=False),
        int(data.get("create_time") or 0),
        int(data.get("update_time") or 0),
        now,
    ))
    # Sync FTS
    conn.execute(
        "INSERT INTO products_fts(rowid, item_name, description, item_sku, brand) VALUES (?,?,?,?,?)",
        (
            data.get("item_id") or data.get("id"),
            data.get("item_name") or data.get("name") or "",
            data.get("description") or "",
            data.get("item_sku") or "",
            brand,
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Raw API helper for Brazil-specific endpoints
# ---------------------------------------------------------------------------

def _raw_get(
    client: ShopeeClient,
    path: str,
    query_params: dict[str, Any],
    *,
    access_token: str,
    shop_id: int,
) -> dict[str, Any]:
    """Make a raw GET request to the Shopee API, handling signing."""
    import requests as _requests
    cfg = client.config
    base = str(cfg.base_url).rstrip("/")
    partner_id = cfg.partner_id
    partner_key = cfg.partner_key
    ts = int(time.time())

    params: dict[str, Any] = {
        "partner_id": partner_id,
        "timestamp": ts,
        "access_token": access_token,
        "shop_id": shop_id,
    }
    params.update(query_params)
    params["sign"] = sign_request(
        partner_id=partner_id,
        partner_key=partner_key,
        path=path,
        timestamp=ts,
        access_token=access_token,
        shop_id=shop_id,
    )

    r = _requests.get(f"{base}{path}", params=params, timeout=30)
    if r.status_code == 200:
        body = r.json()
        if isinstance(body, dict) and not body.get("error"):
            return body.get("response", body)
    return {}


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_all_products(
    client: ShopeeClient,
    access_token: str,
    shop_id: int,
    *,
    force: bool = False,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Scrape ALL products from the store with full detail.

    Args:
        client: Authenticated ShopeeClient instance.
        access_token: Shopee access token.
        shop_id: Shop ID.
        force: If False, skip products already in DB.
        max_items: Max items to scrape (None = all).

    Returns:
        dict with counts.
    """
    init_db()
    result: dict[str, Any] = {
        "total_found": 0,
        "total_new": 0,
        "errors": 0,
    }

    offset = 0
    page_size = 100
    seen_ids: set[int] = set()

    def _fetch_detail(item_id: int) -> dict:
        """Fetch product detail using get_item_base_info (Brazil API)."""
        resp_data = _raw_get(
            client,
            "/api/v2/product/get_item_base_info",
            {"item_id_list": str(item_id)},
            access_token=access_token,
            shop_id=shop_id,
        )
        item_list = resp_data.get("item_list", []) if isinstance(resp_data, dict) else []
        if item_list and isinstance(item_list, list):
            return item_list[0]
        return {}

    while True:
        resp = client.get_item_list(
            access_token=access_token,
            shop_id=shop_id,
            offset=offset,
            page_size=page_size,
            item_status="NORMAL",
        )

        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", [])
        if not isinstance(items, list) or not items:
            break

        for item in items:
            item_id = item.get("item_id")
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            result["total_found"] += 1

            if not force and _product_exists(item_id):
                continue

            try:
                detail = _fetch_detail(item_id)
                if detail:
                    _save_product(detail)
                    result["total_new"] += 1
                else:
                    result["errors"] += 1
            except Exception:
                result["errors"] += 1

            if max_items and result["total_new"] >= max_items:
                break

        has_next = body.get("has_next_page", False)
        if not has_next:
            break
        offset = len(seen_ids)

        if max_items and result["total_new"] >= max_items:
            break

    # Also scrape UNLISTED items
    try:
        resp = client.get_item_list(
            access_token=access_token,
            shop_id=shop_id,
            offset=0,
            page_size=page_size,
            item_status="UNLISTED",
        )
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", [])
        for item in items if isinstance(items, list) else []:
            item_id = item.get("item_id")
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            result["total_found"] += 1
            if force or not _product_exists(item_id):
                try:
                    detail = _fetch_detail(item_id)
                    if detail:
                        _save_product(detail)
                        result["total_new"] += 1
                except Exception:
                    result["errors"] += 1
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def search_products(query: str, limit: int = 10, offset: int = 0) -> list[dict]:
    """Full-text search on products with pagination."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT p.item_id, p.item_name, p.item_sku, p.current_price, p.stock, "
            "p.status, p.category_name, p.sold, p.historical_sold, "
            "snippet(products_fts, 1, '<b>', '</b>', '...', 32) AS snippet "
            "FROM products_fts f JOIN products p ON f.rowid = p.item_id "
            "WHERE products_fts MATCH ? "
            "ORDER BY rank "
            "LIMIT ? OFFSET ?",
            (query, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT item_id, item_name, item_sku, current_price, stock, status, "
            "category_name, sold, historical_sold, "
            "substr(description, 1, 200) AS snippet "
            "FROM products "
            "WHERE item_name LIKE ? OR description LIKE ? OR item_sku LIKE ? "
            "LIMIT ? OFFSET ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_product(item_id: int) -> dict | None:
    """Get product by ID with all details."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM products WHERE item_id=?", (item_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        for field in ("variation_json", "attribute_json", "logistic_json", "dimension_json", "item_rating_json"):
            try:
                d[field] = json.loads(d.get(field) or "{}")
            except Exception:
                d[field] = {} if field.endswith("_json") else []
        return d
    return None


def get_products_by_category(category_name: str, limit: int = 20, offset: int = 0) -> list[dict]:
    """Get products by category name."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT item_id, item_name, item_sku, current_price, stock, status, category_name "
        "FROM products WHERE category_name LIKE ? ORDER BY item_name LIMIT ? OFFSET ?",
        (f"%{category_name}%", limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_categories() -> list[dict]:
    """Get distinct categories with product count."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT category_id, category_name, COUNT(*) AS product_count "
        "FROM products WHERE category_id > 0 "
        "GROUP BY category_id ORDER BY category_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_low_stock_products(threshold: int = 5) -> list[dict]:
    """Get products with stock below threshold."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT item_id, item_name, item_sku, current_price, stock, category_name "
        "FROM products WHERE stock > 0 AND stock < ? ORDER BY stock LIMIT 50",
        (threshold,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_product_count() -> int:
    """Total number of products in DB."""
    conn = _get_db()
    row = conn.execute("SELECT COUNT(*) AS cnt FROM products").fetchone()
    conn.close()
    return row["cnt"] if row else 0
