"""Browser automation skill using Playwright (or CDP fallback)."""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

from .registry import Skill, default_registry

# ---------------------------------------------------------------------------
# CDP-only client (fallback when playwright is not installed)
# ---------------------------------------------------------------------------


class _CDPClient:
    """Minimal CDP client over WebSocket."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self._host = host
        self._port = port
        self._ws = None
        self._msg_id = 0

    def _connect(self):
        import ssl as _ssl

        import requests as _req
        import websocket as _ws
        tabs = _req.get(
            f"http://{self._host}:{self._port}/json", timeout=5
        ).json()
        target = next((t for t in tabs if t.get("type") == "page"), None)
        if not target:
            resp = _req.put(
                f"http://{self._host}:{self._port}/json/new", timeout=5
            )
            target = resp.json()
        ws_url = target["webSocketDebuggerUrl"]
        self._ws = _ws.create_connection(
            ws_url,
            timeout=30,
            sslopt={"cert_reqs": _ssl.CERT_NONE}
            if ws_url.startswith("wss")
            else {},
        )
        self._send("Page.enable")
        self._send("Runtime.enable")

    def _send(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        payload = {
            "id": self._msg_id,
            "method": method,
            "params": params or {},
        }
        self._ws.send(json.dumps(payload))
        while True:
            raw = self._ws.recv()
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                return data

    def _eval(self, js: str) -> Any:
        resp = self._send(
            "Runtime.evaluate",
            {
                "expression": js,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        inner = resp.get("result", {})
        exc = inner.get("exceptionDetails")
        if exc:
            raise RuntimeError(
                f"JS exception: {exc.get('text', '')} | {exc.get('exception', {}).get('description', '')}"
            )
        return (inner.get("result") or {}).get("value")

    def navigate(self, url: str):
        self._send("Page.navigate", {"url": url})

    def click(self, selector: str):
        self._eval(
            f"document.querySelector({json.dumps(selector)})?.click();"
        )

    def type_text(self, selector: str, value: str):
        self._eval(
            f"const el = document.querySelector({json.dumps(selector)});"
            f"if (el) {{"
            f"  el.value = {json.dumps(value)};"
            f"  el.dispatchEvent(new Event('input', {{bubbles:true}}));"
            f"  el.dispatchEvent(new Event('change', {{bubbles:true}}));"
            f"}}"
        )

    def screenshot(self) -> bytes:
        resp = self._send("Page.captureScreenshot", {"format": "png"})
        data = (resp.get("result") or {}).get("data", "")
        return base64.b64decode(data)

    def extract_text(self, selector: str = "body") -> str:
        js = (
            f"document.querySelector({json.dumps(selector)})?.innerText || ''"
        )
        return str(self._eval(js) or "")

    def extract_html(self, selector: str = "html") -> str:
        js = (
            f"document.querySelector({json.dumps(selector)})?.innerHTML || ''"
        )
        return str(self._eval(js) or "")

    def wait_for_selector(self, selector: str, timeout: float = 10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            val = self._eval(
                f"document.querySelector({json.dumps(selector)}) !== null"
            )
            if val:
                return True
            time.sleep(0.3)
        raise TimeoutError(
            f"Selector '{selector}' not found within {timeout}s"
        )

    def scroll(self, x: int = 0, y: int = 0):
        self._eval(f"window.scrollBy({x}, {y})")

    def evaluate_js(self, expression: str) -> Any:
        return self._eval(expression)

    def close(self):
        if self._ws:
            self._ws.close()


# ---------------------------------------------------------------------------
# Browser Skill
# ---------------------------------------------------------------------------

_playwright = None
try:
    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright
except ImportError:
    pass


class BrowserSkill(Skill):
    name = "browser_skill"
    risk_level = "MEDIUM"
    preconditions = {"browser_available": True}
    effects = {"browser_action_completed": True}
    cost = 3.0
    priority = 1

    ACTIONS = frozenset(
        {
            "navigate",
            "click",
            "type",
            "screenshot",
            "extract_text",
            "extract_html",
            "wait_for_selector",
            "scroll",
            "evaluate_js",
        }
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def validate_params(self, params: dict) -> bool:
        if not isinstance(params, dict):
            return False
        action = params.get("action", "")
        if action not in self.ACTIONS:
            return False
        if action in ("navigate",) and not params.get("url"):
            return False
        if action in (
            "click",
            "type",
            "extract_text",
            "extract_html",
            "wait_for_selector",
        ) and not params.get("selector"):
            return False
        if action == "type" and "value" not in params:
            return False
        return True

    def run(self, params: dict | None = None, **kwargs) -> dict:
        p = params or kwargs
        if not self.validate_params(p):
            return {
                "ok": False,
                "result": None,
                "screenshot_path": None,
                "error": "Invalid parameters",
            }

        action = p["action"]
        url = p.get("url", "")
        selector = p.get("selector", "")
        value = p.get("value", "")
        take_screenshot = p.get("screenshot", False)

        if _playwright is not None:
            return self._run_playwright(
                action, url, selector, value, take_screenshot, p
            )
        return self._run_cdp(
            action, url, selector, value, take_screenshot, p
        )

    # ---- Playwright implementation ----

    def _run_playwright(
        self, action, url, selector, value, take_screenshot, params
    ) -> dict:
        screenshot_path = None
        result = None
        with _playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                result = self._pw_action(
                    page, action, url, selector, value, params
                )
                if take_screenshot:
                    path = (
                        params.get("screenshot_path", "")
                        or "browser_screenshot.png"
                    )
                    page.screenshot(path=path)
                    screenshot_path = path
            except Exception as exc:
                return {
                    "ok": False,
                    "result": None,
                    "screenshot_path": None,
                    "error": str(exc),
                }
            finally:
                browser.close()
        return {
            "ok": True,
            "result": result,
            "screenshot_path": screenshot_path,
        }

    @staticmethod
    def _pw_action(page, action, url, selector, value, params):
        if action == "navigate":
            page.goto(url, wait_until="domcontentloaded")
            return page.url
        if action == "click":
            page.click(selector)
            return True
        if action == "type":
            page.fill(selector, value)
            return True
        if action == "screenshot":
            path = (
                params.get("screenshot_path", "")
                or "browser_screenshot.png"
            )
            page.screenshot(path=path)
            return path
        if action == "extract_text":
            els = (
                page.query_selector_all(selector)
                if selector != "body"
                else [page]
            )
            return els[0].inner_text() if els else ""
        if action == "extract_html":
            els = page.query_selector_all(selector) if selector else [page]
            return els[0].inner_html() if els else ""
        if action == "wait_for_selector":
            page.wait_for_selector(selector, timeout=10000)
            return True
        if action == "scroll":
            page.evaluate(
                f"window.scrollBy({params.get('x', 0)}, {params.get('y', 0)})"
            )
            return True
        if action == "evaluate_js":
            return page.evaluate(params.get("expression", ""))
        raise ValueError(f"Unknown action: {action}")

    # ---- CDP fallback implementation ----

    def _run_cdp(
        self, action, url, selector, value, take_screenshot, params
    ) -> dict:
        client = _CDPClient()
        try:
            client._connect()
            result = self._cdp_action(
                client, action, url, selector, value, params
            )
            screenshot_path = None
            if take_screenshot:
                data = client.screenshot()
                path = (
                    params.get("screenshot_path", "")
                    or "browser_screenshot.png"
                )
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
                screenshot_path = path
            return {
                "ok": True,
                "result": result,
                "screenshot_path": screenshot_path,
            }
        except Exception as exc:
            return {
                "ok": False,
                "result": None,
                "screenshot_path": None,
                "error": str(exc),
            }
        finally:
            client.close()

    @staticmethod
    def _cdp_action(client, action, url, selector, value, params):
        if action == "navigate":
            client.navigate(url)
            time.sleep(2)
            return client._eval("window.location.href")
        if action == "click":
            client.wait_for_selector(selector)
            client.click(selector)
            return True
        if action == "type":
            client.wait_for_selector(selector)
            client.type_text(selector, value)
            return True
        if action == "screenshot":
            data = client.screenshot()
            path = (
                params.get("screenshot_path", "")
                or "browser_screenshot.png"
            )
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            return path
        if action == "extract_text":
            return client.extract_text(selector or "body")
        if action == "extract_html":
            return client.extract_html(selector or "html")
        if action == "wait_for_selector":
            client.wait_for_selector(selector)
            return True
        if action == "scroll":
            client.scroll(params.get("x", 0), params.get("y", 0))
            return True
        if action == "evaluate_js":
            return client.evaluate_js(params.get("expression", ""))
        raise ValueError(f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# Seller Center Browser Skill
# ---------------------------------------------------------------------------


class SellerCenterBrowserSkill(BrowserSkill):
    name = "seller_center_browser"
    risk_level = "HIGH"
    preconditions = {
        "browser_available": True,
        "seller_center_logged_in": True,
    }
    effects = {"seller_center_action_completed": True}
    cost = 5.0
    priority = 2

    SELLER_CENTER_ACTIONS = frozenset(
        {
            "login",
            "get_orders",
            "update_price",
            "update_stock",
            "get_dashboard",
        }
    )

    def validate_params(self, params: dict) -> bool:
        if not isinstance(params, dict):
            return False
        action = params.get("action", "")
        if action in self.SELLER_CENTER_ACTIONS:
            return True
        return super().validate_params(params)

    def run(self, params: dict | None = None, **kwargs) -> dict:
        p = params or kwargs
        action = p.get("action", "")
        if action not in self.SELLER_CENTER_ACTIONS:
            return super().run(p)
        if _playwright is not None:
            return self._run_sc_playwright(action, p)
        return self._run_sc_cdp(action, p)

    def _inject_cookies(self, ctx_or_client) -> bool:
        """Load saved cookies and inject into the browser context."""
        try:
            from shopee_agent.seller_center import load_cookies

            session = load_cookies()
            if not session or not session.cookies:
                return False
            return True
        except Exception:
            return False

    def _run_sc_playwright(self, action: str, params: dict) -> dict:
        result = None
        screenshot_path = None
        with _playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                if action == "login":
                    self._inject_cookies(ctx)
                    url = params.get(
                        "url", "https://seller.shopee.com.br/"
                    )
                    page.goto(url, wait_until="domcontentloaded")
                    result = {
                        "url": page.url,
                        "title": page.title(),
                    }

                elif action == "get_orders":
                    url = params.get(
                        "url",
                        "https://seller.shopee.com.br/portal/orders",
                    )
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    row_sel = params.get("row_selector", "table tr")
                    rows = page.query_selector_all(row_sel)
                    result = [row.inner_text() for row in rows[:50]]

                elif action == "update_price":
                    item_id = params.get("item_id", "")
                    price = params.get("price", 0)
                    url = params.get(
                        "url",
                        f"https://seller.shopee.com.br/portal/product/{item_id}",
                    )
                    page.goto(url, wait_until="domcontentloaded")
                    sel = params.get(
                        "price_selector",
                        "input[data-testid='price-input']",
                    )
                    page.fill(sel, str(price))
                    save_sel = params.get(
                        "save_selector", "button[type='submit']"
                    )
                    page.click(save_sel)
                    page.wait_for_timeout(2000)
                    result = {
                        "item_id": item_id,
                        "price_updated": True,
                    }

                elif action == "update_stock":
                    item_id = params.get("item_id", "")
                    stock = params.get("stock", 0)
                    url = params.get(
                        "url",
                        f"https://seller.shopee.com.br/portal/product/{item_id}",
                    )
                    page.goto(url, wait_until="domcontentloaded")
                    sel = params.get(
                        "stock_selector",
                        "input[data-testid='stock-input']",
                    )
                    page.fill(sel, str(stock))
                    save_sel = params.get(
                        "save_selector", "button[type='submit']"
                    )
                    page.click(save_sel)
                    page.wait_for_timeout(2000)
                    result = {
                        "item_id": item_id,
                        "stock_updated": True,
                    }

                elif action == "get_dashboard":
                    page.goto(
                        "https://seller.shopee.com.br/",
                        wait_until="domcontentloaded",
                    )
                    page.wait_for_timeout(3000)
                    result = {
                        "url": page.url,
                        "title": page.title(),
                        "body_snippet": page.evaluate(
                            "document.body.innerText.substring(0, 3000)"
                        ),
                    }

                if params.get("screenshot"):
                    path = (
                        params.get("screenshot_path", "")
                        or "seller_center_screenshot.png"
                    )
                    page.screenshot(path=path)
                    screenshot_path = path

            except Exception as exc:
                return {
                    "ok": False,
                    "result": None,
                    "screenshot_path": None,
                    "error": str(exc),
                }
            finally:
                browser.close()
        return {
            "ok": True,
            "result": result,
            "screenshot_path": screenshot_path,
        }

    def _run_sc_cdp(self, action: str, params: dict) -> dict:
        client = _CDPClient()
        try:
            client._connect()
            try:
                from shopee_agent.seller_center import load_cookies

                session = load_cookies()
                if session:
                    client._send("Network.enable")
                    for c in session.cookies:
                        client._send(
                            "Network.setCookie",
                            {
                                "name": c.name,
                                "value": c.value,
                                "domain": c.domain
                                or "seller.shopee.com.br",
                                "path": c.path or "/",
                            },
                        )
            except Exception:
                pass

            result = None
            screenshot_path = None

            if action == "login":
                url = params.get(
                    "url", "https://seller.shopee.com.br/"
                )
                client.navigate(url)
                time.sleep(3)
                result = {
                    "url": client._eval("window.location.href"),
                    "title": client._eval("document.title"),
                }

            elif action == "get_orders":
                url = params.get(
                    "url",
                    "https://seller.shopee.com.br/portal/orders",
                )
                client.navigate(url)
                time.sleep(4)
                html = client.extract_html("body")
                result = {"html_snippet": html[:5000]}

            elif action == "update_price":
                item_id = params.get("item_id", "")
                price = params.get("price", 0)
                url = params.get(
                    "url",
                    f"https://seller.shopee.com.br/portal/product/{item_id}",
                )
                client.navigate(url)
                time.sleep(4)
                sel = params.get(
                    "price_selector",
                    "input[data-testid='price-input']",
                )
                client.wait_for_selector(sel)
                client.type_text(sel, str(price))
                save_sel = params.get(
                    "save_selector", "button[type='submit']"
                )
                client.click(save_sel)
                result = {"item_id": item_id, "price_updated": True}

            elif action == "update_stock":
                item_id = params.get("item_id", "")
                stock = params.get("stock", 0)
                url = params.get(
                    "url",
                    f"https://seller.shopee.com.br/portal/product/{item_id}",
                )
                client.navigate(url)
                time.sleep(4)
                sel = params.get(
                    "stock_selector",
                    "input[data-testid='stock-input']",
                )
                client.wait_for_selector(sel)
                client.type_text(sel, str(stock))
                save_sel = params.get(
                    "save_selector", "button[type='submit']"
                )
                client.click(save_sel)
                result = {"item_id": item_id, "stock_updated": True}

            elif action == "get_dashboard":
                client.navigate("https://seller.shopee.com.br/")
                time.sleep(3)
                body = client.extract_text("body")
                result = {
                    "url": client._eval("window.location.href"),
                    "title": client._eval("document.title"),
                    "body_snippet": body[:3000],
                }

            if params.get("screenshot"):
                data = client.screenshot()
                path = (
                    params.get("screenshot_path", "")
                    or "seller_center_screenshot.png"
                )
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
                screenshot_path = path

            return {
                "ok": True,
                "result": result,
                "screenshot_path": screenshot_path,
            }
        except Exception as exc:
            return {
                "ok": False,
                "result": None,
                "screenshot_path": None,
                "error": str(exc),
            }
        finally:
            client.close()


default_registry.register(BrowserSkill)
default_registry.register(SellerCenterBrowserSkill)
