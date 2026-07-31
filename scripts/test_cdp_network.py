"""Test CDP scrape with Network interception."""
import json, ssl, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import websocket as ws
import requests as req

r = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = r.json()
ws_url = tab.get("webSocketDebuggerUrl", '')

ws_conn = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

msg_id = 0
responses = {}

def cdp(method, params=None):
    global msg_id
    msg_id += 1
    ws_conn.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = ws_conn.recv()
        try:
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data
            # Store network responses
            if data.get("method") == "Network.responseReceived":
                resp_id = data.get("params", {}).get("requestId", "")
                responses[resp_id] = data
        except json.JSONDecodeError:
            continue

# Enable network
cdp("Network.enable")
cdp("Page.enable")

# Navigate to search
cdp("Page.navigate", {"url": "https://shopee.com.br/search?keyword=Xiaomi+Band+8"})
print('Waiting 8s for full page load...')
time.sleep(8)

# Try to get the page's rendered HTML for the search results area
js_get_items = """
(function() {
    // Look for search result elements
    var items = document.querySelectorAll('[data-sqe="item"]');
    if (items.length > 0) {
        return JSON.stringify({count: items.length, found: 'data-sqe'});
    }
    items = document.querySelectorAll('.shopee-search-item-result__item');
    if (items.length > 0) {
        return JSON.stringify({count: items.length, found: 'class'});
    }
    // Try to find data in __NEXT_DATA__ or similar
    var scripts = document.querySelectorAll('script');
    for (var s of scripts) {
        if (s.id === '__NEXT_DATA__' || s.id === '__INITIAL_STATE__') {
            return JSON.stringify({script_id: s.id, data: s.textContent.substring(0, 2000)});
        }
    }
    // Check if we can see any item in the page
    var allText = document.body ? document.body.innerText.substring(0, 500) : 'no body';
    return JSON.stringify({no_items: true, bodyText: allText, url: window.location.href, title: document.title});
})()
"""
result = cdp("Runtime.evaluate", {"expression": js_get_items, "awaitPromise": False})
val = result.get("result", {}).get("value", "{}")
print(f'Page state: {val[:500]}')

# Check if there's any search API response captured
for req_id, resp_data in list(responses.items())[:5]:
    params = resp_data.get("params", {})
    resp = params.get("response", {})
    url = resp.get("url", "")
    if "search" in url.lower() or "api" in url.lower():
        print(f'Network: {resp.get("status")} {url[:80]}')

# Try to get the response body of search API via Network.getResponseBody
# First list all requests
result2 = cdp("Runtime.evaluate", {"expression": "JSON.stringify(performance.getEntriesByType('resource').filter(e => e.name.includes('search')).map(e => ({name: e.name.substring(0,80), type: e.initiatorType})))"})
val2 = result2.get("result", {}).get("value", "[]")
print(f'API calls: {val2[:300]}')

ws_conn.close()
