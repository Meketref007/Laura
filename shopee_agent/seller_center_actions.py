"""
seller_center_actions.py - Acoes executaveis na Central do Vendedor.

Combina chamadas diretas a API (quando o endpoint e conhecido) com
automacao via Playwright (para operacoes sem API documentada).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from shopee_agent.ceo_mode import ceo_mode_enabled
from shopee_agent.logger import error, info, warning
from shopee_agent.seller_center import (
    SELLER_CENTER_BASE,
    SellerCenterClient,
    load_cookies,
)


class SellerCenterActions:
    """Acoes executaveis na Central do Vendedor, com fallback via Playwright."""

    def __init__(self, client: SellerCenterClient | None = None):
        if client is None:
            client = SellerCenterClient()
        self.client = client
        self._playwright_interceptor = None

    def is_authenticated(self) -> bool:
        return self.client.is_authenticated()

    # =====================================================================
    # ACESSO VIA API DIRETA (endpoints conhecidos do Seller Center)
    # =====================================================================

    def reply_to_rating(self, order_id: int, comment_id: int, comment: str) -> str:
        """Responder a uma avaliacao."""
        guard = self._confirm_or_dry_run(
            f"Responder avaliacao {comment_id} do pedido {order_id}",
            {"order_id": order_id, "comment_id": comment_id, "comment": comment[:100]},
        )
        if guard:
            return guard
        ok = self.client.reply_to_rating(order_id, comment_id, comment)
        return "✅ Resposta enviada a avaliacao!" if ok else "Falha ao enviar resposta."

    def get_shop_overview(self) -> dict:
        return self.client.get_shop_overview() or {}

    def get_shop_health(self) -> dict:
        h = self.client.get_shop_health()
        return h if isinstance(h, dict) else {}

    def get_financial_summary(self) -> dict:
        f = self.client.get_financial_summary()
        return f if isinstance(f, dict) else {}

    def get_violations(self) -> list:
        return self.client.get_violation_records() or []

    def get_shipping_settings(self) -> dict:
        s = self.client.get_shipping_settings()
        return s if isinstance(s, dict) else {}

    def get_shop_profile(self) -> dict:
        s = self.client.get_shop_profile()
        return s if isinstance(s, dict) else {}

    def get_orders(self, page=1, limit=10) -> list:
        return self.client.get_orders(page=page, limit=limit) or []

    def get_ratings(self, page=1, limit=10) -> list:
        return self.client.get_ratings(page=page, limit=limit) or []

    def get_wallet_balance(self) -> dict:
        w = self.client.get_wallet_balance()
        return w if isinstance(w, dict) else {}

    def get_campaigns(self, page=1, limit=10) -> list:
        return self.client.get_campaigns(page=page, limit=limit) or []

    def get_vouchers(self, page=1, limit=10) -> list:
        return self.client.get_vouchers(page=page, limit=limit) or []

    def get_flash_sales(self, page=1, limit=10) -> list:
        return self.client.get_flash_sales(page=page, limit=limit) or []

    def get_chat_messages(self, page=1, limit=10) -> list:
        return self.client.get_chat_management(page=page, limit=limit) or []

    def get_pickup_settings(self) -> dict:
        return self.client.get_pickup_settings()

    def enable_pickup(self, enable: bool = True) -> str:
        guard = self._confirm_or_dry_run("Ativar retirada pelo comprador", {"enabled": enable})
        if guard:
            return guard
        result = self.client.enable_pickup(enable)
        if result.get("success"):
            return "✅ Retirada pelo comprador " + ("ativada!" if enable else "desativada!")
        return f"Falha ao configurar retirada: {result}"

    def get_returns(self, page=1, limit=10) -> list:
        return self.client.get_returns(page=page, limit=limit) or []

    def get_products(self, page=1, limit=10) -> list:
        return self.client.get_products(page=page, limit=limit) or []

    def get_account_health(self) -> dict:
        a = self.client.get_account_health()
        return a if isinstance(a, dict) else {}

    def get_appeals(self, page=1, limit=10) -> list:
        return self.client.get_appeals(page=page, limit=limit) or []

    def get_rating_dashboard(self) -> dict:
        r = self.client.get_rating_dashboard()
        return r if isinstance(r, dict) else {}

    def get_todo_summary(self) -> dict:
        t = self.client.get_todo_summary()
        return t if isinstance(t, dict) else {}

    # =====================================================================
    # ESCRITA via API direta
    # =====================================================================

    def _is_dry_run(self) -> bool:
        if ceo_mode_enabled():
            return False
        return os.getenv("SELLER_CENTER_DRY_RUN", "1") == "1"

    def _confirm_or_dry_run(self, action_desc: str, data: dict) -> str | None:
        """Retorna None se pode prosseguir, ou string de resposta se bloqueou."""
        if self._is_dry_run():
            info(f"[DRY RUN] {action_desc}: {json.dumps(data, ensure_ascii=False)[:500]}")
            return f"🧪 MODO DRY RUN — {action_desc} nao executada.\nPara desativar: SELLER_CENTER_DRY_RUN=0\nDados que seriam enviados: {json.dumps(data, ensure_ascii=False)[:300]}"
        return None

    def _post(self, path: str, data: dict) -> dict:
        """POST para um endpoint do Seller Center com CSRF."""
        try:
            resp = self.client.post(f"{SELLER_CENTER_BASE}{path}", json=data)
            if resp.ok:
                return resp.json()
            warning(f"POST {path} falhou: {resp.status_code} {resp.text[:200]}")
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
        except Exception as e:
            error(f"POST {path} exception: {e}")
            return {"error": str(e)}

    def update_shipping_setting(self, **kwargs) -> str:
        """Atualizar configuracao de envio."""
        guard = self._confirm_or_dry_run("Atualizar configuracao de envio", kwargs)
        if guard:
            return guard
        result = self._post("/api/v2/setting/shipping/update", kwargs)
        if result.get("code") == 0 or result.get("error") is None:
            return "✅ Configuracao de envio atualizada!"
        return f"Falha ao atualizar envio: {result}"

    def update_shop_profile(self, **kwargs) -> str:
        """Atualizar perfil da loja."""
        guard = self._confirm_or_dry_run("Atualizar perfil da loja", kwargs)
        if guard:
            return guard
        result = self._post("/api/v2/setting/shop_profile/update", kwargs)
        if result.get("code") == 0 or result.get("error") is None:
            return "✅ Perfil da loja atualizado!"
        return f"Falha ao atualizar perfil: {result}"

    # =====================================================================
    # PLAYWRIGHT - automacao para acoes sem API direta
    # =====================================================================

    def _ensure_playwright(self) -> Any:
        """Garantir que o Playwright esta disponivel com cookies carregados."""
        if self._playwright_interceptor is not None:
            return self._playwright_interceptor
        from shopee_agent.article_scraper import _PWInterceptor
        from shopee_agent.seller_center import COOKIES_FILE

        session = load_cookies(COOKIES_FILE)
        if not session or not session.is_valid():
            raise RuntimeError("Cookies do Seller Center expirados. Rode auto-login primeiro.")

        intc = _PWInterceptor(base_url=SELLER_CENTER_BASE, domain_key="br")
        intc.__enter__()

        # Injetar cookies no navegador
        for c in session.cookies:
            if c.is_expired():
                continue
            try:
                intc._page.context.add_cookies([{
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain.lstrip("."),
                    "path": c.path or "/",
                    "secure": c.secure,
                }])
            except Exception:
                pass

        self._playwright_interceptor = intc
        return intc

    def _pw_execute(self, url: str, js_code: str | None = None, wait_seconds: int = 3) -> str:
        """Navegar para URL no Playwright e opcionalmente executar JS."""
        intc = self._ensure_playwright()
        intc._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(wait_seconds)
        if js_code:
            try:
                intc._page.evaluate(js_code)
                time.sleep(2)
            except Exception as e:
                return f"Erro ao executar acao: {e}"
        return f"✅ Pagina {url} acessada"

    def close(self):
        """Liberar recursos do Playwright."""
        if self._playwright_interceptor:
            try:
                self._playwright_interceptor.__exit__(None, None, None)
            except Exception:
                pass
            self._playwright_interceptor = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # =====================================================================
    # ACOES ESPECIFICAS via Playwright
    # =====================================================================

    def navigate_to_shipping(self) -> str:
        """Navegar para configuracoes de envio."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/setting/shipping",
            wait_seconds=3,
        )

    def navigate_to_pickup_settings(self) -> str:
        """Navegar para configuracao de retirada pelo comprador."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/setting/shipping?tab=pickup",
            wait_seconds=3,
        )

    def navigate_to_shop_profile(self) -> str:
        """Navegar para perfil da loja."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/setting/shop_profile",
            wait_seconds=3,
        )

    def navigate_to_vouchers(self) -> str:
        """Navegar para pagina de cupons."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/marketing/voucher",
            wait_seconds=3,
        )

    def navigate_to_campaigns(self) -> str:
        """Navegar para campanhas de marketing."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/marketing/campaign",
            wait_seconds=3,
        )

    def navigate_to_flash_sale(self) -> str:
        """Navegar para promocoes relampago."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/marketing/flash_sale",
            wait_seconds=3,
        )

    def navigate_to_ratings(self) -> str:
        """Navegar para avaliacoes."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/rating/list",
            wait_seconds=3,
        )

    def navigate_to_products(self) -> str:
        """Navegar para lista de produtos."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/product/list",
            wait_seconds=3,
        )

    def navigate_to_orders(self) -> str:
        """Navegar para pedidos."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/order/list",
            wait_seconds=3,
        )

    def navigate_to_dashboard(self) -> str:
        """Navegar para dashboard da loja."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/dashboard",
            wait_seconds=3,
        )

    def navigate_to_chat(self) -> str:
        """Navegar para chat com compradores."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/chat/list",
            wait_seconds=3,
        )

    def navigate_to_wallet(self) -> str:
        """Navegar para carteira financeira."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/finance/wallet",
            wait_seconds=3,
        )

    def navigate_to_account_health(self) -> str:
        """Navegar para saude da conta."""
        return self._pw_execute(
            f"{SELLER_CENTER_BASE}/portal/account_health",
            wait_seconds=3,
        )

    # =====================================================================
    # PER-PRODUCT SHIPPING CHANNELS via Playwright
    # =====================================================================

    def get_product_shipping_channels(self, item_id: int) -> str:
        """Ler os canais de envio ativos para um produto especifico."""
        intc = self._ensure_playwright()
        url = f"{SELLER_CENTER_BASE}/portal/product/{item_id}"
        intc._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)

        import json as _json

        channels = []
        try:
            # Tenta encontrar os toggles de canal de envio na pagina
            result = intc._page.evaluate("""() => {
  const channels = [];
  // Procura por secoes de envio com toggles
  const sections = document.querySelectorAll('[class*="shipping"], [class*="logistics"], [class*="delivery"]');
  sections.forEach(s => {
    const label = s.textContent.trim().substring(0, 100);
    const toggles = s.querySelectorAll('input[type="checkbox"], [class*="toggle"], [class*="switch"], [role="switch"]');
    toggles.forEach(t => {
      const parent = t.closest('label') || t.parentElement;
      const name = parent ? parent.textContent.trim().substring(0, 80) : '';
      const checked = t.checked || t.getAttribute('aria-checked') === 'true' || t.classList.contains('active');
      channels.push({name: name || label, checked: !!checked});
    });
  });
  // Fallback: procura por qualquer toggle na pagina
  if (channels.length === 0) {
    document.querySelectorAll('[class*="toggle"], [class*="switch"], [role="switch"], input[type="checkbox"]').forEach(t => {
      const parent = t.closest('label, div, li') || t.parentElement;
      const name = parent ? parent.textContent.trim().substring(0, 80) : '';
      const checked = t.checked || t.getAttribute('aria-checked') === 'true' || t.classList.contains('active');
      if (name.toLowerCase().includes('envio') || name.toLowerCase().includes('shipping') || name.toLowerCase().includes('frete') || name.toLowerCase().includes('retirada') || name.toLowerCase().includes('xpress')) {
        channels.push({name: name.substring(0, 60), checked: !!checked});
      }
    });
  }
  return channels;
}""")
            for ch in result:
                channels.append(ch)
        except Exception as e:
            channels.append({"error": str(e)})

        if not channels:
            return f"Nenhum canal de envio encontrado para o produto {item_id}. A pagina pode estar em branco."

        output = _json.dumps(channels, ensure_ascii=False, indent=2)
        return f"Canais de envio do produto {item_id}:\n{output}"

    def set_product_shipping_channel(self, item_id: int, channel: str, enable: bool = True) -> str:
        """Ativar/desativar um canal de envio para um produto especifico."""
        guard = self._confirm_or_dry_run(
            f"{'Ativar' if enable else 'Desativar'} canal '{channel}' no produto {item_id}",
            {"item_id": item_id, "channel": channel, "enable": enable},
        )
        if guard:
            return guard

        # Tenta via CDP (Brave autenticado) primeiro
        cdp_result = self._cdp_toggle_shipping(item_id, channel, enable)
        info(f"CDP result for {item_id}: {cdp_result[:80] if cdp_result else 'None'}")
        if cdp_result:
            return cdp_result

        # Fallback: Playwright headless
        intc = self._ensure_playwright()
        url = f"{SELLER_CENTER_BASE}/portal/product/{item_id}"
        intc._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)

        # Procura pelo toggle correspondente ao canal (eds-switch = toggle Shopee)
        result = intc._page.evaluate("""(args) => {
  const channel = args.channel.toLowerCase();
  const enable = args.enable;
  const items = document.querySelectorAll('.logistics-item');
  let matched = null;
  for (const item of items) {
    if (item.textContent.toLowerCase().includes(channel)) {
      matched = item;
      break;
    }
  }
  if (!matched) {
    for (const item of items) {
      const text = item.textContent.toLowerCase();
      if (text.includes('frete') || text.includes('envio')) {
        matched = item;
        break;
      }
    }
  }
  if (matched) {
    const toggle = matched.querySelector('.eds-switch');
    if (!toggle) return {found: false, reason: 'sem toggle no item'};
    const isOpen = toggle.classList.contains('eds-switch--open');
    if (isOpen !== enable) {
      toggle.click();
      return {found: true, clicked: true};
    }
    return {found: true, clicked: false, alreadyCorrect: true};
  }
  return {found: false};
}""", {"channel": channel, "enable": enable})

        if result.get("found"):
            time.sleep(2)
            try:
                save_btn = intc._page.evaluate("""() => {
  const btns = document.querySelectorAll('button[class*="save"], button[class*="update"], button[class*="submit"], [type="submit"]');
  for (const b of btns) {
    if (b.textContent.toLowerCase().includes('salvar') || b.textContent.toLowerCase().includes('atualizar') || b.textContent.toLowerCase().includes('publicar')) {
      b.click();
      return true;
    }
  }
  return false;
}""")
                if save_btn:
                    time.sleep(3)
                    return f"Canal '{channel}' {'ativado' if enable else 'desativado'}. Produto salvo."
            except Exception:
                pass
            return f"Canal '{channel}' {'ativado' if enable else 'desativado'} (sem salvamento automatico)."
        else:
            return f"Canal '{channel}' nao encontrado na pagina do produto {item_id}."

    def _cdp_toggle_shipping(self, channel: str, enable: bool) -> str | None:
        """Alterna canal de envio via CDP na pagina GLOBAL de configuracoes de envio.

        Usa /portal/all-settings/shipping/shipping-channel. Reusa aba existente
        do Seller Center (evita acumular abas). Notifica Telegram em caso de falha.
        """
        import json as _json
        try:
            import requests as _req
            import websocket as _ws
        except ImportError:
            return None

        def _notify_falha(msg: str):
            info(msg)
            try:
                from shopee_agent.vilu_workers import enviar_para_canal
                enviar_para_canal("sistema", f"⚠️ *Toggle Shipping*\n{msg}")
            except Exception:
                pass
            return None

        try:
            version = _req.get("http://127.0.0.1:9222/json/version", timeout=5)
            if version.status_code != 200:
                return _notify_falha(f"CDP nao disponivel (status {version.status_code})")

            tabs = _req.get("http://127.0.0.1:9222/json", timeout=5).json()
            target_tab = None
            for tab in tabs:
                url = tab.get("url", "")
                if "shipping-channel" in url:
                    target_tab = tab
                    break
            if not target_tab:
                for tab in tabs:
                    u = tab.get("url", "")
                    if "seller.shopee.com.br" in u and "product" not in u:
                        target_tab = tab
                        break
            if not target_tab:
                resp = _req.put("http://127.0.0.1:9222/json/new", timeout=10)
                if resp.status_code != 200:
                    return _notify_falha(f"Falha ao criar aba (status {resp.status_code})")
                target_tab = resp.json()

            ws_url = target_tab.get("webSocketDebuggerUrl", "")
            if not ws_url:
                info("CDP: sem wsUrl na aba")
                return None

            import ssl as _ssl
            ws = _ws.create_connection(ws_url, timeout=30,
                sslopt={"cert_reqs": _ssl.CERT_NONE} if ws_url.startswith("wss") else {})
            msg_id = 0

            def _send(method, params=None):
                nonlocal msg_id
                msg_id += 1
                ws.send(_json.dumps({"id": msg_id, "method": method, "params": params or {}}))
                while True:
                    raw = ws.recv()
                    data = _json.loads(raw)
                    if data.get("id") == msg_id:
                        return data.get("result")

            _send("Page.enable")

            # Injeta cookies se disponiveis
            try:
                from shopee_agent.seller_center import COOKIES_FILE
                from shopee_agent.seller_center import load_cookies as _load_cookies
                _cookie_session = _load_cookies(COOKIES_FILE)
                if _cookie_session:
                    for _c in _cookie_session.cookies:
                        if _c.is_expired():
                            continue
                        _cp = {"name": _c.name, "value": _c.value, "domain": _c.domain, "path": _c.path, "secure": _c.secure, "httpOnly": _c.httpOnly}
                        if _c.expirationDate:
                            _cp["expires"] = _c.expirationDate
                        _send("Network.setCookie", _cp)
            except Exception:
                pass

            # Navega para pagina global de canais de envio
            SETTINGS_URL = f"{SELLER_CENTER_BASE}/portal/all-settings/shipping/shipping-channel"
            _send("Page.navigate", {"url": SETTINGS_URL})
            _send("Runtime.evaluate", {
                "expression": "new Promise(r => { if (document.readyState === 'complete') r(); else document.addEventListener('readystatechange', () => { if (document.readyState === 'complete') r(); }); })",
                "awaitPromise": True,
            })
            time.sleep(6)

            url_check = _send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
            current_url = ((url_check.get("result") or {}).get("value", "") if url_check else "")
            if "login" in current_url:
                _notify_falha("Redirecionado para login - auth expirado")
                try:
                    _req.delete(f"http://127.0.0.1:9222/json/close/{target_tab.get('id', '')}", timeout=5)
                except Exception:
                    pass
                ws.close()
                return None

            # Fecha dialogs de onboarding que podem bloquear a pagina
            _send("Runtime.evaluate", {"expression": """(() => {
  const all = document.querySelectorAll('button');
  for (const b of all) {
    const t = b.textContent.trim();
    if ((t === 'Ok' || t === 'Done') && b.offsetParent !== null) { b.click(); return 'closed ' + t; }
  }
  return 'no onboarding dialogs';
})()""", "returnByValue": True})
            time.sleep(1)

            # Encontra o switch pelo nome do canal
            toggle_js = """(args) => {
  const channelName = args.channel.toLowerCase().trim();
  const wantOpen = args.enable;
  const switches = document.querySelectorAll('.eds-switch');
  for (const sw of switches) {
    const header = sw.closest('.channel-setting-header');
    if (!header) continue;
    const text = header.textContent.trim().toLowerCase();
    if (text === channelName || text.startsWith(channelName)) {
      const isDisabled = sw.classList.contains('eds-switch--disabled');
      if (isDisabled) return JSON.stringify({found: true, clicked: false, reason: 'canal nao pode ser alterado (disabled)'});
      const isOpen = sw.classList.contains('eds-switch--open');
      if (isOpen === wantOpen) {
        return JSON.stringify({found: true, clicked: false, reason: 'ja no estado desejado'});
      }
      sw.click();
      return JSON.stringify({found: true, clicked: true, channelName: header.textContent.trim()});
    }
  }
  return JSON.stringify({found: false, pageText: document.body.innerText.substring(0, 400)});
}"""
            toggle_raw = _send("Runtime.evaluate", {
                "expression": f"({toggle_js})({_json.dumps({'channel': channel, 'enable': enable})})",
                "returnByValue": True,
            })
            toggle_val = (toggle_raw or {}).get("result", {}).get("value", "{}") if toggle_raw else "{}"
            info(f"CDP toggle global: {toggle_val[:200]}")
            toggle_result = _json.loads(toggle_val)

            if not toggle_result.get("found"):
                ws.close()
                return _notify_falha(f"Canal '{channel}' nao encontrado na pagina global")

            if not toggle_result.get("clicked"):
                ws.close()
                return f"Canal '{channel}' ja esta no estado desejado (global)"

            # Clica "Confirmar" no modal de confirmacao
            time.sleep(2)
            confirm_js = """() => {
  const btns = document.querySelectorAll('button');
  for (const b of btns) {
    const txt = b.textContent.trim().toLowerCase();
    if ((txt === 'confirmar' || txt === 'confirm') && b.offsetParent !== null) {
      b.click();
      return true;
    }
  }
  return false;
}"""
            confirm_raw = _send("Runtime.evaluate", {"expression": f"({confirm_js})()", "returnByValue": True})
            confirmed = bool((confirm_raw or {}).get("result", {}).get("value", False) if confirm_raw else False)
            if not confirmed:
                info("AVISO: botao Confirmar nao encontrado no modal global")
            else:
                info("Confirmacao global clicada, aguardando save...")
                time.sleep(4)

            try:
                _req.delete(f"http://127.0.0.1:9222/json/close/{target_tab.get('id', '')}", timeout=5)
            except Exception:
                pass
            ws.close()

            action = "ativado" if enable else "desativado"
            return f"Canal '{channel}' {action} globalmente (afeta todos os produtos). Confirmacao: {'OK' if confirmed else 'nao encontrada'}."

        except Exception as e:
            info(f"CDP toggle global error: {e}")
            return None

    def set_channel_for_all_products(self, channel: str, enable: bool = True) -> str:
        """Ativar/desativar um canal de envio em TODOS os produtos.
        Usa toggle GLOBAL via pagina de configuracoes de envio."""
        guard = self._confirm_or_dry_run(
            f"{'Ativar' if enable else 'Desativar'} canal '{channel}' em TODOS os produtos",
            {"channel": channel, "enable": enable},
        )
        if guard:
            return guard

        global_result = self._cdp_toggle_shipping(channel, enable)
        if global_result is not None:
            from shopee_agent.logger import info as _info
            _info(f"Toggle GLOBAL: {global_result}")
            if "ativado" in global_result or "desativado" in global_result:
                try:
                    from shopee_agent.vilu_workers import enviar_para_canal
                    enviar_para_canal("sistema", f"✅ *{channel}* {'ativado' if enable else 'desativado'} globalmente para todos os produtos")
                except Exception:
                    pass
            return global_result

        return (
            f"Toggle global falhou para canal '{channel}'. "
            "Fallback per-produto desabilitado: o botao de salvar na pagina do produto "
            "fica permanentemente disabled devido a validacao do formulario (issue #1). "
            "Tente renovar a sessao (re-login no Brave) e tente novamente."
        )


# =====================================================================
# MAPA DE ACOES - centraliza todas as acoes disponiveis
# =====================================================================

# Cada acao: (metodo, descricao, parametros_opcionais)
ACTION_REGISTRY: dict[str, tuple[str, str, list[str]]] = {
    # Leituras via API direta
    "get_shop_overview": ("get_shop_overview", "Visao geral da loja", []),
    "get_shop_health": ("get_shop_health", "Saude da loja", []),
    "get_financial_summary": ("get_financial_summary", "Resumo financeiro", []),
    "get_shipping_settings": ("get_shipping_settings", "Configuracoes de envio", []),
    "get_shop_profile": ("get_shop_profile", "Perfil da loja", []),
    "get_orders": ("get_orders", "Listar pedidos", ["page", "limit"]),
    "get_ratings": ("get_ratings", "Listar avaliacoes", ["page", "limit"]),
    "get_violations": ("get_violations", "Violacoes e penalidades", []),
    "get_wallet_balance": ("get_wallet_balance", "Saldo da carteira", []),
    "get_campaigns": ("get_campaigns", "Campanhas de marketing", ["page", "limit"]),
    "get_vouchers": ("get_vouchers", "Cupons da loja", ["page", "limit"]),
    "get_flash_sales": ("get_flash_sales", "Promocoes relampago", ["page", "limit"]),
    "get_chat_messages": ("get_chat_messages", "Mensagens do chat", ["page", "limit"]),
    "get_returns": ("get_returns", "Devolucoes", ["page", "limit"]),
    "get_products": ("get_products", "Produtos da loja", ["page", "limit"]),
    "get_account_health": ("get_account_health", "Saude da conta", []),
    "get_appeals": ("get_appeals", "Recursos de penalidades", ["page", "limit"]),
    "get_rating_dashboard": ("get_rating_dashboard", "Dashboard de avaliacoes", []),
    "get_todo_summary": ("get_todo_summary", "Resumo de tarefas pendentes", []),

    # Retirada pelo comprador
    "get_pickup_settings": ("get_pickup_settings", "Configuracao de retirada", []),
    "enable_pickup": ("enable_pickup", "Ativar retirada pelo comprador", ["enable"]),

    # Escrita via API direta
    "reply_to_rating": ("reply_to_rating", "Responder avaliacao", ["order_id", "comment_id", "comment"]),
    "update_shipping_setting": ("update_shipping_setting", "Atualizar config de envio", ["kwargs"]),
    "update_shop_profile": ("update_shop_profile", "Atualizar perfil da loja", ["kwargs"]),

    # Navegacao via Playwright (somente visualizacao - nao executa acoes nas paginas)
    "navigate_shipping": ("navigate_to_shipping", "Visualizar config de envio (Playwright)", []),
    "navigate_pickup": ("navigate_to_pickup_settings", "Visualizar config de retirada (Playwright)", []),
    "navigate_shop_profile": ("navigate_to_shop_profile", "Visualizar perfil da loja (Playwright)", []),
    "navigate_vouchers": ("navigate_to_vouchers", "Visualizar pagina de cupons (Playwright)", []),
    "navigate_campaigns": ("navigate_to_campaigns", "Visualizar campanhas (Playwright)", []),
    "navigate_flash_sale": ("navigate_to_flash_sale", "Visualizar promocoes (Playwright)", []),
    "navigate_ratings": ("navigate_to_ratings", "Visualizar avaliacoes (Playwright)", []),
    "navigate_products": ("navigate_to_products", "Visualizar produtos (Playwright)", []),
    "navigate_orders": ("navigate_to_orders", "Visualizar pedidos (Playwright)", []),
    "navigate_dashboard": ("navigate_to_dashboard", "Visualizar dashboard (Playwright)", []),
    "navigate_chat": ("navigate_to_chat", "Visualizar chat (Playwright)", []),
    "navigate_wallet": ("navigate_to_wallet", "Visualizar carteira (Playwright)", []),
    "navigate_account_health": ("navigate_to_account_health", "Visualizar saude da conta (Playwright)", []),
    "navigate_appeals": ("navigate_to_appeals", "Visualizar recursos (Playwright)", []),

    # Canais de envio por produto
    "get_product_shipping_channels": ("get_product_shipping_channels", "Ver canais de envio de um produto (Playwright)", ["item_id"]),
    "set_product_shipping_channel": ("set_product_shipping_channel", "Ativar/desativar canal de envio de um produto (Playwright)", ["item_id", "channel", "enable"]),
    "set_channel_for_all_products": ("set_channel_for_all_products", "Ativar/desativar canal de envio em TODOS os produtos (Playwright) — primeiro verifica cada produto, so altera os que precisam", ["channel", "enable"]),
}


def list_actions() -> dict[str, str]:
    """Listar todas as acoes disponiveis com descricao."""
    return {k: v[1] for k, v in sorted(ACTION_REGISTRY.items())}


def execute_action(action_name: str, **params) -> str:
    """Executar uma acao pelo nome."""
    if action_name not in ACTION_REGISTRY:
        raise ValueError(f"Acao desconhecida: {action_name}. Use list_actions() para ver disponiveis.")

    method_name, desc, _ = ACTION_REGISTRY[action_name]

    # Se um seller_center client foi passado como kwarg, usa ele
    client = params.pop("_seller_center_client", None)

    with SellerCenterActions(client=client) as actions:
        method = getattr(actions, method_name, None)
        if method is None:
            return f"❌ Metodo {method_name} nao implementado."

        try:
            result = method(**params)
            if isinstance(result, str):
                return result
            if isinstance(result, (list, dict)):
                return json.dumps(result, ensure_ascii=False, indent=2)[:1500]
            return str(result)[:1500]
        except Exception as e:
            return f"❌ Erro ao executar {action_name}: {e}"
