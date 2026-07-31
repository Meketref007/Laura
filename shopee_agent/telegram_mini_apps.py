from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .client import ShopeeClient


class MiniApp:
    name: str
    label: str
    emoji: str

    def menu(self) -> list[list[dict[str, str]]]:
        raise NotImplementedError

    def handle(self, action: str, arg: str | None, **ctx: Any) -> str:
        raise NotImplementedError


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _fmt_order(order: dict[str, Any]) -> str:
    sn = order.get("order_sn", "?")
    status = str(order.get("order_status", "") or "")
    amount = ""
    for k in ("total_amount", "amount", "paid_amount"):
        v = order.get(k)
        if v:
            try:
                amount = f"R${float(v)/100000:.2f}"
            except Exception:
                pass
            break
    product = (order.get("product_name") or order.get("item_name") or "")[:40]
    return f"#{sn} {status} {amount} {product}".strip()


# ──────────────────────────────────────────────
# Mini-app implementations
# ──────────────────────────────────────────────

class PedidosApp(MiniApp):
    name = "pedidos"
    label = "Pedidos"
    emoji = "📦"

    def menu(self) -> list[list[dict[str, str]]]:
        return [
            [{"text": "📋 Últimos pedidos", "callback_data": "app:pedidos:ultimos"}],
            [{"text": "📊 Resumo do dia", "callback_data": "app:pedidos:hoje"}],
            [{"text": "🚚 Pendentes de envio", "callback_data": "app:pedidos:pendentes"}],
            [{"text": "🔙 Voltar", "callback_data": "app:voltar"}],
        ]

    def handle(self, action: str, arg: str | None, **ctx: Any) -> str:
        client: ShopeeClient = ctx.get("client")
        token: str = ctx.get("access_token", "")
        shop_id: int = ctx.get("shop_id")
        ctx.get("reports_dir")

        if action == "ultimos":
            if not token or not shop_id:
                return "Shopee nao configurado"
            now = int(datetime.now(UTC).timestamp())
            week_ago = int((datetime.now(UTC) - timedelta(days=7)).timestamp())
            try:
                resp = client.get_order_list(access_token=token, shop_id=shop_id, time_from=week_ago, time_to=now, page_size=10)
                body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
                orders = body.get("order_list", []) if isinstance(body, dict) else []
                if not orders:
                    return "Nenhum pedido nos últimos 7 dias"
                lines = ["📋 Últimos pedidos:"]
                for o in orders[:10]:
                    lines.append(f"  {_fmt_order(o)}")
                return "\n".join(lines)
            except Exception as e:
                return f"Erro: {e}"

        if action == "hoje":
            if not token or not shop_id:
                return "Shopee nao configurado"
            today_start = int(datetime.now(UTC).replace(hour=0, minute=0, second=0).timestamp())
            now = int(datetime.now(UTC).timestamp())
            try:
                resp = client.get_order_list(access_token=token, shop_id=shop_id, time_from=today_start, time_to=now, page_size=50)
                body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
                orders = body.get("order_list", []) if isinstance(body, dict) else []
                total = 0
                count = 0
                for o in orders:
                    for k in ("total_amount", "amount", "paid_amount"):
                        v = o.get(k)
                        if v:
                            try:
                                total += float(v) / 100000
                            except Exception:
                                pass
                            break
                    count += 1
                return f"📊 Resumo do dia:\n  Pedidos: {count}\n  Faturamento: R${total:.2f}"
            except Exception as e:
                return f"Erro: {e}"

        if action == "pendentes":
            if not token or not shop_id:
                return "Shopee nao configurado"
            now = int(datetime.now(UTC).timestamp())
            week_ago = int((datetime.now(UTC) - timedelta(days=7)).timestamp())
            try:
                resp = client.get_order_list(access_token=token, shop_id=shop_id, time_from=week_ago, time_to=now, order_status="READY_TO_SHIP", page_size=20)
                body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
                orders = body.get("order_list", []) if isinstance(body, dict) else []
                if not orders:
                    return "Nenhum pedido pendente de envio"
                lines = ["🚚 Pendentes de envio:"]
                for o in orders[:10]:
                    lines.append(f"  {_fmt_order(o)}")
                return "\n".join(lines)
            except Exception as e:
                return f"Erro: {e}"

        return "Ação desconhecida"


class ProdutosApp(MiniApp):
    name = "produtos"
    label = "Produtos"
    emoji = "🏷️"

    def menu(self) -> list[list[dict[str, str]]]:
        return [
            [{"text": "📋 Listar produtos", "callback_data": "app:produtos:listar"}],
            [{"text": "📉 Estoque baixo", "callback_data": "app:produtos:estoque"}],
            [{"text": "⏸️ Todos sob encomenda", "callback_data": "app:produtos:pre_order"}],
            [{"text": "🔙 Voltar", "callback_data": "app:voltar"}],
        ]

    def handle(self, action: str, arg: str | None, **ctx: Any) -> str:
        client: ShopeeClient = ctx.get("client")
        token: str = ctx.get("access_token", "")
        shop_id: int = ctx.get("shop_id")
        reports_dir: Path = ctx.get("reports_dir")

        if action == "listar":
            if not token or not shop_id:
                return "Shopee nao configurado"
            try:
                resp = client.get_item_list(access_token=token, shop_id=shop_id)
                items = resp.data.get("items", resp.data.get("response", {}).get("item_list", [])) if isinstance(resp.data, dict) else []
                if isinstance(items, list):
                    return f"📋 Total de produtos: {len(items)}" + ("\n  (use /pedidos para mais detalhes)" if not items else "")
                return f"Resposta inesperada: {str(resp.data)[:200]}"
            except Exception as e:
                return f"Erro: {e}"

        if action == "estoque":
            latest = _load_json(reports_dir / "laura_inventory_monitor_latest.json")
            if not latest:
                return "Estoque indisponivel: rode `laura inventory-monitor` antes"
            low_count = int(latest.get("low_stock_count", 0) or 0)
            threshold = latest.get("low_stock_threshold", "N/A")
            sample = latest.get("low_stock_items", []) if isinstance(latest.get("low_stock_items"), list) else []
            lines = [f"📉 Estoque baixo: {low_count} item(ns) (limite {threshold})"]
            for item in sample[:10]:
                item_id = item.get("item_id", "?")
                stock = item.get("stock", "?")
                lines.append(f"  item {item_id}: estoque {stock}")
            return "\n".join(lines)

        if action == "pre_order":
            return "⚠️ Função de colocar todos sob encomenda (prazo mínimo de 3 dias (Open API)) requer confirmação. Envie:\n  /confirmar pre_order_3\npara executar."

        return "Ação desconhecida"


class FinancasApp(MiniApp):
    name = "financas"
    label = "Finanças"
    emoji = "💰"

    def menu(self) -> list[list[dict[str, str]]]:
        return [
            [{"text": "📊 Margem atual", "callback_data": "app:financas:margem"}],
            [{"text": "💵 Faturamento hoje", "callback_data": "app:financas:faturamento"}],
            [{"text": "📈 Renda diária", "callback_data": "app:financas:renda"}],
            [{"text": "🔙 Voltar", "callback_data": "app:voltar"}],
        ]

    def handle(self, action: str, arg: str | None, **ctx: Any) -> str:
        reports_dir: Path = ctx.get("reports_dir")

        if action == "margem":
            latest = _load_json(reports_dir / "laura_profitability_latest.json")
            if not latest:
                return "Margem indisponivel: rode pipeline de profitability"
            metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
            revenue = float(metrics.get("revenue", 0.0) or 0.0)
            profit = float(metrics.get("profit", 0.0) or 0.0)
            margin = float(metrics.get("margin_pct", 0.0) or 0.0)
            orders = int(metrics.get("orders", 0) or 0)
            return (
                f"💰 Margem atual:\n"
                f"  Receita: R${revenue:.2f}\n"
                f"  Lucro: R${profit:.2f}\n"
                f"  Margem: {margin:.2f}%\n"
                f"  Pedidos: {orders}"
            )

        if action == "faturamento":
            latest = _load_json(reports_dir / "laura_profitability_latest.json")
            if not latest:
                return "Dados indisponiveis"
            metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
            revenue = float(metrics.get("revenue", 0.0) or 0.0)
            return f"💵 Faturamento (período atual): R${revenue:.2f}"

        if action == "renda":
            latest = _load_json(reports_dir / "laura_profitability_latest.json")
            if not latest:
                return "Dados indisponiveis"
            metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
            profit = float(metrics.get("profit", 0.0) or 0.0)
            days = max(1, int(metrics.get("period_days", 1) or 1))
            daily = profit / days
            return f"📈 Renda diária estimada: R${daily:.2f}/dia (lucro R${profit:.2f} em {days} dias)"

        return "Ação desconhecida"


class MarketingApp(MiniApp):
    name = "marketing"
    label = "Marketing"
    emoji = "📢"

    def menu(self) -> list[list[dict[str, str]]]:
        return [
            [{"text": "📊 Status campanhas", "callback_data": "app:marketing:campanhas"}],
            [{"text": "⚡ Boost itens", "callback_data": "app:marketing:boost"}],
            [{"text": "🔙 Voltar", "callback_data": "app:voltar"}],
        ]

    def handle(self, action: str, arg: str | None, **ctx: Any) -> str:
        client: ShopeeClient = ctx.get("client")
        token: str = ctx.get("access_token", "")
        shop_id: int = ctx.get("shop_id")

        if action == "campanhas":
            if not token or not shop_id:
                return "Shopee nao configurado"
            try:
                resp = client.get_campaign_list(access_token=token, shop_id=shop_id)
                campaigns = resp.data.get("response", {}).get("campaign_list", []) if isinstance(resp.data, dict) else []
                if not campaigns:
                    return "Nenhuma campanha ativa"
                lines = ["📊 Campanhas:"]
                for c in campaigns[:10]:
                    name = c.get("campaign_name", "?")
                    status = c.get("status", "?")
                    budget = c.get("budget", "?")
                    lines.append(f"  {name} [{status}] budget: {budget}")
                return "\n".join(lines)
            except Exception as e:
                return f"Erro: {e}"

        if action == "boost":
            return "Para dar boost em itens, use:\n  /boost item_id1 item_id2 ..."

        return "Ação desconhecida"


class ConfigApp(MiniApp):
    name = "config"
    label = "Configurações"
    emoji = "⚙️"

    def menu(self) -> list[list[dict[str, str]]]:
        return [
            [{"text": "📧 Status e-mail", "callback_data": "app:config:email"}],
            [{"text": "🤖 Status Laura", "callback_data": "app:config:status"}],
            [{"text": "🌐 Painel web", "callback_data": "app:config:web"}],
            [{"text": "🔙 Voltar", "callback_data": "app:voltar"}],
        ]

    def handle(self, action: str, arg: str | None, **ctx: Any) -> str:
        reports_dir: Path = ctx.get("reports_dir")

        if action == "email":
            return "📧 Email: wordshop.suporte24h@gmail.com\n  Configure em: http://localhost:8000/config/telegram"

        if action == "status":
            health = _load_json(reports_dir / "laura_health_latest.json") or {}
            profit = _load_json(reports_dir / "laura_profitability_latest.json") or {}
            score = health.get("health_score", "N/A")
            decision = profit.get("action_key", "N/A")
            return (
                f"🤖 Status Laura:\n"
                f"  Health: {score}\n"
                f"  Decisão: {decision}\n"
                f"  Web config: http://localhost:8000/config/telegram"
            )

        if action == "web":
            return "🌐 Painel de configuração:\n  http://localhost:8000/config/telegram"

        return "Ação desconhecida"


# ──────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────

APPS: dict[str, MiniApp] = {
    app.name: app
    for app in [
        PedidosApp(),
        ProdutosApp(),
        FinancasApp(),
        MarketingApp(),
        ConfigApp(),
    ]
}


def main_menu() -> list[list[dict[str, str]]]:
    keyboard: list[list[dict[str, str]]] = []
    for app in APPS.values():
        keyboard.append([
            {"text": f"{app.emoji} {app.label}", "callback_data": f"app:open:{app.name}"}
        ])
    return keyboard


def handle_app_callback(data: str, **ctx: Any) -> str | None:
    parts = data.split(":")
    if len(parts) < 2 or parts[0] != "app":
        return None

    action = parts[1]

    if action == "voltar":
        from .telegram_bot import _render_main_menu
        return _render_main_menu(ctx.get("chat_id", ""))

    if action == "open" and len(parts) >= 3:
        app_name = parts[2]
        app = APPS.get(app_name)
        if not app:
            return "App nao encontrado"
        from .telegram_bot import _render_app_menu
        return _render_app_menu(app, ctx.get("chat_id", ""))

    if action in APPS:
        app = APPS[action]
        return app.menu()

    # app:app_name:sub_action
    if len(parts) >= 3 and parts[1] in APPS:
        app_name = parts[1]
        sub_action = parts[2]
        sub_arg = ":".join(parts[3:]) if len(parts) > 3 else None
        app = APPS[app_name]
        return app.handle(sub_action, sub_arg, **ctx)

    return None
