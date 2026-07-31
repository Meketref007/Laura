"""
Módulo de raspagem e consulta de artigos do Shopee Seller Education Hub.

APIs descobertas:
  GET /help/api/v3/cat/list/              -> hierarchy + meta de categorias
  GET /help/api/v3/article/top/            -> 9 artigos em destaque
  GET /help/api/v3/article/list/?l1_cat_id=X&page_index=0&page_size=15  -> artigos por categoria
  GET /help/api/v3/article/detail/?article_id=X  -> conteudo completo do artigo
  GET /help/api/v3/article/related_list/?article_id=X  -> artigos relacionados
  GET /help/api/v3/collection/list/        -> colecoes (basico, intermediario, avancado)
"""
from __future__ import annotations

import json
import sqlite3
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_DB_DIR = Path(__file__).parents[1] / "data"
_DB_PATH = _DB_DIR / "shopee_articles.db"
_API_BASE = "https://seller.br.shopee.cn"
_API_PREFIX = "/help/api/v3"

# Domínios disponíveis para scraping de artigos
AVAILABLE_DOMAINS = {
    "cn": {
        "base_url": "https://seller.br.shopee.cn",
        "name": "Shopee BR (China-hosted)",
    },
    "br": {
        "base_url": "https://seller.shopee.com.br",
        "name": "Shopee BR (Brasil)",
    },
}

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
        CREATE TABLE IF NOT EXISTS categories (
            cat_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS articles (
            article_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT,
            cat_id INTEGER,
            cat_title TEXT,
            url_title TEXT DEFAULT '',
            article_type INTEGER DEFAULT 0,
            article_class INTEGER DEFAULT 0,
            meta_title TEXT DEFAULT '',
            meta_desc TEXT DEFAULT '',
            catalogue TEXT DEFAULT '[]',
            res_list TEXT DEFAULT '[]',
            disable_seo INTEGER DEFAULT 0,
            access_control INTEGER DEFAULT 0,
            generic_tags TEXT DEFAULT '[]',
            feedback TEXT DEFAULT '{}',
            rtime INTEGER DEFAULT 0,
            source TEXT DEFAULT 'cn',
            scraped_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_articles_cat_id ON articles(cat_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            title, content, meta_title, meta_desc,
            content=articles,
            content_rowid='article_id'
        );
    """)
    # Migration: add rtime if not present
    try:
        conn.execute("ALTER TABLE articles ADD COLUMN rtime INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    # Migration: add source after rtime (before index creation)
    try:
        conn.execute("ALTER TABLE articles ADD COLUMN source TEXT DEFAULT 'cn'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    # Create index on source (must come after column exists)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source)")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def _article_exists(article_id: int) -> bool:
    conn = _get_db()
    row = conn.execute("SELECT 1 FROM articles WHERE article_id=?", (article_id,)).fetchone()
    conn.close()
    return row is not None

def _normalize_json_field(value: Any) -> str:
    """Normalize a field that may be a JSON string, URL-encoded string, list, or dict."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        # Try URL-decoding first (catalogue comes URL-encoded)
        decoded = urllib.parse.unquote(value)
        if decoded != value:
            try:
                parsed = json.loads(decoded)
                return json.dumps(parsed, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
        # If it's already valid JSON, return as-is
        try:
            json.loads(value)
            return value
        except (json.JSONDecodeError, TypeError):
            pass
        # Otherwise, wrap in quotes
        return json.dumps(value, ensure_ascii=False)
    return "[]"


def _save_article(data: dict, source: str = "cn") -> None:
    now = datetime.now(UTC).isoformat()
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO articles
            (article_id, title, content, cat_id, cat_title, url_title,
             article_type, article_class, meta_title, meta_desc,
             catalogue, res_list, disable_seo, access_control,
             generic_tags, feedback, rtime, source, scraped_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("article_id"),
        data.get("title", ""),
        data.get("content", ""),
        data.get("cat_id"),
        data.get("cat_title", ""),
        data.get("url_title", ""),
        data.get("article_type", 0),
        data.get("article_class", 0),
        data.get("meta_title", ""),
        data.get("meta_desc", ""),
        _normalize_json_field(data.get("catalogue", [])),
        _normalize_json_field(data.get("res_list", [])),
        data.get("disable_seo", 0),
        data.get("access_control", 0),
        _normalize_json_field(data.get("generic_tags", [])),
        _normalize_json_field(data.get("feedback", {})),
        data.get("rtime", 0),
        source,
        now,
    ))
    # Sync FTS
    conn.execute("INSERT INTO articles_fts(rowid, title, content, meta_title, meta_desc) VALUES (?,?,?,?,?)", (
        data.get("article_id"),
        data.get("title", ""),
        data.get("content", ""),
        data.get("meta_title", ""),
        data.get("meta_desc", ""),
    ))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Playwright-based interceptor (uses page's own API calls)
# ---------------------------------------------------------------------------

class _PWInterceptor:
    """Maintains a headless Playwright browser that intercepts the page's own API calls.
    
    The page's React SPA handles authentication internally. We just navigate
    and intercept the responses.
    """

    def __init__(self, base_url: str = _API_BASE, domain_key: str = "cn") -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._last_responses: dict[str, dict] = {}
        self._base_url = base_url.rstrip("/")
        self._domain_key = domain_key
        self._spc_cache_path = _DB_DIR / f"spc_cds_cache_{domain_key}.txt"
        self._spc_cds: str = self._load_cached_spc_cds()

    def _load_cached_spc_cds(self) -> str:
        try:
            if self._spc_cache_path.exists():
                return self._spc_cache_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return ""

    def __enter__(self) -> _PWInterceptor:
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright()
        playwright = self._playwright.__enter__()
        self._browser = playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="pt-BR",
        )
        self._page = self._context.new_page()

        # Intercept all API responses for /help/api/v3
        self._page.on("response", self._on_response)
        return self

    def __exit__(self, *args) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.__exit__(*args)

    def _on_response(self, response) -> None:
        url = response.url
        if "/help/api/v3" not in url:
            return
        # Extract SPC_CDS from URL if not yet known
        if not self._spc_cds:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            if "SPC_CDS" in qs:
                self._spc_cds = qs["SPC_CDS"][0]
                try:
                    self._spc_cache_path.parent.mkdir(parents=True, exist_ok=True)
                    self._spc_cache_path.write_text(self._spc_cds, encoding="utf-8")
                except Exception:
                    pass
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p]
        # /help/api/v3/cat/list/ -> parts[-2:] = ['cat', 'list']
        key = "/".join(parts[-2:]) if len(parts) >= 2 else ""
        try:
            body = response.json()
        except Exception:
            return
        if isinstance(body, dict) and body.get("code") == 0:
            self._last_responses[key] = body

    def api_json(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """Make an API call from within the browser page context using fetch().
        
        Automatically includes authentication cookies, SPC_CDS query param,
        shopee-language header, and Referer header.
        The base URL is always /help/api/v3{path}.
        
        Args:
            path: API path like "/article/list/"
            params: Query parameters
        """
        qs_params = dict(params or {})
        if self._spc_cds:
            qs_params.setdefault("SPC_CDS", self._spc_cds)
            qs_params.setdefault("SPC_CDS_VER", "2")
        qs = urllib.parse.urlencode(qs_params)
        url = f"/help/api/v3{path}"
        if qs:
            url += f"?{qs}"
        result: dict | None = self._page.evaluate(f"""
            () => fetch('{url}', {{
                headers: {{
                    'accept': 'application/json, text/plain, */*',
                    'shopee-language': 'default',
                    'referer': 'https://seller.br.shopee.cn/edu/article'
                }}
            }})
                .then(r => r.json())
                .catch(e => ({{"error": e.message}}))
        """)
        if result is None:
            return {"error": "fetch returned None"}
        return result

    def navigate_category(self, sub_cat_id: int) -> list[dict]:
        """Navigate to a category page and intercept the article/list API response.
        
        Returns list of articles for that subcategory.
        """
        self._page.goto(f"{self._base_url}/edu/category?sub_cat_id={sub_cat_id}",
                       wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(3000)
        list_body = self._last_responses.get("article/list")
        if list_body and list_body.get("code") == 0:
            articles = list_body.get("data", {}).get("article_list", [])
            for art in articles:
                art["cat_id"] = sub_cat_id
            return articles
        return []

    def navigate_article_detail(self, article_id: int) -> dict | None:
        """Navigate to an article page and intercept the article/detail response."""
        try:
            self._page.goto(f"{self._base_url}/edu/article/{article_id}",
                           wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(3000)
        except Exception:
            # Timeout is OK if we got the data
            pass
        detail_body = self._last_responses.get("article/detail")
        if detail_body and detail_body.get("code") == 0:
            return detail_body.get("data")
        # Fallback: try fetching via in-page fetch
        fetch_body = self.api_json("/article/detail/", {
            "lang": "default",
            "article_id": str(article_id),
        })
        if fetch_body.get("code") == 0:
            return fetch_body.get("data")
        return None

    def load_page(self) -> None:
        """Load the main article page and wait for initial data."""
        self._page.goto(f"{self._base_url}/edu/article", wait_until="networkidle", timeout=30000)
        self._page.wait_for_timeout(3000)

    def get_cached_response(self, key: str) -> dict | None:
        """Get the last successful API response for a given endpoint key."""
        return self._last_responses.get(key)

# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def get_categories(interceptor: _PWInterceptor) -> list[dict]:
    """Extract category data from intercepted response."""
    body = interceptor.get_cached_response("cat/list")
    if not body:
        raise RuntimeError("cat/list response not found. Call interceptor.load_page() first.")

    data = body.get("data", {})
    meta = data.get("meta", [])
    data.get("cat_hierarchy", {})

    cat_map: dict[int, dict] = {}
    for m in meta:
        cid = m.get("cat_id")
        if cid:
            cat_map[cid] = {
                "cat_id": cid,
                "name": m.get("name", ""),
                "parent_id": m.get("parent_id", 0),
                "level": 0,
            }

    def _compute_level(cid: int) -> int:
        level = 0
        visited = set()
        while cid in cat_map and cid not in visited:
            visited.add(cid)
            pid = cat_map[cid]["parent_id"]
            if pid and pid in cat_map:
                level += 1
                cid = pid
            else:
                break
        return level

    for cid in cat_map:
        cat_map[cid]["level"] = _compute_level(cid)

    conn = _get_db()
    conn.execute("DELETE FROM categories")
    for cat in cat_map.values():
        conn.execute(
            "INSERT OR REPLACE INTO categories (cat_id, name, parent_id, level) VALUES (?,?,?,?)",
            (cat["cat_id"], cat["name"], cat["parent_id"], cat["level"]),
        )
    conn.commit()
    conn.close()

    return list(cat_map.values())


def get_leaf_category_ids(interceptor: _PWInterceptor) -> list[int]:
    """Get all leaf category IDs from intercepted cat/list response."""
    body = interceptor.get_cached_response("cat/list")
    if not body:
        raise RuntimeError("cat/list response not found")
    data = body.get("data", {})
    meta = data.get("meta", [])
    hierarchy = data.get("cat_hierarchy", {})
    parent_ids = set(int(k) for k in hierarchy.keys())
    leaf_ids = set()
    for m in meta:
        cid = m.get("cat_id")
        if cid and cid not in parent_ids:
            leaf_ids.add(cid)
    if not leaf_ids:
        leaf_ids = parent_ids
    return sorted(leaf_ids)


def _get_cat_title(cat_id: int) -> str:
    """Look up category name from DB by cat_id."""
    conn = _get_db()
    row = conn.execute("SELECT name FROM categories WHERE cat_id=?", (cat_id,)).fetchone()
    conn.close()
    return row["name"] if row else ""


def scrape_domain(
    domain_key: str = "cn",
    force: bool = False,
) -> dict[str, Any]:
    """Full scraping of a single domain: navigate each category -> collect article list -> detail.
    
    Uses a single Playwright browser session. For each leaf category, navigates
    to /edu/category?sub_cat_id=X and intercepts the page's own API responses.
    Article details are fetched via in-page fetch() (faster).
    
    Args:
        domain_key: Key from AVAILABLE_DOMAINS dict ("cn" or "br").
        force: If False, skip articles already in DB.
    
    Returns:
        dict with counts of scraped items.
    """
    domain = AVAILABLE_DOMAINS.get(domain_key, list(AVAILABLE_DOMAINS.values())[0])
    base_url = domain["base_url"]

    result: dict[str, Any] = {"categories": 0, "articles_found": 0, "articles_new": 0, "errors": 0}

    with _PWInterceptor(base_url=base_url, domain_key=domain_key) as interceptor:
        # Step 1: Load main page and save categories
        interceptor.load_page()
        cat_body = interceptor.get_cached_response("cat/list")
        if not cat_body:
            raise RuntimeError(f"Failed to get categories from {domain_key} ({base_url})")

        cats = get_categories(interceptor)
        result["categories"] = len(cats)

        # Step 2: Get leaf categories
        leaf_ids = get_leaf_category_ids(interceptor)

        # Step 3: Navigate each category and collect articles
        for cid in leaf_ids:
            try:
                articles = interceptor.navigate_category(cid)
                if not articles:
                    result["errors"] += 1
                    continue
                result["articles_found"] += len(articles)
            except Exception:
                result["errors"] += 1
                continue

            for art in articles:
                aid = art.get("article_id")
                if not aid:
                    continue
                if not force and _article_exists(aid):
                    continue

                try:
                    detail_body = interceptor.api_json("/article/detail/", {
                        "lang": "default",
                        "article_id": str(aid),
                    })
                    if detail_body.get("code") == 0:
                        detail = detail_body.get("data", {})
                        detail["cat_title"] = _get_cat_title(detail.get("cat_id", art.get("cat_id", 0)))
                        _save_article(detail, source=domain_key)
                        result["articles_new"] += 1
                    else:
                        result["errors"] += 1
                except Exception:
                    result["errors"] += 1

    # Rebuild FTS for this domain's articles
    _rebuild_fts()
    return result


def _rebuild_fts() -> None:
    """Rebuild FTS index for all articles."""
    conn = _get_db()
    conn.execute("DELETE FROM articles_fts")
    rows = conn.execute("SELECT article_id, title, content, meta_title, meta_desc FROM articles").fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO articles_fts(rowid, title, content, meta_title, meta_desc) VALUES (?,?,?,?,?)",
            (row["article_id"], row["title"], row["content"], row["meta_title"], row["meta_desc"]),
        )
    conn.commit()
    conn.close()


def scrape_all(force: bool = False) -> dict[str, Any]:
    """Scrape ALL known domains (cn + br) and merge articles.
    
    Args:
        force: If False, skip articles already in DB.
    
    Returns:
        dict with aggregated results per domain.
    """
    init_db()
    combined: dict[str, Any] = {
        "domains_scraped": 0,
        "total_categories": 0,
        "total_articles_found": 0,
        "total_articles_new": 0,
        "total_errors": 0,
        "per_domain": {},
    }

    for domain_key in AVAILABLE_DOMAINS:
        try:
            dom_result = scrape_domain(domain_key=domain_key, force=force)
            combined["per_domain"][domain_key] = dom_result
            combined["domains_scraped"] += 1
            combined["total_categories"] += dom_result.get("categories", 0)
            combined["total_articles_found"] += dom_result.get("articles_found", 0)
            combined["total_articles_new"] += dom_result.get("articles_new", 0)
            combined["total_errors"] += dom_result.get("errors", 0)
            print(f"[article_scraper] Domain '{domain_key}': "
                  f"{dom_result['articles_found']} found, {dom_result['articles_new']} new")
        except Exception as e:
            print(f"[article_scraper] Domain '{domain_key}' error: {e}")
            combined["total_errors"] += 1

    return combined

# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def search_articles(query: str, limit: int = 10, offset: int = 0) -> list[dict]:
    """Full-text search on articles with pagination."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT a.article_id, a.title, a.cat_title, snippet(articles_fts, 1, '<b>', '</b>', '...', 32) AS snippet "
            "FROM articles_fts f JOIN articles a ON f.rowid = a.article_id "
            "WHERE articles_fts MATCH ? "
            "ORDER BY rank "
            "LIMIT ? OFFSET ?",
            (query, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT article_id, title, cat_title, substr(content, 1, 200) AS snippet "
            "FROM articles "
            "WHERE title LIKE ? OR content LIKE ? "
            "LIMIT ? OFFSET ?",
            (f"%{query}%", f"%{query}%", limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_article(article_id: int) -> dict | None:
    """Get article by ID."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM articles WHERE article_id=?", (article_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_articles_by_category(cat_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """Get articles by category ID."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT article_id, title, cat_title, rtime, substr(content, 1, 200) AS snippet "
        "FROM articles WHERE cat_id=? ORDER BY rtime DESC LIMIT ? OFFSET ?",
        (cat_id, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_articles_by_category(cat_id: int) -> int:
    """Count articles in a category."""
    conn = _get_db()
    row = conn.execute("SELECT COUNT(*) AS cnt FROM articles WHERE cat_id=?", (cat_id,)).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_random_article() -> dict | None:
    """Get a random article for daily tip."""
    conn = _get_db()
    row = conn.execute(
        "SELECT article_id, title, cat_title, substr(content, 1, 300) AS snippet "
        "FROM articles ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_articles_by_text(query: str, limit: int = 10) -> list[dict]:
    """Search articles using LIKE (simpler than FTS)."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT article_id, title, cat_title, substr(content, 1, 200) AS snippet "
        "FROM articles "
        "WHERE title LIKE ? OR content LIKE ? "
        "ORDER BY article_id DESC "
        "LIMIT ?",
        (f"%{query}%", f"%{query}%", limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
