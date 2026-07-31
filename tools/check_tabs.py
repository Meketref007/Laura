"""Check existing CDP tabs."""
import requests as req, json, sys
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
found = False
for t in tabs:
    url = t.get("url", "")
    if "seller" in url.lower():
        print(f"Tab: {t.get('id','')[:30]} | URL: {url[:100]}")
        found = True
if not found:
    print("Nenhuma aba do Seller Center encontrada")
    print(f"Total abas: {len(tabs)}")
    for t in tabs[:3]:
        print(f"  {t.get('id','')[:20]} | {t.get('url','')[:80]}")
