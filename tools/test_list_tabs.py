"""List all tabs and find product detail pages."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
for i, t in enumerate(tabs):
    url = t.get("url", "")[:100]
    title = (t.get("title", "") or "")[:60]
    tab_id = t.get("id", "")[:20]
    print(f"[{i}] {tab_id} | {title} | {url}")
