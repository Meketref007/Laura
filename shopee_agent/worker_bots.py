"""
Worker bots command handlers for ViluShop.

Each bot runs in its own thread listening for private commands
from the configured user and responds with real Shopee API data.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime

import requests

from shopee_agent.client import ShopeeClient
from shopee_agent.config import load_config
from shopee_agent.seller_center import SellerCenterClient

_INDISPONIVEL = "Indisponivel no momento"

_config = None
_client = None
_seller_center = None
_lock = threading.Lock()


def _ensure_clients():
    global _config, _client, _seller_center
    with _lock:
        if _config is None:
            _config = load_config()
        if _client is None:
            _client = ShopeeClient(_config)
        if _seller_center is None:
            _seller_center = SellerCenterClient()
            cookies_path = os.path.join(os.path.dirname(__file__), "..", "secrets", "seller_center_cookies.json")
            if not os.path.exists(cookies_path):
                print("[WARNING] Seller Center cookies not found. Run 'laura seller-center-import' first. "
                      "Worker bots for estoque/financeiro/marketing/atendimento will be unavailable.")
    return _client, _seller_center, _config


def _parse_command(text: str) -> tuple[str, str | None] | None:
    if not text:
        return None
    raw = text.strip()
    if not raw.startswith("/"):
        return None
    parts = raw.split(maxsplit=1)
    name = parts[0].split("@", maxsplit=1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else None
    return name, arg


_TODAY = datetime.now(UTC).strftime("%d/%m/%Y")


class WorkerBot:
    """Bot worker that listens for commands via long-polling for a category."""

    def __init__(self, category: str, token: str, user_chat_id: int | str) -> None:
        self.category = category
        self.token = token
        self.user_chat_id = int(user_chat_id) if not isinstance(user_chat_id, int) else user_chat_id
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_update_id = 0

    def start(self) -> None:
        if not self.token:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll, name=f"worker-{self.category}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _poll(self) -> None:
        session = requests.Session()
        while self._running:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                r = session.get(
                    url,
                    params={
                        "offset": self._last_update_id + 1,
                        "timeout": 30,
                        "allowed_updates": ["message"],
                    },
                    timeout=35,
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            self._last_update_id = update["update_id"]
                            self._process_update(update)
            except requests.Timeout:
                continue
            except Exception:
                if self._running:
                    time.sleep(5)

    def _process_update(self, update: dict) -> None:
        msg = update.get("message")
        if not msg:
            return
        chat_id = msg.get("chat", {}).get("id")
        if chat_id != self.user_chat_id:
            return
        text = msg.get("text", "")
        parsed = _parse_command(text)
        if parsed:
            cmd_name, cmd_arg = parsed
            self._handle_command(cmd_name, cmd_arg)

    def _handle_command(self, cmd: str, args: str | None) -> None:
        handlers = {
            "pedidos": self._handle_pedidos,
            "estoque": self._handle_estoque,
            "financeiro": self._handle_financeiro,
            "marketing": self._handle_marketing,
            "logistica": self._handle_logistica,
            "atendimento": self._handle_atendimento,
        }
        handler = handlers.get(self.category)
        if handler:
            handler(cmd, args)
        else:
            self._send(f"Comando `/{cmd}` nao reconhecido para categoria *{self.category}*.")

    # ── Pedidos ─────────────────────────────────────────────────

    def _handle_pedidos(self, cmd: str, args: str | None) -> None:
        if cmd == "ultimos":
            self._cmd_pedidos_ultimos()
        elif cmd == "buscar" and args:
            self._cmd_pedidos_buscar(args)
        else:
            self._send(f"Comando `/{cmd}` nao reconhecido para categoria *{self.category}*.")

    def _cmd_pedidos_ultimos(self) -> None:
        try:
            client, _, config = _ensure_clients()
            token = config.default_access_token
            shop_id = config.default_shop_id
            if not token or not shop_id:
                self._send(_INDISPONIVEL)
                return
            now = int(time.time())
            week_ago = now - 7 * 86400
            resp = client.get_order_list(
                access_token=token,
                shop_id=shop_id,
                time_from=week_ago,
                time_to=now,
                page_size=10,
            )
            orders = resp.data.get("response", {}).get("order_list", [])
            if not orders:
                self._send(f"*Nenhum pedido recente* — {_TODAY}")
                return
            lines = [f"*Ultimos {len(orders)} pedidos* — {_TODAY}\n"]
            for i, o in enumerate(orders[:10], 1):
                sn = o.get("order_sn", "N/A")
                amount = float(o.get("total_amount", 0))
                status = o.get("order_status", "unknown")
                lines.append(f"{i}. `{sn}` — R$ {amount:.2f} — *{status}*")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    def _cmd_pedidos_buscar(self, order_sn: str) -> None:
        try:
            client, _, config = _ensure_clients()
            token = config.default_access_token
            shop_id = config.default_shop_id
            if not token or not shop_id:
                self._send(_INDISPONIVEL)
                return
            resp = client.get_order_detail(
                access_token=token,
                shop_id=shop_id,
                order_sn=order_sn,
            )
            detail = resp.data.get("response", {})
            if not detail:
                self._send(f"Pedido `{order_sn}` nao encontrado.")
                return
            lines = [f"*Detalhe do pedido* `{order_sn}`\n"]
            lines.append(f"📦 Status: *{detail.get('order_status', 'N/A')}*")
            lines.append(f"💰 Total: R$ {float(detail.get('total_amount', 0)):.2f}")
            buyer = detail.get("buyer_user_name") or detail.get("buyer_username", "N/A")
            lines.append(f"👤 Comprador: {buyer}")
            shipping = detail.get("shipping", {}) or {}
            if shipping:
                fee = float(shipping.get("shipping_fee", 0))
                lines.append(f"🚚 Frete: R$ {fee:.2f}")
                address = shipping.get("address", shipping.get("full_address", ""))
                if address:
                    lines.append(f"📍 Endereco: {address}")
            items = detail.get("item_list", [])
            if items:
                lines.append(f"\n*Itens ({len(items)}):*")
                for it in items:
                    name = it.get("item_name", "Item")
                    qty = int(it.get("variation_quantity_purchased", 1))
                    price = float(it.get("item_price", 0))
                    lines.append(f"  - {name} x{qty} = R$ {price * qty:.2f}")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    # ── Estoque ─────────────────────────────────────────────────

    def _handle_estoque(self, cmd: str, args: str | None) -> None:
        if cmd == "baixo":
            self._cmd_estoque_baixo()
        elif cmd == "zerados":
            self._cmd_estoque_zerados()
        elif cmd == "buscar" and args:
            self._cmd_estoque_buscar(args)
        else:
            self._send(f"Comando `/{cmd}` nao reconhecido para categoria *{self.category}*.")

    def _cmd_estoque_baixo(self) -> None:
        try:
            _, seller, _ = _ensure_clients()
            products = seller.get_products(limit=100)
            low = [p for p in products if 0 < int(p.get("stock", 0)) < 10]
            if not low:
                self._send(f"*Nenhum produto com estoque baixo* — {_TODAY}")
                return
            lines = [f"*Produtos com estoque baixo* — {_TODAY}\n"]
            for p in low[:10]:
                name = p.get("item_name", p.get("name", "N/A"))
                sku = p.get("item_sku", "N/A")
                stock = p.get("stock", 0)
                lines.append(f"⚠️ *{name}* — SKU: `{sku}` — *{stock} und*")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    def _cmd_estoque_zerados(self) -> None:
        try:
            _, seller, _ = _ensure_clients()
            products = seller.get_products(limit=100)
            zero = [p for p in products if int(p.get("stock", 0)) == 0]
            if not zero:
                self._send(f"*Nenhum produto sem estoque* — {_TODAY}")
                return
            lines = [f"*Produtos sem estoque* — {_TODAY}\n"]
            for p in zero[:10]:
                name = p.get("item_name", p.get("name", "N/A"))
                sku = p.get("item_sku", "N/A")
                lines.append(f"🚫 *{name}* — SKU: `{sku}`")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    def _cmd_estoque_buscar(self, sku: str) -> None:
        try:
            _, seller, _ = _ensure_clients()
            products = seller.get_products(limit=100)
            found = [
                p
                for p in products
                if sku.lower() in p.get("item_sku", "").lower()
                or sku.lower() in p.get("item_name", "").lower()
            ]
            if not found:
                self._send(f"*Nenhum produto encontrado* para `{sku}`")
                return
            lines = [f"*Resultados para* `{sku}` — {_TODAY}\n"]
            for p in found[:5]:
                name = p.get("item_name", p.get("name", "N/A"))
                sku_val = p.get("item_sku", "N/A")
                stock = p.get("stock", 0)
                price = float(p.get("price", 0))
                lines.append(f"📦 *{name}*")
                lines.append(f"   SKU: `{sku_val}` | Estoque: *{stock}* | Preco: R$ {price:.2f}")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    # ── Financeiro ──────────────────────────────────────────────

    def _handle_financeiro(self, cmd: str, args: str | None) -> None:
        if cmd in ("receita", "hoje"):
            self._cmd_financeiro_hoje()
        elif cmd == "mensal":
            self._cmd_financeiro_mensal()
        else:
            self._send(f"Comando `/{cmd}` nao reconhecido para categoria *{self.category}*.")

    def _cmd_financeiro_hoje(self) -> None:
        try:
            _, seller, _ = _ensure_clients()
            summary = seller.get_financial_summary()
            wallet = seller.get_wallet_balance()
            income = seller.get_income(limit=10)
            lines = [f"*Financeiro — {_TODAY}*\n"]
            if summary:
                available = summary.get("available_balance", "N/A")
                pending = summary.get("pending_payout", "N/A")
                lines.append(f"💰 Saldo disponivel: *R$ {available}*")
                lines.append(f"⏳ Pendente: R$ {pending}")
            if wallet:
                bal_data = wallet.get("data", wallet)
                balance = bal_data.get("balance", "N/A")
                lines.append(f"💳 Carteira: R$ {balance}")
            income_data = income.get("data", []) if isinstance(income, dict) else []
            if income_data:
                total = sum(float(p.get("amount", 0)) for p in income_data[:10])
                count = len(income_data[:10])
                lines.append(f"\n📊 Ultimos {count} recebimentos: *R$ {total:.2f}*")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    def _cmd_financeiro_mensal(self) -> None:
        try:
            _, seller, _ = _ensure_clients()
            income = seller.get_income(limit=100)
            lines = [f"*Resumo Mensal* — {_TODAY[:2]}/{_TODAY[3:]}\n"]
            income_data = income.get("data", []) if isinstance(income, dict) else []
            if income_data:
                total = sum(float(p.get("amount", 0)) for p in income_data)
                lines.append(f"💰 Total recebido: *R$ {total:.2f}*")
                lines.append(f"📦 Transacoes: *{len(income_data)}*")
            else:
                lines.append("Nenhum dado disponivel.")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    # ── Marketing ───────────────────────────────────────────────

    def _handle_marketing(self, cmd: str, args: str | None) -> None:
        if cmd == "promocoes":
            self._cmd_marketing_promocoes()
        elif cmd == "anuncios":
            self._cmd_marketing_anuncios()
        else:
            self._send(f"Comando `/{cmd}` nao reconhecido para categoria *{self.category}*.")

    def _cmd_marketing_promocoes(self) -> None:
        try:
            _, seller, _ = _ensure_clients()
            flash = seller.get_flash_sales(limit=10)
            campaigns = seller.get_campaigns(limit=10)
            lines = [f"*Promocoes ativas* — {_TODAY}\n"]
            if flash:
                lines.append(f"🔥 *Flash Sales ({len(flash)}):*")
                for f in flash[:5]:
                    name = f.get("name", f.get("flash_sale_name", "N/A"))
                    status = f.get("status", "unknown")
                    lines.append(f"  - {name} ({status})")
            if campaigns:
                lines.append(f"\n🎯 *Campanhas ({len(campaigns)}):*")
                for c in campaigns[:5]:
                    name = c.get("name", c.get("campaign_name", "N/A"))
                    status = c.get("status", "unknown")
                    lines.append(f"  - {name} ({status})")
            if not flash and not campaigns:
                lines.append("Nenhuma promocao ativa no momento.")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    def _cmd_marketing_anuncios(self) -> None:
        try:
            client, _, config = _ensure_clients()
            token = config.default_access_token
            shop_id = config.default_shop_id
            lines = [f"*Anuncios* — {_TODAY}\n"]
            if token and shop_id:
                try:
                    camp_resp = client.get_campaign_list(
                        access_token=token,
                        shop_id=shop_id,
                        page_size=10,
                    )
                    camp_list = camp_resp.data.get("response", {}).get("campaign_list", [])
                    if camp_list:
                        lines.append(f"📣 *Campanhas de anuncios ({len(camp_list)}):*")
                        for c in camp_list[:5]:
                            name = c.get("campaign_name", "N/A")
                            budget = c.get("budget", "N/A")
                            lines.append(f"  - {name} (budget: R$ {budget})")
                    else:
                        lines.append("📣 Nenhum anuncio ativo.")
                except Exception:
                    lines.append("📣 Indisponivel no momento.")
            else:
                lines.append("📣 Token nao configurado para anuncios.")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    # ── Logistica ───────────────────────────────────────────────

    def _handle_logistica(self, cmd: str, args: str | None) -> None:
        if cmd == "pendentes":
            self._cmd_logistica_pendentes()
        elif cmd == "enviados":
            self._cmd_logistica_enviados()
        else:
            self._send(f"Comando `/{cmd}` nao reconhecido para categoria *{self.category}*.")

    def _cmd_logistica_pendentes(self) -> None:
        try:
            client, _, config = _ensure_clients()
            token = config.default_access_token
            shop_id = config.default_shop_id
            if not token or not shop_id:
                self._send(_INDISPONIVEL)
                return
            now = int(time.time())
            week_ago = now - 7 * 86400
            resp = client.get_order_list(
                access_token=token,
                shop_id=shop_id,
                time_from=week_ago,
                time_to=now,
                order_status="READY_TO_SHIP",
                page_size=20,
            )
            orders = resp.data.get("response", {}).get("order_list", [])
            lines = [f"*Pedidos para enviar* — {_TODAY}\n"]
            for o in orders[:10]:
                sn = o.get("order_sn", "N/A")
                lines.append(f"📦 `{sn}`")
            lines.append(f"\n🕐 Total pendentes: *{len(orders)}* pedidos")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    def _cmd_logistica_enviados(self) -> None:
        try:
            client, _, config = _ensure_clients()
            token = config.default_access_token
            shop_id = config.default_shop_id
            if not token or not shop_id:
                self._send(_INDISPONIVEL)
                return
            now = int(time.time())
            week_ago = now - 7 * 86400
            resp = client.get_order_list(
                access_token=token,
                shop_id=shop_id,
                time_from=week_ago,
                time_to=now,
                order_status="SHIPPED",
                page_size=20,
            )
            orders = resp.data.get("response", {}).get("order_list", [])
            lines = [f"*Ultimos pedidos enviados* — {_TODAY}\n"]
            for o in orders[:10]:
                sn = o.get("order_sn", "N/A")
                lines.append(f"📦 `{sn}` — Enviado")
            lines.append(f"\n📊 Total enviados: *{len(orders)}*")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    # ── Atendimento ─────────────────────────────────────────────

    def _handle_atendimento(self, cmd: str, args: str | None) -> None:
        if cmd == "naolidas":
            self._cmd_atendimento_naolidas()
        elif cmd == "responder":
            self._send("Funcionalidade `/responder` em desenvolvimento.")
        else:
            self._send(f"Comando `/{cmd}` nao reconhecido para categoria *{self.category}*.")

    def _cmd_atendimento_naolidas(self) -> None:
        try:
            _, seller, _ = _ensure_clients()
            conversations = seller.get_chat_management(limit=20) or []
            lines = [f"*Mensagens nao lidas* — {_TODAY}\n"]
            unread = [c for c in conversations if int(c.get("unread_count", 0)) > 0]
            if unread:
                for c in unread[:5]:
                    name = c.get("buyer_name", c.get("name", "N/A"))
                    last_msg = c.get("last_message", c.get("content", "..."))
                    lines.append(f"💬 *{name}* — \"{last_msg}\"")
                lines.append(
                    f"\n📊 Total nao lidas: *{len(unread)}* | Total conversas: *{len(conversations)}*"
                )
            else:
                lines.append("Nenhuma mensagem nao lida.")
            self._send("\n".join(lines))
        except Exception:
            self._send(_INDISPONIVEL)

    # ── Send ────────────────────────────────────────────────────

    def _send(self, text: str) -> None:
        if not self.token:
            return
        try:
            session = requests.Session()
            session.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.user_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        except Exception:
            pass


_WORKERS: list[WorkerBot] = []


def iniciar_todos_workers(user_chat_id: int | str | None = None) -> list[WorkerBot]:
    """Inicia todos os 6 workers bots em threads paralelas."""
    if user_chat_id is None:
        user_chat_id = int(os.getenv("VILU_BOT_CHAT_ID", "1803160745"))
    global _WORKERS
    for w in _WORKERS:
        w.stop()
    _WORKERS.clear()

    categories = [
        ("pedidos", "VILU_BOT_PEDIDOS_TOKEN"),
        ("estoque", "VILU_BOT_ESTOQUE_TOKEN"),
        ("financeiro", "VILU_BOT_FINANCEIRO_TOKEN"),
        ("marketing", "VILU_BOT_MARKETING_TOKEN"),
        ("logistica", "VILU_BOT_LOGISTICA_TOKEN"),
        ("atendimento", "VILU_BOT_ATENDIMENTO_TOKEN"),
    ]

    for category, env_var in categories:
        token = os.getenv(env_var, "").strip()
        bot = WorkerBot(category=category, token=token, user_chat_id=user_chat_id)
        bot.start()
        _WORKERS.append(bot)

    return _WORKERS


def parar_todos_workers() -> None:
    """Para todos os workers bots."""
    global _WORKERS
    for w in _WORKERS:
        w.stop()
    _WORKERS.clear()
