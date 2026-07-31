"""Scraper for ALL content at seller.shopee.com.br (blog, courses, webinars, collections).

Uses Playwright via _PWInterceptor to navigate and extract both API-delivered
and server-rendered content. Saves everything into a unified knowledge_base table.
"""
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.article_scraper import _get_db, _PWInterceptor

_DB_DIR = Path(__file__).parents[1] / "data"

BASE = "https://seller.shopee.com.br"


def init_content_db() -> None:
    """Create/update knowledge_base table for all content types."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_type TEXT NOT NULL,
            content_id TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT DEFAULT 'br',
            text TEXT,
            url TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            scraped_at TEXT NOT NULL,
            UNIQUE(content_type, content_id)
        );

        CREATE INDEX IF NOT EXISTS idx_kb_type ON knowledge_base(content_type);
        CREATE INDEX IF NOT EXISTS idx_kb_type_source ON knowledge_base(content_type, source);
    """)
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                title, text,
                content=knowledge_base,
                content_rowid='id'
            )
        """)
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def _save_kb(content_type: str, content_id: str, title: str,
             text: str, url: str = "", metadata: dict | None = None) -> None:
    conn = _get_db()
    now = datetime.now(UTC).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO knowledge_base
            (content_type, content_id, title, source, text, url, metadata, scraped_at)
        VALUES (?, ?, ?, 'br', ?, ?, ?, ?)
    """, (content_type, content_id, title, text, url,
          json.dumps(metadata or {}, ensure_ascii=False), now))
    rid = conn.execute(
        "SELECT id FROM knowledge_base WHERE content_type=? AND content_id=?",
        (content_type, content_id)
    ).fetchone()["id"]
    try:
        conn.execute(
            "INSERT OR REPLACE INTO knowledge_fts(rowid, title, text) VALUES (?, ?, ?)",
            (rid, title, text))
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def _exists(content_type: str, content_id: str) -> bool:
    conn = _get_db()
    row = conn.execute(
        "SELECT 1 FROM knowledge_base WHERE content_type=? AND content_id=?",
        (content_type, content_id)
    ).fetchone()
    conn.close()
    return row is not None


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _extract_text(p) -> str:
    """Extract main content text from the current page."""
    text = p.inner_text("body")
    # Split by common separators
    import re
    parts = re.split(r'\s*\||\n', text)
    # Filter out boilerplate
    boilerplate = [
        "centro de educa", "pagina inicial", "faça login", "cursos",
        "treinamentos", "artigos", "blog", "videos", "ok", "entrar",
        "ver tudo", "ver mais", "carregar mais",
    ]
    clean = []
    for part in parts:
        stripped = part.strip()
        if not stripped or len(stripped) < 5:
            continue
        lower = stripped.lower()
        if any(b in lower for b in boilerplate):
            continue
        clean.append(stripped)
    return " | ".join(clean)


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------

def scrape_blog(force: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"found": 0, "new": 0, "errors": 0, "ids": []}

    with _PWInterceptor(base_url=BASE, domain_key="br") as intc:
        p = intc._page
        p.goto(f"{BASE}/edu/blog", wait_until="networkidle", timeout=30000)
        p.wait_for_timeout(2000)

        # Collect blog IDs by clicking navigate on each card
        blog_ids: set[int] = set()
        cards = p.query_selector_all("div.blog-card")
        result["found"] = len(cards)
        print(f"  [blog] {len(cards)} cards found")

        for idx in range(len(cards)):
            current = p.query_selector_all("div.blog-card")
            if idx >= len(current):
                break
            try:
                initial = p.url
                current[idx].click()
                p.wait_for_timeout(1500)
                if p.url != initial:
                    m = re.search(r'/edu/blog/(\d+)', p.url)
                    if m:
                        blog_ids.add(int(m.group(1)))
                    p.go_back()
                    p.wait_for_timeout(1500)
            except Exception:
                pass

        result["ids"] = sorted(blog_ids)
        print(f"  [blog] collected IDs: {sorted(blog_ids)}")

        # Now scrape each blog detail
        for bid in sorted(blog_ids):
            sid = str(bid)
            if not force and _exists("blog", sid):
                continue
            try:
                p.goto(f"{BASE}/edu/blog/{bid}", wait_until="domcontentloaded", timeout=20000)
                p.wait_for_timeout(2000)
                title = p.title()
                title = re.sub(r'\s*\|?\s*(Centro de Educa.*|Shopee.*|do Vendedor.*)', '', title).strip()
                text = _extract_text(p)
                _save_kb("blog", sid, title, text, url=f"{BASE}/edu/blog/{bid}")
                result["new"] += 1
                print(f"  [blog] saved {bid}: {title[:50]}")
            except Exception as e:
                result["errors"] += 1
                print(f"  [blog] error {bid}: {e}")

    return result


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def scrape_courses(force: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"found": 0, "new": 0, "errors": 0}

    with _PWInterceptor(base_url=BASE, domain_key="br") as intc:
        p = intc._page
        p.goto(f"{BASE}/edu/courses", wait_until="networkidle", timeout=30000)
        p.wait_for_timeout(2000)

        # Find all course links
        course_links = []
        links = p.query_selector_all("a[href*='/edu/courseDetail/']")
        for a in links:
            href = p.evaluate("el => el.getAttribute('href') || ''", a)
            if href:
                full = href if href.startswith("http") else f"{BASE}{href}"
                course_links.append(full)

        # Deduplicate
        course_links = list(dict.fromkeys(course_links))
        result["found"] = len(course_links)
        print(f"  [courses] {len(course_links)} courses found")

        for url in course_links:
            cid = url.split("/courseDetail/")[-1].split("/")[0].split("?")[0]
            if not force and _exists("course", cid):
                continue
            try:
                p.goto(url, wait_until="domcontentloaded", timeout=30000)
                p.wait_for_timeout(3000)
                title = p.title()
                import re
                title = re.sub(r'\s*\|?\s*(Centro de Educa.*|Shopee.*|do Vendedor.*)', '', title).strip()
                text = _extract_text(p)
                _save_kb("course", cid, title, text, url=url)
                result["new"] += 1
                print(f"  [course] saved {cid}: {title[:50]}")
            except Exception as e:
                result["errors"] += 1
                print(f"  [course] error {cid}: {e}")

    return result


# ---------------------------------------------------------------------------
# Webinars
# ---------------------------------------------------------------------------

def scrape_webinars(force: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"found": 0, "new": 0, "errors": 0}

    with _PWInterceptor(base_url=BASE, domain_key="br") as intc:
        p = intc._page
        p.goto(f"{BASE}/edu/webinars", wait_until="networkidle", timeout=30000)
        p.wait_for_timeout(2000)

        # Extract all webinar card-like content
        text = _extract_text(p)
        title = p.title().replace(" | Centro de Educa", "").strip()

        # Save the full page as a single webinar entry
        if force or not _exists("webinar", "page"):
            _save_kb("webinar", "page", title, text, url=f"{BASE}/edu/webinars")
            result["new"] = 1
        result["found"] = 1

        # Also try to extract individual webinar cards
        cards = p.query_selector_all("div[class*=card], div[class*=webinar], div[class*=training]")
        result["found"] = max(len(cards), 1)

    return result


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

def scrape_collections(force: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"found": 0, "new": 0, "errors": 0}
    collections = [
        ("started", "Basico - Comece por aqui"),
        ("leveling", "Intermediario"),
        ("scaling", "Avancado"),
    ]

    with _PWInterceptor(base_url=BASE, domain_key="br") as intc:
        p = intc._page
        for key, name in collections:
            if not force and _exists("collection", key):
                result["found"] += 1
                continue
            try:
                p.goto(f"{BASE}/edu/collections/{key}", wait_until="networkidle", timeout=30000)
                p.wait_for_timeout(2000)
                text = _extract_text(p)
                _save_kb("collection", key, name, text, url=f"{BASE}/edu/collections/{key}")
                result["new"] += 1
                result["found"] += 1
                print(f"  [collection] saved {key}: {name}")
            except Exception as e:
                result["errors"] += 1
                print(f"  [collection] error {key}: {e}")

    return result


# ---------------------------------------------------------------------------
# Unified scraper
# ---------------------------------------------------------------------------

def scrape_all_content(force: bool = False) -> dict[str, Any]:
    init_content_db()
    combined: dict[str, Any] = {
        "blog": {"found": 0, "new": 0, "errors": 0},
        "courses": {"found": 0, "new": 0, "errors": 0},
        "webinars": {"found": 0, "new": 0, "errors": 0},
        "collections": {"found": 0, "new": 0, "errors": 0},
        "total_found": 0, "total_new": 0, "total_errors": 0,
    }

    print("[site_scraper] Blog...")
    try:
        combined["blog"] = scrape_blog(force=force)
    except Exception as e:
        print(f"  Blog error: {e}")
        combined["blog"]["errors"] += 1

    print("[site_scraper] Courses...")
    try:
        combined["courses"] = scrape_courses(force=force)
    except Exception as e:
        print(f"  Courses error: {e}")
        combined["courses"]["errors"] += 1

    print("[site_scraper] Webinars...")
    try:
        combined["webinars"] = scrape_webinars(force=force)
    except Exception as e:
        print(f"  Webinars error: {e}")
        combined["webinars"]["errors"] += 1

    print("[site_scraper] Collections...")
    try:
        combined["collections"] = scrape_collections(force=force)
    except Exception as e:
        print(f"  Collections error: {e}")
        combined["collections"]["errors"] += 1

    for k in ["blog", "courses", "webinars", "collections"]:
        combined["total_found"] += combined[k].get("found", 0)
        combined["total_new"] += combined[k].get("new", 0)
        combined["total_errors"] += combined[k].get("errors", 0)

    return combined


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def search_knowledge(query: str, limit: int = 10) -> list[dict]:
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, content_type, content_id, title, source, "
            "substr(text, 1, 200) AS snippet "
            "FROM knowledge_fts f JOIN knowledge_base k ON f.rowid = k.id "
            "WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT id, content_type, content_id, title, source, "
            "substr(text, 1, 200) AS snippet "
            "FROM knowledge_base WHERE title LIKE ? OR text LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_by_type(content_type: str, limit: int = 20) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, content_type, content_id, title, source, url, "
        "substr(text, 1, 300) AS snippet, scraped_at "
        "FROM knowledge_base WHERE content_type=? ORDER BY id DESC LIMIT ?",
        (content_type, limit)).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def count_by_type() -> dict[str, int]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT content_type, COUNT(*) AS cnt FROM knowledge_base GROUP BY content_type").fetchall()
    counts = {r["content_type"]: r["cnt"] for r in rows}
    conn.close()
    return counts
