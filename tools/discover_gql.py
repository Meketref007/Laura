"""Try to access Seller Center via GraphQL and probe for data."""
import json, sys
from pathlib import Path
import requests

SELLER = "https://seller.shopee.com.br"

cookies_file = Path("secrets/seller_center_cookies.json")
data = json.loads(cookies_file.read_text())

session = requests.Session()
for c in data.get("cookies", []):
    session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"), secure=c.get("secure", True))

csrf = None
for c in data.get("cookies", []):
    if c["name"] == "SPC_ST":
        csrf = c["value"]
        break

session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Origin": SELLER,
    "Referer": f"{SELLER}/portal/",
    "X-CSRFToken": csrf or "",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/json",
})

# Try GraphQL introspection
introspection = {
    "query": """
    query {
        __schema {
            types {
                name
                fields {
                    name
                    type {
                        name
                        kind
                    }
                }
            }
        }
    }
    """
}

print("=== GraphQL Introspection ===")
try:
    resp = session.post(f"{SELLER}/graphql", json=introspection, timeout=15)
    print(f"[{resp.status_code}]")
    if resp.status_code == 200:
        result = resp.json()
        if "data" in result:
            print(json.dumps(result["data"], indent=2)[:2000])
        elif "errors" in result:
            print("Errors:", result["errors"])
        else:
            print(resp.text[:500])
    else:
        print(resp.text[:300])
except Exception as e:
    print(f"Error: {e}")

# Try common seller queries
queries = [
    {"query": "{ shop { id name healthScore } }"},
    {"query": "{ shop { overview { totalProducts totalOrders revenue } } }"},
    {"query": "{ seller { health { score violations warnings } } }"},
    {"query": "{ me { shop { name status } } }"},
]

print("\n=== Common queries ===")
for q in queries:
    try:
        resp = session.post(f"{SELLER}/graphql", json=q, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            if "data" in result and result["data"]:
                print(f"OK {q['query'][:60]}: {json.dumps(result['data'])[:200]}")
            elif "errors" in result:
                print(f"ERR {q['query'][:60]}: {result['errors'][0]['message'][:100]}")
            else:
                print(f"EMPTY {q['query'][:60]}: {resp.text[:100]}")
        else:
            print(f"[{resp.status_code}] {q['query'][:60]}: {resp.text[:100]}")
    except Exception as e:
        print(f"ERR {q['query'][:60]}: {e}")
