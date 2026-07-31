"""Seller Center full automation module.

Provides SellerCenterAutomator (high-level API, no browser internals exposed)
and SellerCenterFullSkill (GOAP skill wrapper).
"""

from __future__ import annotations

import csv
import json
import os
import time
from contextlib import contextmanager
from typing import Any

from .skills.browser_skill import _CDPClient
from .skills.registry import Skill, default_registry

# ---------------------------------------------------------------------------
# Playwright availability
# ---------------------------------------------------------------------------

_playwright = None
try:
    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Unified browser page wrapper
# ---------------------------------------------------------------------------


class _BrowserPage:
    """Unified wrapper around Playwright ``Page`` or ``_CDPClient``.

    Automator methods use this single interface so they never have to branch
    on the underlying automation engine.
    """

    def __init__(self, impl: Any):
        self._impl = impl
        self._is_pw = not isinstance(impl, _CDPClient)

    # -- Navigation ---------------------------------------------------------

    def goto(self, url: str, timeout_ms: int = 30000):
        if self._is_pw:
            self._impl.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        else:
            self._impl.navigate(url)
            self.wait_for_timeout(2500)

    # -- Waiting ------------------------------------------------------------

    def wait_for_selector(self, selector: str, timeout_ms: int = 10000):
        if self._is_pw:
            self._impl.wait_for_selector(selector, timeout=timeout_ms)
        else:
            self._impl.wait_for_selector(selector, timeout=timeout_ms / 1000.0)

    def wait_for_timeout(self, ms: int):
        if self._is_pw:
            self._impl.wait_for_timeout(ms)
        else:
            time.sleep(ms / 1000.0)

    # -- Interaction --------------------------------------------------------

    def fill(self, selector: str, value: str):
        if self._is_pw:
            self._impl.fill(selector, value)
        else:
            self._impl.wait_for_selector(selector)
            self._impl.type_text(selector, value)

    def click(self, selector: str):
        if self._is_pw:
            self._impl.click(selector)
        else:
            self._impl.wait_for_selector(selector)
            self._impl.click(selector)

    def select_option(self, selector: str, value: str):
        if self._is_pw:
            self._impl.select_option(selector, value)
        else:
            js = (
                f"const el = document.querySelector({json.dumps(selector)});"
                f"if (el) {{ el.value = {json.dumps(value)}; "
                f"el.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
            )
            self._impl._eval(js)

    def type_text(self, selector: str, value: str):
        if self._is_pw:
            self._impl.type(selector, value)
        else:
            self._impl.wait_for_selector(selector)
            self._impl.type_text(selector, value)

    def press_enter(self, selector: str | None = None):
        if selector:
            if self._is_pw:
                self._impl.press(selector, "Enter")
            else:
                el = self._impl._eval(
                    f"document.querySelector({json.dumps(selector)})"
                )
                if el:
                    self._impl._eval(
                        f"document.querySelector({json.dumps(selector)})"
                        f"?.['dispatchEvent']?.(new KeyboardEvent('keydown', {{key:'Enter'}}));"
                    )
        else:
            if self._is_pw:
                self._impl.keyboard.press("Enter")
            else:
                self._impl._eval(
                    "document.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter'}));"
                )

    # -- Data extraction ----------------------------------------------------

    def evaluate(self, js: str) -> Any:
        if self._is_pw:
            return self._impl.evaluate(js)
        return self._impl._eval(js)

    def inner_text(self, selector: str = "body") -> str:
        if self._is_pw:
            els = (
                self._impl.query_selector_all(selector)
                if selector != "body"
                else [self._impl]
            )
            return els[0].inner_text() if els else ""
        return self._impl.extract_text(selector)

    def inner_html(self, selector: str = "html") -> str:
        if self._is_pw:
            els = (
                self._impl.query_selector_all(selector)
                if selector
                else [self._impl]
            )
            return els[0].inner_html() if els else ""
        return self._impl.extract_html(selector)

    def query_selector(self, selector: str):
        if self._is_pw:
            return self._impl.query_selector(selector)
        return None

    def query_selector_all(self, selector: str):
        if self._is_pw:
            return self._impl.query_selector_all(selector)
        return []

    def query_selector_text(self, selector: str) -> str:
        if self._is_pw:
            el = self._impl.query_selector(selector)
            return el.inner_text() if el else ""
        return self._impl.extract_text(selector)

    # -- Screenshot ---------------------------------------------------------

    def screenshot(self, path: str):
        if self._is_pw:
            self._impl.screenshot(path=path)
        else:
            data = self._impl.screenshot()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)

    # -- Navigation properties ----------------------------------------------

    @property
    def url(self) -> str:
        if self._is_pw:
            return self._impl.url
        return str(self._impl._eval("window.location.href") or "")

    @property
    def title(self) -> str:
        if self._is_pw:
            return self._impl.title()
        return str(self._impl._eval("document.title") or "")


# ---------------------------------------------------------------------------
# SellerCenterAutomator
# ---------------------------------------------------------------------------


class SellerCenterAutomator:
    """High-level Seller Center automation, no browser internals exposed."""

    BASE_URL = "https://seller.shopee.com.br"

    DEFAULT_SELECTORS = {
        "price_input": "input[data-testid='price-input']",
        "stock_input": "input[data-testid='stock-input']",
        "save_button": "button[type='submit']",
        "product_row": "table tr",
        "order_row": "table tbody tr",
        "search_input": "input[placeholder*='buscar' i], input[placeholder*='search' i]",
        "confirm_button": "button:has-text('Confirmar'), button:has-text('Confirm')",
        "cancel_button": "button:has-text('Cancelar'), button:has-text('Cancel')",
        "modal_confirm": ".eds-modal button:has-text('Confirmar'), .eds-modal button:has-text('Confirm')",
        "switch_toggle": ".eds-switch",
        "toast_message": ".eds-toast, .toast, [class*='toast']",
    }

    def __init__(
        self,
        client=None,
        access_token: str | None = None,
        shop_id: str | None = None,
        headless: bool = True,
    ):
        self._client = client
        self._access_token = access_token
        self._shop_id = shop_id
        self._headless = headless

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _browser(self):
        """Context manager yielding a ``_BrowserPage`` ready to use."""
        if _playwright is not None:
            with _playwright() as pw:
                browser = pw.chromium.launch(headless=self._headless)
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )
                page = ctx.new_page()
                page.set_default_timeout(30000)
                self._inject_cookies(ctx)
                try:
                    yield _BrowserPage(page)
                finally:
                    browser.close()
        else:
            client = _CDPClient()
            try:
                client._connect()
                self._inject_cdp_cookies(client)
                yield _BrowserPage(client)
            finally:
                client.close()

    def _inject_cookies(self, context):
        """Inject saved Seller Center cookies into a Playwright context."""
        try:
            from .seller_center import load_cookies

            session = load_cookies()
            if session and session.cookies:
                pw_cookies = []
                for c in session.cookies:
                    pw_cookies.append(
                        {
                            "name": c.name,
                            "value": c.value,
                            "domain": c.domain or "seller.shopee.com.br",
                            "path": c.path or "/",
                            "secure": c.secure,
                            "httpOnly": c.httpOnly,
                            "sameSite": c.sameSite or "Lax",
                        }
                    )
                if pw_cookies:
                    context.add_cookies(pw_cookies)
        except Exception:
            pass

    def _inject_cdp_cookies(self, client: _CDPClient):
        """Inject saved cookies into a CDP session."""
        try:
            from .seller_center import load_cookies

            session = load_cookies()
            if session and session.cookies:
                client._send("Network.enable")
                for c in session.cookies:
                    params = {
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain or "seller.shopee.com.br",
                        "path": c.path or "/",
                        "secure": c.secure,
                        "httpOnly": c.httpOnly,
                    }
                    if c.expirationDate:
                        params["expires"] = c.expirationDate
                    if c.sameSite:
                        params["sameSite"] = c.sameSite
                    client._send("Network.setCookie", params)
        except Exception:
            pass

    def _extract_page_data(self, page: _BrowserPage) -> dict:
        """Try to extract structured data from common SPA data stores."""
        for var in [
            "window.__INITIAL_STATE__",
            "window.__NUXT__",
            "window.__DATA__",
            "window.__STORE__",
            "window.__PRELOADED_STATE__",
        ]:
            try:
                raw = page.evaluate(f"JSON.stringify({var})")
                if raw and raw != "undefined" and raw != "null":
                    return json.loads(raw)
            except Exception:
                continue
        return {}

    def _table_to_dicts(self, page: _BrowserPage, row_selector: str) -> list[dict]:
        """Parse an HTML table into a list of dicts using page.evaluate."""
        js = f"""() => {{
            const rows = document.querySelectorAll('{row_selector}');
            const headers = [];
            const thead = document.querySelector('table thead tr');
            if (thead) {{
                thead.querySelectorAll('th, td').forEach(th => headers.push(th.textContent.trim()));
            }}
            const result = [];
            rows.forEach(row => {{
                const cells = row.querySelectorAll('td');
                const obj = {{}};
                cells.forEach((cell, i) => {{
                    const key = headers[i] || `col_${{i}}`;
                    obj[key] = cell.textContent.trim();
                }});
                if (Object.keys(obj).length) result.push(obj);
            }});
            return JSON.stringify(result);
        }}"""
        try:
            raw = page.evaluate(js)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return []

    def _wait_for_toast(self, page: _BrowserPage, timeout_ms: int = 5000) -> str | None:
        """Wait for a toast notification and return its text."""
        sel = self.DEFAULT_SELECTORS["toast_message"]
        try:
            page.wait_for_selector(sel, timeout_ms=timeout_ms)
            return page.inner_text(sel)
        except Exception:
            return None

    def _click_save(self, page: _BrowserPage, selector: str | None = None):
        """Find and click a save / submit / update button."""
        sel = selector or self.DEFAULT_SELECTORS["save_button"]
        try:
            page.click(sel)
        except Exception:
            try:
                page.evaluate(
                    """() => {
                        const btns = document.querySelectorAll('button');
                        for (const b of btns) {
                            const t = b.textContent.toLowerCase().trim();
                            if (['salvar', 'save', 'atualizar', 'update', 'publicar', 'publish'].includes(t)) {
                                b.click(); return true;
                            }
                        }
                        return false;
                    }"""
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Product Management
    # ------------------------------------------------------------------

    def list_products(self, page: int = 1, page_size: int = 100, **kwargs) -> list[dict]:
        url = kwargs.get(
            "url",
            f"{self.BASE_URL}/portal/product/list?page={page}&page_size={page_size}",
        )
        row_sel = kwargs.get("row_selector", self.DEFAULT_SELECTORS["product_row"])
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                return self._extract_products_from_state(data)

            return self._table_to_dicts(p, row_sel)

    def get_product_detail(self, item_id: str, **kwargs) -> dict:
        url = kwargs.get(
            "url", f"{self.BASE_URL}/portal/product/{item_id}"
        )
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                result = {"item_id": item_id, "extracted_from_state": True}
                if "product" in data:
                    result["product"] = data["product"]
                elif "item" in data:
                    result["product"] = data["item"]
                else:
                    result["page_data"] = str(data)[:2000]
                return result

            body = p.inner_text("body")
            return {
                "item_id": item_id,
                "title": p.title,
                "url": p.url,
                "body_snippet": body[:3000],
            }

    def create_product(self, data: dict, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/add")
        selectors = {**self.DEFAULT_SELECTORS, **kwargs}

        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            name = data.get("name", "")
            description = data.get("description", "")
            price = data.get("price", 0)
            stock = data.get("stock", 0)
            category = data.get("category", "")
            weight = data.get("weight", 0)
            images = data.get("images", [])
            variations = data.get("variations", [])
            shipping = data.get("shipping", {})

            try:
                # Name
                name_sel = kwargs.get("name_selector", "input[data-testid='product-name'], input[name='name'], input[placeholder*='nome' i]")
                if name:
                    p.fill(name_sel, name)

                # Description
                desc_sel = kwargs.get("desc_selector", "textarea[data-testid='description'], textarea[name='description'], [contenteditable='true']")
                if description:
                    p.fill(desc_sel, description)

                # Category
                if category:
                    cat_sel = kwargs.get("category_selector", "select[data-testid='category'], .category-selector input, input[placeholder*='categoria' i]")
                    try:
                        p.select_option(cat_sel, category)
                    except Exception:
                        try:
                            p.fill(cat_sel, category)
                        except Exception:
                            pass

                # Price
                if price:
                    p.fill(selectors["price_input"], str(price))

                # Stock
                if stock:
                    p.fill(selectors["stock_input"], str(stock))

                # Weight
                if weight:
                    weight_sel = kwargs.get("weight_selector", "input[data-testid='weight'], input[name='weight'], input[placeholder*='peso' i]")
                    p.fill(weight_sel, str(weight))

                # Variations
                for i, var in enumerate(variations):
                    var_name = var.get("name", f"Variacao {i + 1}")
                    var_price = var.get("price", price)
                    var_stock = var.get("stock", stock)
                    var_name_sel = kwargs.get("var_name_selector", f"input[name='variations[{i}].name'], .variation-item input")
                    var_price_sel = kwargs.get("var_price_selector", f"input[name='variations[{i}].price']")
                    var_stock_sel = kwargs.get("var_stock_selector", f"input[name='variations[{i}].stock']")
                    try:
                        p.fill(var_name_sel, var_name)
                        p.fill(var_price_sel, str(var_price))
                        p.fill(var_stock_sel, str(var_stock))
                    except Exception:
                        pass

                # Images
                if images:
                    for idx, img_url in enumerate(images):
                        img_sel = kwargs.get("image_selector", "input[type='file'], input[data-testid='image-upload']")
                        try:
                            p.fill(img_sel, img_url)
                        except Exception:
                            pass

                # Shipping
                if shipping:
                    kwargs.get("shipping_selector", "select[name='shipping'], .shipping-config input")
                    try:
                        if isinstance(shipping, dict):
                            for key, val in shipping.items():
                                s = f"input[name='shipping.{key}'], select[name='shipping.{key}']"
                                try:
                                    p.fill(s, str(val))
                                except Exception:
                                    try:
                                        p.select_option(s, str(val))
                                    except Exception:
                                        pass
                    except Exception:
                        pass

                self._click_save(p, selectors.get("save_button"))
                p.wait_for_timeout(3000)

                toast = self._wait_for_toast(p)
                current_url = p.url
                item_id = kwargs.get("item_id", "")
                if not item_id and "product/" in current_url:
                    item_id = current_url.split("product/")[-1].split("/")[0].split("?")[0]

                return {
                    "success": True,
                    "item_id": item_id,
                    "url": current_url,
                    "toast": toast,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

    def update_product(self, item_id: str, updates: dict, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        selectors = {**self.DEFAULT_SELECTORS, **kwargs}

        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            try:
                for field, value in updates.items():
                    sel_key = f"{field}_selector"
                    sel = kwargs.get(sel_key, f"input[name='{field}'], [data-testid='{field}']")
                    try:
                        p.fill(sel, str(value))
                    except Exception:
                        pass
                self._click_save(p, selectors.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def delete_product(self, item_id: str, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                delete_sel = kwargs.get("delete_selector", "button:has-text('Excluir'), button:has-text('Delete'), button:has-text('Remover')")
                p.click(delete_sel)
                p.wait_for_timeout(1000)
                confirm_sel = kwargs.get("confirm_selector", self.DEFAULT_SELECTORS["modal_confirm"])
                try:
                    p.click(confirm_sel)
                except Exception:
                    try:
                        p.click(self.DEFAULT_SELECTORS["confirm_button"])
                    except Exception:
                        pass
                p.wait_for_timeout(2000)
                toast = self._wait_for_toast(p)
                return toast is None or "sucesso" in toast.lower() or "success" in toast.lower()
            except Exception:
                return False

    def update_variations(self, item_id: str, variations: list[dict], **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                for i, var in enumerate(variations):
                    var_name_sel = kwargs.get("var_name_selector", f"input[name='variations[{i}].name'], .variation-item:nth-child({i + 1}) input")
                    var_price_sel = kwargs.get("var_price_selector", f"input[name='variations[{i}].price']")
                    var_stock_sel = kwargs.get("var_stock_selector", f"input[name='variations[{i}].stock']")
                    if "name" in var:
                        try:
                            p.fill(var_name_sel, var["name"])
                        except Exception:
                            pass
                    if "price" in var:
                        try:
                            p.fill(var_price_sel, str(var["price"]))
                        except Exception:
                            pass
                    if "stock" in var:
                        try:
                            p.fill(var_stock_sel, str(var["stock"]))
                        except Exception:
                            pass
                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def update_images(self, item_id: str, image_urls: list[str], **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                for idx, img_url in enumerate(image_urls):
                    img_sel = kwargs.get("image_selector", "input[type='file'], input[data-testid='image-upload'], .image-upload input")
                    try:
                        p.fill(img_sel, img_url)
                        p.wait_for_timeout(500)
                    except Exception:
                        pass
                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def update_shipping(self, item_id: str, shipping_info: dict, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                shipping_tab = kwargs.get("shipping_tab_selector", "button:has-text('Shipping'), button:has-text('Frete'), button:has-text('Envio'), [data-testid='shipping-tab']")
                try:
                    p.click(shipping_tab)
                    p.wait_for_timeout(1000)
                except Exception:
                    pass

                for key, val in shipping_info.items():
                    sel = kwargs.get(f"shipping_{key}_selector", f"input[name='shipping.{key}'], select[name='shipping.{key}'], [data-testid='shipping-{key}']")
                    try:
                        if isinstance(val, bool):
                            try:
                                if val:
                                    p.click(sel)
                            except Exception:
                                pass
                        else:
                            try:
                                p.fill(sel, str(val))
                            except Exception:
                                try:
                                    p.select_option(sel, str(val))
                                except Exception:
                                    pass
                    except Exception:
                        pass

                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def update_description(self, item_id: str, description: str, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                desc_tab = kwargs.get("desc_tab_selector", "button:has-text('Descricao'), button:has-text('Description'), [data-testid='description-tab']")
                try:
                    p.click(desc_tab)
                    p.wait_for_timeout(1000)
                except Exception:
                    pass

                desc_sel = kwargs.get("desc_selector", "textarea[data-testid='description'], textarea[name='description'], [contenteditable='true']")
                p.fill(desc_sel, description)

                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    # ------------------------------------------------------------------
    # Order Management
    # ------------------------------------------------------------------

    def list_orders(self, status: str = "all", days: int = 7, **kwargs) -> list[dict]:
        url = kwargs.get(
            "url",
            f"{self.BASE_URL}/portal/orders?status={status}&days={days}",
        )
        row_sel = kwargs.get("row_selector", self.DEFAULT_SELECTORS["order_row"])
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                orders = self._extract_orders_from_state(data)
                if orders:
                    return orders

            return self._table_to_dicts(p, row_sel)

    def get_order_detail(self, order_sn: str, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/orders/{order_sn}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                result = {"order_sn": order_sn, "extracted_from_state": True}
                if "order" in data:
                    result["order"] = data["order"]
                else:
                    result["page_data"] = str(data)[:2000]
                return result

            body = p.inner_text("body")
            return {
                "order_sn": order_sn,
                "title": p.title,
                "url": p.url,
                "body_snippet": body[:3000],
            }

    def ship_order(self, order_sn: str, logistics: dict, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/orders/{order_sn}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                ship_btn = kwargs.get("ship_btn_selector", "button:has-text('Enviar'), button:has-text('Ship'), button:has-text(' despachar'), [data-testid='ship-button']")
                p.click(ship_btn)
                p.wait_for_timeout(1500)

                for key, val in logistics.items():
                    sel = kwargs.get(f"logistics_{key}_selector", f"input[name='{key}'], select[name='{key}'], [data-testid='{key}']")
                    try:
                        p.fill(sel, str(val))
                    except Exception:
                        try:
                            p.select_option(sel, str(val))
                        except Exception:
                            pass

                confirm_sel = kwargs.get("confirm_selector", self.DEFAULT_SELECTORS["confirm_button"])
                p.click(confirm_sel)
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def cancel_order(self, order_sn: str, reason: str = "", **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/orders/{order_sn}")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                cancel_btn = kwargs.get("cancel_btn_selector", "button:has-text('Cancelar'), button:has-text('Cancel'), [data-testid='cancel-button']")
                p.click(cancel_btn)
                p.wait_for_timeout(1500)

                if reason:
                    reason_sel = kwargs.get("reason_selector", "textarea[name='reason'], textarea[placeholder*='motivo' i], .reason-input textarea")
                    try:
                        p.fill(reason_sel, reason)
                    except Exception:
                        pass

                confirm_sel = kwargs.get("confirm_selector", self.DEFAULT_SELECTORS["confirm_button"])
                p.click(confirm_sel)
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def bulk_ship_orders(self, order_list: list[dict], **kwargs) -> dict:
        shipped = []
        failed = []
        for order in order_list:
            order_sn = order.get("order_sn", "")
            logistics = order.get("logistics", {})
            try:
                ok = self.ship_order(order_sn, logistics, **kwargs)
                if ok:
                    shipped.append(order_sn)
                else:
                    failed.append(order_sn)
            except Exception:
                failed.append(order_sn)
        return {"shipped": shipped, "failed": failed, "total": len(order_list)}

    def get_pending_shipments(self, **kwargs) -> list[dict]:
        return self.list_orders(status="pending", days=30, **kwargs)

    # ------------------------------------------------------------------
    # Marketing Actions
    # ------------------------------------------------------------------

    def create_flash_sale(self, items: list[dict], **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/marketing/flash_sale")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                create_btn = kwargs.get("create_btn_selector", "button:has-text('Criar'), button:has-text('Create'), [data-testid='create-flash-sale']")
                p.click(create_btn)
                p.wait_for_timeout(2000)

                for i, item in enumerate(items):
                    item_name = item.get("name", f"Item {i + 1}")
                    item_price = item.get("price", 0)
                    item_stock = item.get("stock", 0)
                    name_sel = kwargs.get("fs_name_selector", f"input[name='items[{i}].name'], .flash-sale-item:nth-child({i + 1}) input")
                    price_sel = kwargs.get("fs_price_selector", f"input[name='items[{i}].price']")
                    stock_sel = kwargs.get("fs_stock_selector", f"input[name='items[{i}].stock']")
                    try:
                        p.fill(name_sel, item_name)
                        p.fill(price_sel, str(item_price))
                        p.fill(stock_sel, str(item_stock))
                    except Exception:
                        pass

                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                toast = self._wait_for_toast(p)
                return {"success": True, "toast": toast, "items_count": len(items)}
            except Exception as e:
                return {"success": False, "error": str(e)}

    def create_voucher_campaign(self, data: dict, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/marketing/voucher")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                create_btn = kwargs.get("create_btn_selector", "button:has-text('Criar'), button:has-text('Create'), [data-testid='create-voucher']")
                p.click(create_btn)
                p.wait_for_timeout(2000)

                for key, val in data.items():
                    sel = kwargs.get(f"voucher_{key}_selector", f"input[name='{key}'], select[name='{key}'], [data-testid='voucher-{key}']")
                    try:
                        p.fill(sel, str(val))
                    except Exception:
                        try:
                            p.select_option(sel, str(val))
                        except Exception:
                            pass

                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                toast = self._wait_for_toast(p)
                return {"success": True, "toast": toast}
            except Exception as e:
                return {"success": False, "error": str(e)}

    def create_bundle_deal(self, data: dict, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/marketing/bundle_deal")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                create_btn = kwargs.get("create_btn_selector", "button:has-text('Criar'), button:has-text('Create'), [data-testid='create-bundle']")
                p.click(create_btn)
                p.wait_for_timeout(2000)

                for key, val in data.items():
                    sel = kwargs.get(f"bundle_{key}_selector", f"input[name='{key}'], select[name='{key}'], [data-testid='bundle-{key}']")
                    try:
                        p.fill(sel, str(val))
                    except Exception:
                        try:
                            p.select_option(sel, str(val))
                        except Exception:
                            pass

                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                toast = self._wait_for_toast(p)
                return {"success": True, "toast": toast}
            except Exception as e:
                return {"success": False, "error": str(e)}

    def activate_campaign(self, campaign_id: str, **kwargs) -> bool:
        return self._toggle_campaign(campaign_id, activate=True, **kwargs)

    def pause_campaign(self, campaign_id: str, **kwargs) -> bool:
        return self._toggle_campaign(campaign_id, activate=False, **kwargs)

    def _toggle_campaign(self, campaign_id: str, activate: bool, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/marketing/campaigns")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                campaign_sel = kwargs.get(
                    "campaign_selector",
                    f"[data-campaign-id='{campaign_id}'], "
                    f"tr:has(td:text('{campaign_id}')), "
                    f".campaign-item:nth-child({campaign_id})",
                )
                kwargs.get(
                    "toggle_selector",
                    ".eds-switch, button:has-text('Ativar'), button:has-text('Pausar'), "
                    "button:has-text('Activate'), button:has-text('Pause')",
                )
                try:
                    p.click(campaign_sel)
                except Exception:
                    pass
                try:
                    target_text = "Ativar" if activate else "Pausar"
                    btn = p.evaluate(
                        f"""() => {{
                            const btns = document.querySelectorAll('button');
                            for (const b of btns) {{
                                if (b.textContent.toLowerCase().includes({json.dumps(target_text.lower())})) {{
                                    b.click(); return true;
                                }}
                            }}
                            return false;
                        }}"""
                    )
                    if btn:
                        p.wait_for_timeout(1000)
                        try:
                            p.click(self.DEFAULT_SELECTORS["modal_confirm"])
                        except Exception:
                            pass
                        p.wait_for_timeout(1500)
                        return True
                except Exception:
                    pass
                return False
            except Exception:
                return False

    def list_campaigns(self, **kwargs) -> list[dict]:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/marketing/campaigns")
        row_sel = kwargs.get("row_selector", self.DEFAULT_SELECTORS["product_row"])
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                return self._extract_campaigns_from_state(data)

            return self._table_to_dicts(p, row_sel)

    def get_campaign_performance(self, campaign_id: str, **kwargs) -> dict:
        url = kwargs.get(
            "url",
            f"{self.BASE_URL}/portal/marketing/campaigns/{campaign_id}/performance",
        )
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                result = {"campaign_id": campaign_id, "extracted_from_state": True}
                if "performance" in data:
                    result["performance"] = data["performance"]
                elif "campaign" in data:
                    result["campaign"] = data["campaign"]
                else:
                    result["page_data"] = str(data)[:2000]
                return result

            body = p.inner_text("body")
            return {"campaign_id": campaign_id, "body_snippet": body[:3000]}

    # ------------------------------------------------------------------
    # Finance Actions
    # ------------------------------------------------------------------

    def get_account_balance(self, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/finance/wallet")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data and "balance" in data:
                return {"balance": data["balance"]}

            body = p.inner_text("body")
            balance = self._extract_balance_from_text(body)
            return {"balance": balance, "body_snippet": body[:2000]}

    def get_payout_history(self, days: int = 30, **kwargs) -> list[dict]:
        url = kwargs.get(
            "url",
            f"{self.BASE_URL}/portal/finance/payout?days={days}",
        )
        row_sel = kwargs.get("row_selector", self.DEFAULT_SELECTORS["product_row"])
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            return self._table_to_dicts(p, row_sel)

    def get_transaction_history(self, days: int = 30, **kwargs) -> list[dict]:
        url = kwargs.get(
            "url",
            f"{self.BASE_URL}/portal/finance/transactions?days={days}",
        )
        row_sel = kwargs.get("row_selector", self.DEFAULT_SELECTORS["product_row"])
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            return self._table_to_dicts(p, row_sel)

    # ------------------------------------------------------------------
    # Performance & Compliance
    # ------------------------------------------------------------------

    def get_shop_performance(self, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/performance")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                result = {"extracted_from_state": True}
                if "performance" in data:
                    result["performance"] = data["performance"]
                elif "score" in data:
                    result["score"] = data["score"]
                else:
                    result["page_data"] = str(data)[:2000]
                return result

            body = p.inner_text("body")
            return {"body_snippet": body[:3000]}

    def get_listing_violations(self, **kwargs) -> list[dict]:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/performance/violations")
        row_sel = kwargs.get("row_selector", self.DEFAULT_SELECTORS["product_row"])
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            return self._table_to_dicts(p, row_sel)

    def resolve_violation(self, violation_id: str, action: str, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/performance/violations")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                violation_sel = kwargs.get(
                    "violation_selector",
                    f"[data-violation-id='{violation_id}'], "
                    f"tr:has(td:text('{violation_id}'))",
                )
                try:
                    p.click(violation_sel)
                    p.wait_for_timeout(1000)
                except Exception:
                    pass

                action_sel = kwargs.get(
                    "action_selector",
                    f"button:has-text('{action}'), [data-action='{action}']",
                )
                p.click(action_sel)
                p.wait_for_timeout(1000)

                try:
                    p.click(self.DEFAULT_SELECTORS["modal_confirm"])
                except Exception:
                    pass
                p.wait_for_timeout(1500)
                return True
            except Exception:
                return False

    # ------------------------------------------------------------------
    # Settings Actions
    # ------------------------------------------------------------------

    def get_shipping_settings(self, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/settings/shipping")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)

            data = self._extract_page_data(p)
            if data:
                result = {"extracted_from_state": True}
                if "shipping" in data:
                    result["shipping"] = data["shipping"]
                else:
                    result["page_data"] = str(data)[:2000]
                return result

            body = p.inner_text("body")
            return {"body_snippet": body[:3000]}

    def update_shipping_settings(self, settings: dict, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/settings/shipping")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                for key, val in settings.items():
                    sel = kwargs.get(
                        f"setting_{key}_selector",
                        f"input[name='{key}'], select[name='{key}'], "
                        f"[data-testid='{key}']",
                    )
                    try:
                        if isinstance(val, bool):
                            try:
                                is_active = p.evaluate(
                                    f"document.querySelector({json.dumps(sel)})?.checked ?? false"
                                )
                                if is_active != val:
                                    p.click(sel)
                            except Exception:
                                pass
                        else:
                            try:
                                p.fill(sel, str(val))
                            except Exception:
                                try:
                                    p.select_option(sel, str(val))
                                except Exception:
                                    pass
                    except Exception:
                        pass

                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def get_shop_categories(self, **kwargs) -> list[dict]:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/settings/category")
        row_sel = kwargs.get("row_selector", self.DEFAULT_SELECTORS["product_row"])
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            return self._table_to_dicts(p, row_sel)

    def create_shop_category(self, name: str, parent_id: int = 0, **kwargs) -> dict:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/settings/category")
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                create_btn = kwargs.get(
                    "create_btn_selector",
                    "button:has-text('Criar'), button:has-text('Nova'), "
                    "[data-testid='create-category']",
                )
                p.click(create_btn)
                p.wait_for_timeout(1000)

                name_sel = kwargs.get(
                    "category_name_selector",
                    "input[name='name'], input[placeholder*='nome' i], "
                    "[data-testid='category-name']",
                )
                p.fill(name_sel, name)

                if parent_id:
                    parent_sel = kwargs.get(
                        "parent_selector",
                        "select[name='parent_id'], select[name='parent']",
                    )
                    try:
                        p.select_option(parent_sel, str(parent_id))
                    except Exception:
                        pass

                self._click_save(p, kwargs.get("save_button"))
                p.wait_for_timeout(2000)
                toast = self._wait_for_toast(p)
                return {"success": True, "name": name, "toast": toast}
            except Exception as e:
                return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Batch / Utility Actions
    # ------------------------------------------------------------------

    def bulk_update_prices(self, items: list[dict], **kwargs) -> dict:
        updated = []
        failed = []
        for item in items:
            item_id = item.get("item_id", "")
            price = item.get("price", 0)
            try:
                ok = self._update_single_price(item_id, price, **kwargs)
                if ok:
                    updated.append(item_id)
                else:
                    failed.append(item_id)
            except Exception:
                failed.append(item_id)
        return {"updated": updated, "failed": failed, "total": len(items)}

    def _update_single_price(self, item_id: str, price: float, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        selectors = {**self.DEFAULT_SELECTORS, **kwargs}
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                p.fill(selectors["price_input"], str(price))
                self._click_save(p, selectors.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def bulk_update_stock(self, items: list[dict], **kwargs) -> dict:
        updated = []
        failed = []
        for item in items:
            item_id = item.get("item_id", "")
            stock = item.get("stock", 0)
            try:
                ok = self._update_single_stock(item_id, stock, **kwargs)
                if ok:
                    updated.append(item_id)
                else:
                    failed.append(item_id)
            except Exception:
                failed.append(item_id)
        return {"updated": updated, "failed": failed, "total": len(items)}

    def _update_single_stock(self, item_id: str, stock: int, **kwargs) -> bool:
        url = kwargs.get("url", f"{self.BASE_URL}/portal/product/{item_id}")
        selectors = {**self.DEFAULT_SELECTORS, **kwargs}
        with self._browser() as p:
            p.goto(url)
            p.wait_for_timeout(3000)
            try:
                p.fill(selectors["stock_input"], str(stock))
                self._click_save(p, selectors.get("save_button"))
                p.wait_for_timeout(2000)
                return True
            except Exception:
                return False

    def export_products_to_csv(self, filepath: str, **kwargs) -> str:
        products = self.list_products(page=1, page_size=10000, **kwargs)
        if not products:
            return ""

        fieldnames = set()
        for prod in products:
            fieldnames.update(prod.keys())
        fieldnames = sorted(fieldnames)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for prod in products:
                writer.writerow(prod)

        return filepath

    def import_products_from_csv(self, filepath: str, **kwargs) -> dict:
        imported = []
        failed = []
        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    data = dict(row)
                    item_id = data.pop("item_id", data.pop("id", ""))
                    if item_id:
                        result = self.update_product(item_id, data, **kwargs)
                        if result:
                            imported.append(item_id)
                        else:
                            failed.append({"item_id": item_id, "error": "update failed"})
                    else:
                        result = self.create_product(data, **kwargs)
                        if result.get("success"):
                            imported.append(result.get("item_id", "unknown"))
                        else:
                            failed.append({"data": data, "error": result.get("error")})
                except Exception as e:
                    failed.append({"row": row, "error": str(e)})
        return {"imported": imported, "failed": failed, "total": len(imported) + len(failed)}

    # ------------------------------------------------------------------
    # Internal data extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_products_from_state(data: dict) -> list[dict]:
        for key in ("products", "items", "productList", "itemList", "data"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for sub in ("items", "list", "products", "data"):
                    if sub in val and isinstance(val[sub], list):
                        return val[sub]
        return []

    @staticmethod
    def _extract_orders_from_state(data: dict) -> list[dict]:
        for key in ("orders", "orderList", "data", "list"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for sub in ("orders", "list", "items", "data"):
                    if sub in val and isinstance(val[sub], list):
                        return val[sub]
        return []

    @staticmethod
    def _extract_campaigns_from_state(data: dict) -> list[dict]:
        for key in ("campaigns", "campaignList", "data", "list"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for sub in ("campaigns", "list", "items", "data"):
                    if sub in val and isinstance(val[sub], list):
                        return val[sub]
        return []

    @staticmethod
    def _extract_balance_from_text(text: str) -> str:
        import re
        patterns = [
            r"(?:R\$\s*|BRL\s*)?([\d,]+\.\d{2})",
            r"(?:saldo|balance)[:\s]*R?\$?\s*([\d.,]+)",
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return ""


# ---------------------------------------------------------------------------
# SellerCenterFullSkill — GOAP skill
# ---------------------------------------------------------------------------


class SellerCenterFullSkill(Skill):
    """GOAP skill that wraps ``SellerCenterAutomator`` for full Seller Center
    automation.  Dispatches to the correct automator method based on
    ``params["action"]``."""

    name = "seller_center_full"
    cost = 8.0
    risk_level = "HIGH"
    preconditions = {
        "browser_available": True,
        "seller_center_logged_in": True,
    }
    effects = {"seller_center_action_completed": True}

    # Map action names -> (method, returns_iterable)
    ACTION_MAP = {
        # Product
        "list_products": ("list_products", True),
        "get_product_detail": ("get_product_detail", False),
        "create_product": ("create_product", False),
        "update_product": ("update_product", False),
        "delete_product": ("delete_product", False),
        "update_variations": ("update_variations", False),
        "update_images": ("update_images", False),
        "update_shipping": ("update_shipping", False),
        "update_description": ("update_description", False),
        # Order
        "list_orders": ("list_orders", True),
        "get_order_detail": ("get_order_detail", False),
        "ship_order": ("ship_order", False),
        "cancel_order": ("cancel_order", False),
        "bulk_ship_orders": ("bulk_ship_orders", False),
        "get_pending_shipments": ("get_pending_shipments", True),
        # Marketing
        "create_flash_sale": ("create_flash_sale", False),
        "create_voucher_campaign": ("create_voucher_campaign", False),
        "create_bundle_deal": ("create_bundle_deal", False),
        "activate_campaign": ("activate_campaign", False),
        "pause_campaign": ("pause_campaign", False),
        "list_campaigns": ("list_campaigns", True),
        "get_campaign_performance": ("get_campaign_performance", False),
        # Finance
        "get_account_balance": ("get_account_balance", False),
        "get_payout_history": ("get_payout_history", True),
        "get_transaction_history": ("get_transaction_history", True),
        # Performance
        "get_shop_performance": ("get_shop_performance", False),
        "get_listing_violations": ("get_listing_violations", True),
        "resolve_violation": ("resolve_violation", False),
        # Settings
        "get_shipping_settings": ("get_shipping_settings", False),
        "update_shipping_settings": ("update_shipping_settings", False),
        "get_shop_categories": ("get_shop_categories", True),
        "create_shop_category": ("create_shop_category", False),
        # Batch
        "bulk_update_prices": ("bulk_update_prices", False),
        "bulk_update_stock": ("bulk_update_stock", False),
        "export_products_to_csv": ("export_products_to_csv", False),
        "import_products_from_csv": ("import_products_from_csv", False),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._automator: SellerCenterAutomator | None = None

    def _get_automator(self, params: dict) -> SellerCenterAutomator:
        if self._automator is None:
            self._automator = SellerCenterAutomator(
                client=params.get("client"),
                access_token=params.get("access_token"),
                shop_id=params.get("shop_id"),
                headless=params.get("headless", True),
            )
        return self._automator

    def validate_params(self, params: dict) -> bool:
        if not isinstance(params, dict):
            return False
        action = params.get("action", "")
        if action not in self.ACTION_MAP:
            return False
        return True

    def run(self, params: dict | None = None, **kwargs) -> dict:
        p = params or kwargs
        if not self.validate_params(p):
            return {
                "ok": False,
                "result": None,
                "error": f"Invalid parameters or unknown action '{p.get('action', '')}'",
            }

        action = p["action"]
        method_name, is_iterable = self.ACTION_MAP[action]

        try:
            automator = self._get_automator(p)
            method = getattr(automator, method_name)

            # Build the call arguments — pass all params except known skill-level keys
            call_args = {
                k: v
                for k, v in p.items()
                if k
                not in (
                    "action",
                    "client",
                    "access_token",
                    "shop_id",
                    "headless",
                )
            }

            result = method(**call_args)
            return {
                "ok": True,
                "result": result,
                "action": action,
            }
        except Exception as exc:
            return {
                "ok": False,
                "result": None,
                "action": action,
                "error": f"{type(exc).__name__}: {exc}",
            }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

default_registry.register(SellerCenterFullSkill)
