from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.logger import debug, info, warning

SELLER_CENTER_URL = "https://seller.shopee.com.br"
COOKIES_FILE = "secrets/seller_center_cookies.json"


@dataclass
class BrowserContext:
    cookies: list[dict[str, Any]] = field(default_factory=list)
    saved_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class SellerCenterBrowser:
    def __init__(self, cookies_path: str = COOKIES_FILE, headless: bool = True):
        self.cookies_path = cookies_path
        self.headless = headless
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    async def start(self) -> None:
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        # Load cookies if available
        cookies = self._load_cookies()
        if cookies:
            await self._context.add_cookies(cookies)
            info(f"Seller Center: {len(cookies)} cookies carregados")
        self._page = await self._context.new_page()
        self._page.set_default_timeout(30000)

    async def stop(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def _load_cookies(self) -> list[dict[str, Any]]:
        path = Path(self.cookies_path)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data if isinstance(data, list) else data.get("cookies", [])
            return [
                {k: v for k, v in c.items() if k in ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")}
                for c in raw
            ]
        except Exception as e:
            warning(f"Failed to load cookies: {e}")
            return []

    async def _navigate(self, path: str) -> None:
        url = f"{SELLER_CENTER_URL}{path}"
        debug(f"Seller Center navigate: {url}")
        await self._page.goto(url, wait_until="networkidle")
        await asyncio.sleep(1)

    async def _wait_for_spa(self, timeout: int = 15) -> bool:
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            return True
        except Exception:
            return False

    async def _is_logged_in(self) -> bool:
        try:
            await self._page.goto(f"{SELLER_CENTER_URL}/portal/login", wait_until="networkidle", timeout=10000)
            current = self._page.url
            # If redirected away from /login, we are logged in
            return "/login" not in current
        except Exception:
            return False

    async def ensure_logged_in(self) -> bool:
        if await self._is_logged_in():
            debug("Seller Center: ja autenticado")
            return True
        warning("Seller Center: nao autenticado. Importe cookies com `laura seller-center-import`")
        return False

    # === Page data extraction methods ===

    async def get_shipping_settings(self) -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/shipping/setting")
        await self._wait_for_spa()
        try:
            await self._page.content()
            result: dict[str, Any] = {"url": self._page.url}
            # Extract warehouse/shipping info from the page
            elements = await self._page.query_selector_all('[class*="shipping"]')
            result["elements_found"] = len(elements)
            return result
        except Exception as e:
            return {"error": str(e)}

    async def get_traffic_dashboard(self) -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/analytics/dashboard")
        await self._wait_for_spa()
        try:
            result: dict[str, Any] = {"url": self._page.url}
            title = await self._page.title()
            result["title"] = title
            return result
        except Exception as e:
            return {"error": str(e)}

    async def get_dispute_list(self) -> list[dict[str, Any]]:
        if not await self.ensure_logged_in():
            return [{"error": "not authenticated"}]
        await self._navigate("/portal/account-health/disputes")
        await self._wait_for_spa()
        results: list[dict[str, Any]] = []
        try:
            rows = await self._page.query_selector_all("table tbody tr")
            for row in rows:
                cells = await row.query_selector_all("td")
                if cells:
                    data = {}
                    texts = await asyncio.gather(*[cell.inner_text() for cell in cells])
                    for i, t in enumerate(texts):
                        data[f"col_{i}"] = t.strip()
                    results.append(data)
        except Exception:
            pass
        return results

    async def get_store_setup(self) -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/shop/setting")
        await self._wait_for_spa()
        try:
            return {"url": self._page.url, "title": await self._page.title()}
        except Exception as e:
            return {"error": str(e)}

    async def get_order_processing_settings(self) -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/shipping/processing")
        await self._wait_for_spa()
        try:
            return {"url": self._page.url, "title": await self._page.title()}
        except Exception as e:
            return {"error": str(e)}

    async def take_screenshot(self, path: str = "reports/seller_center_screenshot.png") -> str:
        await self._page.screenshot(path=path, full_page=True)
        return path

    async def get_current_url(self) -> str:
        return self._page.url

    async def handle_dispute(self, return_sn: str, action: str, reason: str = "") -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/account-health/disputes")
        await self._wait_for_spa()
        result: dict[str, Any] = {"return_sn": return_sn, "action": action}
        try:
            search_input = await self._page.query_selector('input[placeholder*="buscar"], input[placeholder*="search"]')
            if search_input:
                await search_input.fill(return_sn)
                await asyncio.sleep(1)
                await search_input.press("Enter")
                await self._wait_for_spa()
            detail_link = await self._page.query_selector(f'a[href*="{return_sn}"], button:has-text("{return_sn}")')
            if detail_link:
                await detail_link.click()
                await self._wait_for_spa()
                result["navigated_to_detail"] = True
            if action == "accept":
                btn = await self._page.query_selector('button:has-text("Aceitar"), button:has-text("Acceptar")')
                if btn:
                    await btn.click()
                    await self._wait_for_spa()
                    result["action_taken"] = "accept_clicked"
            elif action == "reject":
                btn = await self._page.query_selector('button:has-text("Recusar"), button:has-text("Rejeitar")')
                if btn:
                    await btn.click()
                    await self._wait_for_spa()
                    if reason:
                        textarea = await self._page.query_selector("textarea")
                        if textarea:
                            await textarea.fill(reason)
                            await asyncio.sleep(0.5)
                    confirm = await self._page.query_selector('button:has-text("Confirmar"), button:has-text("Enviar")')
                    if confirm:
                        await confirm.click()
                        await self._wait_for_spa()
                    result["action_taken"] = "reject_clicked"
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
        return result

    async def update_shipping_setting(self, processing_days: int | None = None) -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/shipping/processing")
        await self._wait_for_spa()
        result: dict[str, Any] = {}
        try:
            if processing_days is not None:
                input_el = await self._page.query_selector('input[type="number"]')
                if input_el:
                    await input_el.fill("")
                    await input_el.fill(str(processing_days))
                    await asyncio.sleep(0.5)
                    save_btn = await self._page.query_selector('button:has-text("Salvar"), button:has-text("Save")')
                    if save_btn:
                        await save_btn.click()
                        await self._wait_for_spa()
                        result["processing_days_updated"] = processing_days
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
            result["success"] = False
        return result

    async def get_traffic_data(self) -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/analytics/dashboard")
        await self._wait_for_spa()
        result: dict[str, Any] = {"url": self._page.url}
        try:
            text = await self._page.inner_text("body")
            import re
            visits = re.findall(r'([\d.]+)\s*(visitas|visitantes|views)', text, re.IGNORECASE)
            if visits:
                result["visits"] = [{"value": v[0], "label": v[1]} for v in visits[:5]]
            orders = re.findall(r'([\d.]+)\s*(pedidos|vendas|orders)', text, re.IGNORECASE)
            if orders:
                result["orders"] = [{"value": o[0], "label": o[1]} for o in orders[:5]]
            revenue = re.findall(r'(?:R\$|BRL)\s*([\d.,]+)', text)
            if revenue:
                result["revenue_mentions"] = revenue[:5]
            title = await self._page.title()
            result["title"] = title
        except Exception as e:
            result["error"] = str(e)
        return result

    async def get_performance_data(self) -> dict[str, Any]:
        if not await self.ensure_logged_in():
            return {"error": "not authenticated"}
        await self._navigate("/portal/account-health/overview")
        await self._wait_for_spa()
        result: dict[str, Any] = {"url": self._page.url}
        try:
            text = await self._page.inner_text("body")
            import re
            scores = re.findall(r'([\d.]+)\s*(?:%)\s*(?:de\s*)?(\w+)', text)
            result["metrics_found"] = [{"score": s[0], "metric": s[1]} for s in scores[:10]]
            title = await self._page.title()
            result["title"] = title
        except Exception as e:
            result["error"] = str(e)
        return result

    async def summarize(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "authenticated": False,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if not await self.ensure_logged_in():
            return result
        result["authenticated"] = True
        try:
            traffic = await self.get_traffic_dashboard()
            result["traffic"] = traffic
        except Exception as e:
            result["traffic_error"] = str(e)
        try:
            disputes = await self.get_dispute_list()
            result["disputes_count"] = len(disputes)
            result["disputes"] = disputes[:5]
        except Exception as e:
            result["disputes_error"] = str(e)
        try:
            shipping = await self.get_shipping_settings()
            result["shipping"] = shipping
        except Exception as e:
            result["shipping_error"] = str(e)
        return result
