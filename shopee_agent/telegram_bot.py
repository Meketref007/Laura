from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from .client import ShopeeClient


@dataclass(frozen=True)
class TelegramCommand:
    name: str
    arg: str | None = None


def parse_command(text: str) -> TelegramCommand | None:
    if not text:
        return None
    raw = text.strip()
    if not raw.startswith("/"):
        return None
    parts = raw.split(maxsplit=1)
    name = parts[0].split("@", maxsplit=1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else None
    return TelegramCommand(name=name, arg=arg or None)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _callback_data(action: str, case_id: str) -> str:
    return f"{action}:{case_id}"


def _strip_html(text: str) -> str:
    """Remove HTML tags (including malformed ones from FTS5 truncation) and format callout boxes."""
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\b(?:span|div|p|li|ul|ol|h[1-6]|strong|em|b|i|u|a|br|img|table|tr|td|th)\b[^>]*>?", "", text, flags=re.IGNORECASE)
    text = re.sub(r'style\s*=\s*"[^"]*"', "", text, flags=re.IGNORECASE)
    text = re.sub(r"class\s*=\s*\"[^\"]*\"", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+data-[a-z-]+\s*=\s*\"[^\"]*\"", "", text, flags=re.IGNORECASE)
    # Remove truncated HTML fragments (from FTS5 truncation mid-tag)
    text = re.sub(r"rgb\s*\([^)]*\)", "", text)  # "rgb(0, 0, 0)"
    text = re.sub(r'"[^"]*"\s*>', " ", text)    # '...";">' or '..."><b>'
    text = re.sub(r"<[^>]*$", "", text, flags=re.MULTILINE)  # unfinished tag at line end
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p>\s*<p[^>]*>", "\n\n", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    for keyword, emoji in [("Importante", "⚠️"), ("Dica", "💡"), ("Observação", "👀"), ("Nota", "📝"), ("Aviso", "🔔")]:
        text = re.sub(rf"\b{keyword}\b", f"\n{emoji} *{keyword}:*", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _approval_keyboard(case_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Aprovar", "callback_data": _callback_data("approve", case_id)},
                {"text": "Cancelar", "callback_data": _callback_data("cancel", case_id)},
            ]
        ]
    }


def approve_remediation_case(case_id: str, reports_dir: Path, approved_by: str) -> tuple[bool, str]:
    history_file = reports_dir / "laura_remediation_cases.jsonl"
    if not history_file.exists():
        return False, f"Arquivo nao encontrado: {history_file}"
    lines = history_file.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    updated = False
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            new_lines.append(line)
            continue
        if obj.get("case_id") == case_id:
            if obj.get("executed"):
                return False, f"Caso {case_id} ja executado"
            obj["executed"] = True
            obj["executed_at"] = datetime.now(UTC).isoformat()
            obj["result"] = f"Approved via Telegram ({approved_by})"
            updated = True
        new_lines.append(json.dumps(obj, ensure_ascii=False))
    if not updated:
        return False, f"Caso nao encontrado: {case_id}"
    history_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    audit_path = reports_dir / "laura_remediation_audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"timestamp": datetime.now(UTC).isoformat(), "action": "approve_remediation", "case_id": case_id, "approved_by": approved_by, "source": "telegram_bot"}, ensure_ascii=False) + "\n")
    try:
        lines2 = history_file.read_text(encoding="utf-8").splitlines()
        for line in lines2:
            if not line.strip():
                continue
            try:
                obj2 = json.loads(line)
            except Exception:
                continue
            if obj2.get("case_id") == case_id:
                if obj2.get("execute_on_approve"):
                    action = obj2.get("action_key")
                    try:
                        import subprocess
                        dispatcher = Path(__file__).parents[1] / "scripts" / "laura_profitability_action_dispatch.sh"
                        subprocess.Popen([str(dispatcher), "--action", str(action), "--execute"], cwd=str(Path(__file__).parents[1]))
                    except Exception:
                        pass
                break
    except Exception:
        pass
    return True, f"Caso aprovado: {case_id}"


def _render_main_menu(chat_id: str) -> str:
    return "🏪 *Laura - Menu Principal*\nEscolha um mini-app:"


def _render_app_menu(app: Any, chat_id: str) -> str:
    return f"{app.emoji} *{app.label}*\nEscolha uma opcao:"  # type: ignore[union-attr]


# LLM helper for natural language understanding
INTENT_SYSTEM_PROMPT = """Você é Laura, assistente de loja Shopee. Responda APENAS com JSON válido, sem texto adicional.

Se o usuário PEDIR UMA AÇÃO, responda:
{"type":"action","intent":"NOME","params":{...},"response":"mensagem"}

Se for uma PERGUNTA, responda:
{"type":"query","response":"sua resposta aqui"}

AÇÕES DISPONÍVEIS (você PODE executar estas diretamente):

=== CONSULTAS (leitura de dados) ===
- get_shop_overview: {} — Visão geral da loja (pedidos, visitas, receita)
- get_shop_health: {} — Saúde da loja (penalidades, performance)
- get_financial_summary: {} — Resumo financeiro (receita, despesas, saldo)
- get_shipping_settings: {} — Configurações de envio/frete atuais
- get_shop_profile: {} — Perfil da loja (nome, descrição, endereço)
- get_orders: {"limit": N, "page": P} — Listar pedidos recentes
- get_ratings: {"limit": N, "page": P} — Listar avaliações de clientes
- get_violations: {} — Violações e penalidades da loja
- get_wallet_balance: {} — Saldo da carteira Shopee
- get_campaigns: {"limit": N} — Campanhas de marketing ativas
- get_vouchers: {"limit": N} — Cupons da loja
- get_flash_sales: {"limit": N} — Promoções relâmpago
- get_chat_messages: {"limit": N} — Mensagens do chat com compradores
- get_returns: {"limit": N} — Devoluções e reembolsos
- get_products: {"limit": N} — Produtos da loja
- get_account_health: {} — Saúde da conta do vendedor
- get_appeals: {"limit": N} — Recursos de penalidades
- get_rating_dashboard: {} — Dashboard de avaliações (métricas)
- get_todo_summary: {} — Resumo de tarefas pendentes
- get_pickup_settings: {} — Configuração atual de retirada pelo comprador
- get_status: {} — Status geral da loja
- get_inventory: {} — Produtos com estoque baixo
- get_email: {"limit": N} — E-mails não lidos

=== AÇÕES DE ESCRITA (modificam dados) ===
- holiday_mode: {"on": true/false} — LIGAR ou DESLIGAR modo férias
- pre_order_all: {"days": N} — Mudar prazo de envio de TODOS os produtos
- ship_order: {"order_sn": "XXX"} — Enviar/marcar um pedido como enviado
- reply_to_rating: {"order_id": NUMERO, "comment_id": NUMERO, "comment": "TEXTO"} — RESPONDER a uma avaliação de cliente
- update_shipping_setting: {"kwargs": {}} — Atualizar configurações de frete/envio
- update_shop_profile: {"kwargs": {}} — Atualizar perfil da loja
- enable_pickup: {"enable": true/false} — ATIVAR ou DESATIVAR retirada pelo comprador
- set_product_shipping_channel: {"item_id": NUMERO, "channel": "NOME", "enable": true/false} — ATIVAR ou DESATIVAR canal de envio em UM PRODUTO ESPECÍFICO (ex: Shopee Xpress, Retirada, etc.). Cada produto pode ter canais diferentes ativados.
- get_product_shipping_channels: {"item_id": NUMERO} — VER canais de envio ativos em um produto específico
- set_channel_for_all_products: {"channel": "NOME", "enable": true/false} — ATIVAR ou DESATIVAR canal de envio em TODOS os produtos. Primeiro verifica cada um, só altera os que precisam.

=== PESQUISA EM CONHECIMENTO ===
- search_articles: {"query": "termo"} — Buscar artigo na base de conhecimento Shopee. Use APENAS quando o usuário perguntar "como fazer" algo que NÃO está na lista de ações acima. Ex: "como criar cupom?", "como anunciar?"
- search_products: {"query": "termo"} — Buscar produtos na base da loja
- search_knowledge: {"query": "termo"} — Buscar em artigos, blog, cursos, webinars

REGRAS IMPORTANTES:
1. Quando o usuário PEDIR para FAZER algo (ativar, desativar, configurar, mudar, alterar, ligar, desligar, enviar, responder) use a ação de ESCRITA correspondente. NÃO use search_articles.
2. A ação enable_pickup serve para ativar/desativar retirada pelo comprador
3. A ação reply_to_rating serve para responder avaliações
4. A ação holiday_mode serve para ligar/desligar modo férias
5. Se o usuário pedir algo que realmente não tem ação direta, aí sim use search_articles

EXEMPLOS:
Usuário: ativa a retirada pelo comprador
Você: {"type":"action","intent":"enable_pickup","params":{"enable":true},"response":"Ativando retirada pelo comprador."}

Usuário: responde a avaliação do pedido 123456 dizendo "obrigado pelo feedback"
Você: {"type":"action","intent":"reply_to_rating","params":{"order_id":123456,"comment_id":0,"comment":"obrigado pelo feedback"},"response":"Enviando resposta à avaliação."}

Usuário: tira a loja do modo férias
Você: {"type":"action","intent":"holiday_mode","params":{"on":false},"response":"Vou desativar o modo férias."}

Usuário: quero ver as configurações de frete
Você: {"type":"action","intent":"get_shipping_settings","params":{},"response":"Buscando configurações de frete."}

Usuário: qual o status da loja?
Você: {"type":"query","response":"A loja está operando normalmente."}

Usuário: quero ver os emails
Você: {"type":"action","intent":"get_email","params":{"limit":5},"response":"Buscando últimos e-mails."}

Usuário: mostrar produtos com estoque baixo
Você: {"type":"action","intent":"get_inventory","params":{},"response":"Buscando produtos com estoque baixo."}

Usuário: como criar um cupom de desconto?
Você: {"type":"action","intent":"search_articles","params":{"query":"criar cupom desconto"},"response":"Vou buscar artigos sobre criação de cupons."}

IMPORTANTE: Responda APENAS o JSON, sem texto antes ou depois."""

_TELEGRAM_CHATS_FILE = Path(__file__).parents[1] / "reports" / "telegram_chats.json"
_LOG_FILE = Path(__file__).parents[1] / "logs" / "telegram_bot_intent.log"

def _log(msg: str, level: str = "INFO") -> None:
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(UTC).isoformat()}] [{level}] {msg}\n")
    except Exception:
        pass

def _load_chat_ids() -> list[str]:
    if not _TELEGRAM_CHATS_FILE.exists():
        return []
    try:
        data = json.loads(_TELEGRAM_CHATS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(c) for c in data]
        if isinstance(data, dict):
            ids = data.get("chat_ids", data.get("ids", []))
            return [str(c) for c in ids] if isinstance(ids, list) else []
    except Exception:
        pass
    return []


def _save_chat_ids(ids: list[str]) -> None:
    try:
        _TELEGRAM_CHATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TELEGRAM_CHATS_FILE.write_text(json.dumps({"chat_ids": ids}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _llm_ask_structured(question: str, context: dict[str, Any]) -> dict[str, Any]:
    """
    Send question to LLM and parse structured response for actions.
    Returns dict with keys: type ('query'|'action'), response (str),
    and optionally intent, params.
    """
    try:
        from .llm_local import ask_local
        ctx_lines = [f"{k}: {v}" for k, v in context.items() if v]
        prompt = f"{INTENT_SYSTEM_PROMPT}\n\nContexto da loja:\n" + "\n".join(ctx_lines) + f"\n\nUsuário: {question}\n\nVocê:"
        result = ask_local(prompt, max_tokens=400)
        raw = ""
        if isinstance(result, dict):
            raw = result.get("text", str(result))
        else:
            raw = str(result)

        # Try to parse entire response as JSON
        import json as _json
        for candidate in _extract_json_candidates(raw):
            try:
                parsed = _json.loads(candidate)
                if isinstance(parsed, dict):
                    if parsed.get("type") == "action":
                        intent = parsed.get("intent", "")
                        params = parsed.get("params", {})
                        response = parsed.get("response", f"Confirma {intent}?")
                        _log(f"LLM parse: action intent={intent}", "INFO")
                        return {"type": "action", "intent": intent, "params": params, "response": response}
                    if parsed.get("type") == "query":
                        resp_text = parsed.get("response", raw[:500])
                        _log(f"LLM parse: query response={resp_text[:80]}", "INFO")
                        return {"type": "query", "response": resp_text}
            except Exception:
                continue

        _log(f"LLM raw (no JSON): {raw[:200]}", "WARNING")
        # Fallback: try keyword matching on raw text
        keywords = {
            "férias": ("holiday_mode", {"on": True if "desativar" not in raw.lower() and "desligar" not in raw.lower() else False}),
            "ferias": ("holiday_mode", {"on": True}),
            "pré-venda": ("pre_order_all", {"days": 3}),
            "pre-venda": ("pre_order_all", {"days": 3}),
            "pre venda": ("pre_order_all", {"days": 3}),
            "prazo de envio": ("pre_order_all", {"days": 3}),
            "sob encomenda": ("pre_order_all", {"days": 3}),
            "pedido": ("get_orders", {"limit": 5}),
            "orders": ("get_orders", {"limit": 5}),
            "estoque": ("get_inventory", {}),
            "inventory": ("get_inventory", {}),
            "inventário": ("get_inventory", {}),
            "financeiro": ("get_financeiro", {}),
            "margem": ("get_financeiro", {}),
            "lucro": ("get_financeiro", {}),
            "receita": ("get_financeiro", {}),
            "e-mail": ("get_email", {"limit": 5}),
            "email": ("get_email", {"limit": 5}),
            "status": ("get_status", {}),
            "ajuda": ("get_help", {}),
            "help": ("get_help", {}),
            # search_products keywords
            "produto": ("search_products", {"query": raw}),
            "produtos": ("search_products", {"query": raw}),
            "característica": ("search_products", {"query": raw}),
            "caracteristicas": ("search_products", {"query": raw}),
            "descrição": ("search_products", {"query": raw}),
            "descricao": ("search_products", {"query": raw}),
            "variação": ("search_products", {"query": raw}),
            "variacao": ("search_products", {"query": raw}),
            "atributo": ("search_products", {"query": raw}),
            "cor": ("search_products", {"query": raw}),
            "tamanho": ("search_products", {"query": raw}),
            "frete": ("search_products", {"query": raw}),
            "peso": ("search_products", {"query": raw}),
            "dimensão": ("search_products", {"query": raw}),
            "dimensao": ("search_products", {"query": raw}),
            "sku": ("search_products", {"query": raw}),
            # search_knowledge keywords
            "curso": ("search_knowledge", {"query": raw}),
            "cursos": ("search_knowledge", {"query": raw}),
            "blog": ("search_knowledge", {"query": raw}),
            "webinar": ("search_knowledge", {"query": raw}),
            "treinamento": ("search_knowledge", {"query": raw}),
            "treinar": ("search_knowledge", {"query": raw}),
            "aprender": ("search_knowledge", {"query": raw}),
            "aprenda": ("search_knowledge", {"query": raw}),
            "tutorial": ("search_knowledge", {"query": raw}),
            "educação": ("search_knowledge", {"query": raw}),
            "educacao": ("search_knowledge", {"query": raw}),
        }
        raw_lower = raw.lower()
        for keyword, (intent, params) in keywords.items():
            if keyword in raw_lower:
                _log(f"LLM keyword fallback: {keyword}->{intent}", "INFO")
                return {"type": "action", "intent": intent, "params": params, "response": raw[:200]}

        # Ultimo fallback: tenta keywords na pergunta original do usuario
        q_lower = question.lower()
        for keyword, (intent, params) in keywords.items():
            if keyword in q_lower:
                _log(f"LLM question keyword: {keyword}->{intent}", "INFO")
                return {"type": "action", "intent": intent, "params": params, "response": raw[:200]}

        return {"type": "query", "response": raw[:500]}
    except Exception as _exc:
        _log(f"LLM ask_local exception: {_exc}", "ERROR")
        import traceback as _tb
        _log(f"LLM ask_local traceback: {''.join(_tb.format_exception(type(_exc), _exc, _exc.__traceback__))}", "ERROR")
        pass

    # Fallback to Claude API
    try:
        from .llm import ask_claude
        ctx_lines = [f"{k}: {v}" for k, v in context.items() if v]
        prompt = f"{INTENT_SYSTEM_PROMPT}\n\nContexto:\n" + "\n".join(ctx_lines) + f"\n\nPergunta: {question}"
        result = ask_claude(system="Você é Laura, assistente Shopee.", prompt=prompt)
        raw = ""
        if isinstance(result, dict):
            raw = result.get("content", str(result))
        else:
            raw = str(result)

        for candidate in _extract_json_candidates(raw):
            try:
                parsed = _json.loads(candidate)
                if isinstance(parsed, dict):
                    if parsed.get("type") == "action":
                        intent = parsed.get("intent", "")
                        params = parsed.get("params", {})
                        response = parsed.get("response", f"Confirma {intent}?")
                        return {"type": "action", "intent": intent, "params": params, "response": response}
                    if parsed.get("type") == "query":
                        return {"type": "query", "response": parsed.get("response", raw[:500])}
            except Exception:
                continue
        return {"type": "query", "response": raw[:500]}
    except Exception as e:
        return {"type": "query", "response": f"Não consegui processar agora. Erro: {e}"}


def _extract_json_candidates(text: str) -> list[str]:
    """Extract all JSON object candidates from text, best effort."""
    import json as _json
    candidates = []
    # Try code blocks first
    for delim in ("```json", "```"):
        start = text.find(delim)
        if start >= 0:
            start += len(delim)
            end = text.find("```", start)
            if end > start:
                candidates.append(text[start:end].strip())
    # Try braces
    decoder = _json.JSONDecoder()
    for start_char in ("{", "["):
        idx = 0
        while True:
            pos = text.find(start_char, idx)
            if pos < 0:
                break
            try:
                obj, end = decoder.raw_decode(text[pos:])
                candidates.append(_json.dumps(obj, ensure_ascii=False))
                idx = pos + end
            except Exception:
                idx = pos + 1
    return candidates


# Old _llm_ask kept for backward compatibility with any external callers
def _llm_ask(question: str, context: dict[str, Any]) -> str:
    return _llm_ask_structured(question, context).get("response", "Não entendi.")


def _build_shop_context(reports_dir: Path, seller_center: Any = None) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    health = _load_json(reports_dir / "laura_health_latest.json") or {}
    profit = _load_json(reports_dir / "laura_profitability_latest.json") or {}
    inventory = _load_json(reports_dir / "laura_inventory_monitor_latest.json") or {}
    ctx["health_score"] = health.get("health_score", "N/A")
    metrics = profit.get("metrics") if isinstance(profit.get("metrics"), dict) else {}
    ctx["revenue"] = metrics.get("revenue", "N/A")
    ctx["profit"] = metrics.get("profit", "N/A")
    ctx["margin_pct"] = metrics.get("margin_pct", "N/A")
    ctx["orders_count"] = metrics.get("orders", "N/A")
    ctx["low_stock_count"] = inventory.get("low_stock_count", "N/A")
    ctx["action_key"] = profit.get("action_key", "N/A")

    # Seller Center data (logged-in web API)
    if seller_center and seller_center.is_authenticated():
        try:
            info = seller_center.get_shop_info()
            if info:
                ctx["seller_shop_name"] = info.get("shop_name", "N/A")
                ctx["seller_shop_status"] = info.get("status", "N/A")
        except Exception:
            pass
        try:
            health_data = seller_center.get_shop_health()
            if isinstance(health_data, dict):
                ctx["seller_health_score"] = health_data.get("health_score", "N/A")
        except Exception:
            pass
        try:
            financial = seller_center.get_financial_summary()
            if isinstance(financial, dict):
                ctx["seller_balance"] = financial.get("available_balance", "N/A")
        except Exception:
            pass
        try:
            violations = seller_center.get_violation_records()
            ctx["seller_violations"] = len(violations) if violations else 0
        except Exception:
            pass
        try:
            settings = seller_center.get_shop_settings()
            if isinstance(settings, dict):
                ctx["seller_holiday_mode"] = settings.get("holiday_mode", "N/A")
        except Exception:
            pass

    return ctx


class LauraTelegramBot:
    def __init__(
        self,
        *,
        token: str,
        allowed_chat_id: str | None,
        shopee_client: ShopeeClient,
        access_token: str | None,
        shop_id: int | None,
        reports_dir: Path,
        poll_timeout_seconds: int = 30,
        sleep_seconds: float = 1.0,
        email_manager: Any = None,
    ) -> None:
        self.token = token
        self.allowed_chat_id = str(allowed_chat_id).strip() if allowed_chat_id else None
        self.client = shopee_client
        self.access_token = access_token
        self.shop_id = shop_id
        self.reports_dir = reports_dir
        self.poll_timeout_seconds = max(1, int(poll_timeout_seconds))
        self.sleep_seconds = max(0.2, float(sleep_seconds))
        self.offset_file = reports_dir / "laura_telegram_bot_offset.state"
        self.session = requests.Session()
        self.email_manager = email_manager
        self._confirmations: dict[str, dict[str, Any]] = {}
        self._processed_ids: set[int] = set()
        self._running = False
        self._poll_thread: threading.Thread | None = None
        # Seller Center (logged-in web API)
        self.seller_center: Any = None
        self.seller_actions: Any = None
        try:
            from .seller_center import SellerCenterClient
            sc = SellerCenterClient()
            if sc.is_authenticated():
                self.seller_center = sc
                from .seller_center_actions import SellerCenterActions
                self.seller_actions = SellerCenterActions(sc)
                _log("Seller Center autenticado via cookies", "INFO")
            else:
                _log("Seller Center: cookies expirados ou ausentes", "WARNING")
        except Exception as e:
            _log(f"Seller Center init error: {e}", "WARNING")

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _load_offset(self) -> int:
        if not self.offset_file.exists():
            return 0
        try:
            return int(self.offset_file.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        try:
            self.offset_file.parent.mkdir(parents=True, exist_ok=True)
            self.offset_file.write_text(str(int(offset)), encoding="utf-8")
        except Exception:
            pass

    def _get_updates(self, offset: int) -> list[dict[str, Any]]:
        try:
            response = self.session.get(
                self._api_url("getUpdates"),
                params={
                    "offset": offset,
                    "timeout": self.poll_timeout_seconds,
                    "allowed_updates": json.dumps(["message", "callback_query"]),
                },
                timeout=self.poll_timeout_seconds + 10,
            )
            payload = response.json()
        except Exception:
            return []
        if not isinstance(payload, dict) or not payload.get("ok"):
            return []
        result = payload.get("result")
        return result if isinstance(result, list) else []

    def _send_message(self, chat_id: str, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        try:
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            self.session.post(self._api_url("sendMessage"), json=payload, timeout=10)
        except Exception as e:
            _log(f"sendMessage falhou para chat {chat_id}: {e}", "WARNING")

    def _async_execute_action(self, chat_id: str, action: str, params: dict) -> None:
        """Execute a long action in background thread. Sends 'processing' immediately,
        then sends result when done."""
        self._send_message(chat_id, "⏳ Processando... (acao longa pode levar alguns minutos)")
        t = threading.Thread(target=self._run_action_and_report, args=(chat_id, action, params), daemon=True)
        t.start()

    def _run_action_and_report(self, chat_id: str, action: str, params: dict) -> None:
        try:
            from .seller_center import SellerCenterClient
            from .seller_center_actions import execute_action
            # Tenta reaproveitar client autenticado do bot
            client = None
            if self.seller_actions is not None:
                client = getattr(self.seller_actions, 'client', None)
                if client is not None and not client.is_authenticated():
                    client = None  # expirado, recria do arquivo
            if client is None:
                fresh = SellerCenterClient()
                if fresh.is_authenticated():
                    client = fresh
            if client is not None:
                params["_seller_center_client"] = client
            result = execute_action(action, **params)
            self._send_message(chat_id, result)
        except Exception as e:
            self._send_message(chat_id, f"Erro ao executar {action}: {e}")

    def _edit_message(self, chat_id: str, message_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        try:
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            self.session.post(self._api_url("editMessageText"), json=payload, timeout=10)
        except Exception as e:
            _log(f"editMessageText falhou para chat {chat_id}: {e}", "WARNING")

    def _answer_callback(self, callback_id: str, text: str) -> None:
        try:
            self.session.post(
                self._api_url("answerCallbackQuery"),
                json={"callback_query_id": callback_id, "text": text, "show_alert": False},
                timeout=10,
            )
        except Exception as e:
            _log(f"answerCallbackQuery falhou: {e}", "WARNING")

    # ── Public API ────────────────────────────────────────────────────────────

    def send_message(self, chat_id: str, text: str) -> bool:
        try:
            self._send_message(chat_id, text)
            return True
        except Exception:
            return False

    def broadcast(self, text: str) -> int:
        ids = self.get_chat_ids()
        count = 0
        for cid in ids:
            if self.send_message(cid, text):
                count += 1
        return count

    def get_chat_ids(self) -> list[str]:
        return _load_chat_ids()

    def register_chat_id(self, chat_id: str) -> None:
        ids = self.get_chat_ids()
        cid = str(chat_id).strip()
        if cid and cid not in ids:
            ids.append(cid)
            _save_chat_ids(ids)

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running

    # ── Internal ──────────────────────────────────────────────────────────────

    def _main_menu_keyboard(self) -> dict[str, Any]:
        from .telegram_mini_apps import APPS
        keyboard = []
        for app in APPS.values():
            keyboard.append([
                {"text": f"{app.emoji} {app.label}", "callback_data": f"app:open:{app.name}"}
            ])
        return {"inline_keyboard": keyboard}

    def _help_message(self) -> str:
        return (
            "🤖 *Laura - Assistente ViluShop*\n\n"
            "✨ *Fale em linguagem natural!*\n"
            'Ex: "qual o status da loja?", "quero ver os pedidos",\n'
            '"ative modo ferias", "como esta o estoque?"\n\n'
            "*Acoes que eu faco:*\n"
            "/status - Status completo (com Central do Vendedor)\n"
            "/pedidos - Ultimos pedidos\n"
            "/estoque - Estoque baixo\n"
            "/margem - Margem e lucro\n"
            "/email - Ver e-mails\n"
            "/ferias - Modo ferias\n"
            "/enviar <ID> - Enviar pedido\n"
            "/violacoes - Violacoes e penalidades\n"
            "/avaliacoes - Avaliacoes da loja\n"
            "/configuracoes - Info da Central do Vendedor\n\n"
            "*Buscas:*\n"
            "/artigo <termo> - Artigos Shopee\n"
            "/produto <termo> - Produtos da loja\n"
            "/conhecimento <termo> - Cursos e blog\n"
            "/categorias - Listar categorias\n"
            "/acoes - Todas as acoes da Central do Vendedor\n\n"
            "*Outros:*\n"
            "/confirmar - Confirmar acao\n"
            "/ensinar - Ensinar nova acao\n"
            "/help - Esta ajuda\n\n"
            "⚠️ *Importante:* Se eu nao conseguir executar algo, "
            "e porque a API da Shopee nao permite. Nao invento respostas!"
        )

    def _status_message(self) -> str:
        health = _load_json(self.reports_dir / "laura_health_latest.json") or {}
        profit = _load_json(self.reports_dir / "laura_profitability_latest.json") or {}
        webhook_txt = ""
        wf = self.reports_dir / "laura_webhook_callback_latest.txt"
        if wf.exists():
            webhook_txt = wf.read_text(encoding="utf-8").strip()
        health_score = health.get("health_score", "N/A")
        decision = profit.get("action_key", "N/A")
        margin = ((profit.get("metrics") or {}).get("margin_pct") if isinstance(profit.get("metrics"), dict) else None)
        margin_txt = "N/A" if margin is None else f"{float(margin):.2f}%"

        lines = ["📊 *Status Laura*"]
        lines.append(f"health_score: {health_score}")
        lines.append(f"decision: {decision}")
        lines.append(f"margin_pct: {margin_txt}")

        # Seller Center data
        if self.seller_center and self.seller_center.is_authenticated():
            try:
                info = self.seller_center.get_shop_info() or {}
                if info.get("shop_name"):
                    lines.append(f"loja: {info['shop_name']}")
            except Exception:
                pass
            try:
                financial = self.seller_center.get_financial_summary() or {}
                bal = financial.get("available_balance")
                if bal:
                    lines.append(f"saldo: R$ {float(bal):.2f}")
            except Exception:
                pass
            try:
                violations = self.seller_center.get_violation_records() or []
                if violations:
                    lines.append(f"violacoes: {len(violations)} ⚠️")
                else:
                    lines.append("violacoes: 0 ✅")
            except Exception:
                pass

        lines.append(f"webhook: {webhook_txt or 'N/A'}")
        return "\n".join(lines)

    def _seller_info_message(self) -> str:
        """Return Seller Center shop info."""
        if not self.seller_center:
            return "Central do Vendedor nao autenticada. Configure o auto-login."
        try:
            info = self.seller_center.get_shop_info() or {}
            settings = self.seller_center.get_shop_settings() or {}
            lines = ["📋 *Central do Vendedor*"]
            if info.get("shop_name"):
                lines.append(f"\n🏪 Loja: {info['shop_name']}")
            if info.get("status"):
                lines.append(f"📌 Status: {info['status']}")
            if settings.get("holiday_mode"):
                lines.append(f"🏖️ Modo ferias: {settings['holiday_mode']}")
            try:
                health = self.seller_center.get_shop_health()
                if isinstance(health, dict) and "health_score" in health:
                    lines.append(f"💚 Saude: {health['health_score']}")
            except Exception:
                pass
            try:
                financial = self.seller_center.get_financial_summary()
                if isinstance(financial, dict):
                    balance = financial.get("available_balance", "N/A")
                    lines.append(f"💰 Saldo disponivel: R$ {float(balance):.2f}" if balance != "N/A" else "💰 Saldo: N/A")
            except Exception:
                pass
            return "\n".join(lines)
        except Exception as e:
            return f"Erro ao consultar Central do Vendedor: {e}"

    def _shipping_settings_message(self) -> str:
        """Return shipping/logistics settings from Seller Center."""
        if not self.seller_center:
            return "Central do Vendedor nao autenticada."
        try:
            settings = self.seller_center.get_shipping_settings() or {}
            lines = ["🚚 *Configuracoes de Envio*"]
            if isinstance(settings, dict):
                for k, v in settings.items():
                    if not k.startswith("_") and not callable(v):
                        lines.append(f"\n{k}: {v}")
            else:
                lines.append(f"\n{str(settings)[:500]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Erro ao consultar config de envio: {e}"

    def _violations_message(self) -> str:
        """Return violation/penalty records."""
        if not self.seller_center:
            return "Central do Vendedor nao autenticada."
        try:
            records = self.seller_center.get_violation_records() or []
            if not records:
                return "✅ Sem violacoes ou penalidades ativas."
            lines = [f"⚠️ *Violacoes ({len(records)}):*"]
            for v in records[:10]:
                desc = v.get("description", v.get("reason", str(v)[:80]))
                status = v.get("status", "active")
                lines.append(f"\n• {desc} [{status}]")
            return "\n".join(lines)
        except Exception as e:
            return f"Erro ao consultar violacoes: {e}"

    def _ratings_message(self) -> str:
        """Return ratings from Seller Center."""
        if not self.seller_center:
            return "Central do Vendedor nao autenticada."
        try:
            ratings = self.seller_center.get_ratings(limit=5) or []
            if not ratings:
                return "Nenhuma avaliacao encontrada."
            lines = ["⭐ *Ultimas Avaliacoes:*"]
            for r in ratings[:5]:
                star = r.get("rating_star", "?")
                text = r.get("comment", r.get("content", ""))[:100]
                user = r.get("buyer_username", r.get("user", "?"))
                lines.append(f"\n{'⭐' * int(star)} {user}")
                if text:
                    lines.append(f"   \"{text}\"")
            return "\n".join(lines)
        except Exception as e:
            return f"Erro ao consultar avaliacoes: {e}"

    def _list_seller_actions(self) -> str:
        """Listar todas as acoes disponiveis na Central do Vendedor."""
        try:
            from .seller_center_actions import list_actions
            actions = list_actions()
            lines = ["📋 *Acoes da Central do Vendedor:*\n"]
            for name, desc in actions.items():
                lines.append(f"  • `{name}` — {desc}")
            return "\n".join(lines)
        except Exception as e:
            return f"Erro ao listar acoes: {e}"

    def _execute_seller_action(self, action_name: str, **params) -> str:
        """Executar uma acao da Central do Vendedor pelo nome."""
        if not self.seller_actions:
            return "Central do Vendedor nao autenticada."
        try:
            from .seller_center_actions import execute_action
            return execute_action(action_name, **params)
        except Exception as e:
            return f"Erro ao executar {action_name}: {e}"

    def _seller_action_by_name(self, action_name: str, **kwargs) -> str:
        """Atalho para executar acao pelo nome e formatar resultado."""
        if not self.seller_actions:
            return "❌ Central do Vendedor nao autenticada."
        try:
            from .seller_center_actions import ACTION_REGISTRY
            if action_name not in ACTION_REGISTRY:
                return f"Acao '{action_name}' nao encontrada no registro."
            result = self._execute_seller_action(action_name, **kwargs)
            return result
        except Exception as e:
            return f"Erro: {e}"

    @staticmethod
    def _friendly_order_status(status: Any) -> str:
        raw = str(status or "").strip()
        if not raw:
            return "Nao informado"
        normalized = raw.upper()
        labels = {
            "READY_TO_SHIP": "Pronto para envio",
            "UNPAID": "Aguardando pagamento",
            "PROCESSED": "Em processamento",
            "SHIPPED": "Enviado",
            "COMPLETED": "Concluido",
            "TO_CONFIRM_RECEIVE": "Aguardando confirmacao",
            "CANCELLED": "Cancelado",
            "IN_CANCEL": "Cancelamento em andamento",
            "INCOMPLETED": "Incompleto",
            "TO_RETURN": "Devolucao em andamento",
        }
        return labels.get(normalized, raw.replace("_", " ").strip().capitalize())

    @staticmethod
    def _format_order_amount(order: dict[str, Any]) -> str | None:
        for key in ("total_amount", "amount", "order_total", "payment_amount", "paid_amount", "total_price"):
            value = order.get(key)
            if value in (None, "", False):
                continue
            try:
                amount = float(value)
            except Exception:
                continue
            if amount < 0:
                continue
            return f"R$ {amount / 100000:.2f}"
        return None

    def _format_order_block(self, order: dict[str, Any], index: int | None = None) -> list[str]:
        order_sn = str(order.get("order_sn", "")).strip() or "sem numero"
        status = self._friendly_order_status(order.get("order_status") or order.get("status") or order.get("state"))
        product = str(order.get("product_name") or order.get("item_name") or order.get("name") or "").strip()
        quantity = order.get("product_quantity") or order.get("quantity") or order.get("item_quantity")
        buyer = str(order.get("buyer_username") or order.get("buyer_nickname") or order.get("buyer_id") or "").strip()
        amount = self._format_order_amount(order)
        payment_status = str(order.get("payment_status") or order.get("checkout_status") or "").strip()
        create_time = order.get("create_time") or order.get("created_time") or order.get("ctime")
        prefix = f"{index}. " if index is not None else "- "
        lines = [f"{prefix}Pedido {order_sn}", f"   Situacao: {status}"]
        if product:
            lines.append(f"   Produto: {product}")
        if quantity not in (None, "", 0, "0"):
            lines.append(f"   Quantidade: {quantity}")
        if buyer:
            lines.append(f"   Cliente: {buyer}")
        if amount:
            lines.append(f"   Valor: {amount}")
        if payment_status:
            lines.append(f"   Pagamento: {payment_status.replace('_', ' ').strip().capitalize()}")
        if create_time not in (None, "", 0, "0"):
            lines.append(f"   Criado em: {create_time}")
        return lines

    def _orders_message(self, raw_n: str | None) -> str:
        if not self.access_token or self.shop_id is None:
            return "Pedidos indisponivel: configure SHOPEE_DEFAULT_ACCESS_TOKEN e SHOPEE_DEFAULT_SHOP_ID"
        n = 5
        if raw_n:
            try:
                n = max(1, min(20, int(raw_n.strip())))
            except Exception:
                n = 5
        now = int(datetime.now(UTC).timestamp())
        time_from = int((datetime.now(UTC) - timedelta(days=7)).timestamp())
        resp = self.client.get_order_list(access_token=self.access_token, shop_id=self.shop_id, time_from=time_from, time_to=now, page_size=max(20, n))
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        orders = body.get("order_list", []) if isinstance(body, dict) else []
        if not orders:
            return "Nenhum pedido recente encontrado"
        lines = [f"Pedidos recentes (ultimos {min(n, len(orders))})"]
        for idx, order in enumerate(orders[:n], start=1):
            if not isinstance(order, dict):
                continue
            lines.extend(self._format_order_block(order, index=idx))
        return "\n".join(lines)

    def _inventory_message(self) -> str:
        latest = _load_json(self.reports_dir / "laura_inventory_monitor_latest.json")
        if not latest:
            return "Estoque indisponivel: rode `laura inventory-monitor` antes"
        low_count = int(latest.get("low_stock_count", 0) or 0)
        threshold = latest.get("low_stock_threshold", "N/A")
        sample = latest.get("low_stock_items", []) if isinstance(latest.get("low_stock_items"), list) else []
        lines = [f"Estoque baixo: {low_count} item(ns) (limite {threshold})"]
        for item in sample[:5]:
            if not isinstance(item, dict):
                continue
            item_id = item.get("item_id", "?")
            stock = item.get("stock", "?")
            lines.append(f"- item {item_id}: estoque {stock}")
        return "\n".join(lines)

    def _margin_message(self) -> str:
        latest = _load_json(self.reports_dir / "laura_profitability_latest.json")
        if not latest:
            return "Margem indisponivel: rode pipeline de profitability"
        metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
        revenue = float(metrics.get("revenue", 0.0) or 0.0)
        profit = float(metrics.get("profit", 0.0) or 0.0)
        margin = float(metrics.get("margin_pct", 0.0) or 0.0)
        orders = int(metrics.get("orders", 0) or 0)
        action = str(latest.get("action_key", "monitor_only"))
        return f"Margem atual\nrevenue: R$ {revenue:.2f}\nprofit: R$ {profit:.2f}\nmargin_pct: {margin:.2f}%\norders: {orders}\naction: {action}"

    def _email_message(self, limit: int = 5) -> str:
        if not self.email_manager:
            return "Email nao configurado. Configure GMAIL_CREDENTIALS_FILE no .env"
        try:
            unseen = self.email_manager.fetch_unseen()
            if not unseen:
                return "Nenhum email nao lido."
            lines = [f"📧 {len(unseen)} email(ns) nao lido(s):"]
            for mail in unseen[:limit]:
                lines.append(f"  De: {mail.sender[:40]}")
                lines.append(f"  Assunto: {mail.subject[:60]}")
                lines.append(f"  {mail.snippet[:80]}")
                lines.append("")
            return "\n".join(lines)
        except Exception as e:
            return f"Erro ao acessar email: {e}"

    def _approve_message(self, case_id: str | None, from_user: str) -> str:
        if not case_id:
            return "Uso: /aprovar <case_id>"
        case_id = case_id.strip()
        ok, msg = approve_remediation_case(case_id=case_id, reports_dir=self.reports_dir, approved_by=from_user)
        return msg if ok else f"Falha ao aprovar: {msg}"

    def _execute_intent(self, intent: str, params: dict[str, Any]) -> str:
        """Execute a detected intent from natural language. Returns response text."""
        if intent == "holiday_mode":
            on = params.get("on", True)
            if not isinstance(on, bool):
                on = str(params.get("on", "true")).strip().lower() in ("true", "1", "sim", "yes")
            mode = "férias" if on else "normal"
            cid = f"holiday_{'on' if on else 'off'}"
            self._confirmations[cid] = {
                "action": "holiday_mode",
                "params": {"on": on},
                "desc": f"Alternar loja para modo {mode}",
            }
            return f"🔄 Confirmar: alternar loja para *modo {mode}*?\nEnvie: /confirmar {cid}"

        if intent == "pre_order_all":
            days = max(3, int(params.get("days", 3)))
            cid = f"pre_order_{days}"
            self._confirmations[cid] = {
                "action": "pre_order_all",
                "params": {"days": days},
                "desc": f"Definir pré-venda de {days} dias para todos os produtos",
            }
            return f"🔄 Confirmar: definir *pré-venda de {days} dia(s)* para todos os produtos?\nEnvie: /confirmar {cid}"

        if intent == "ship_order":
            order_sn = str(params.get("order_sn", ""))
            if not order_sn:
                return "Qual o número do pedido para enviar?"
            cid = f"ship_{order_sn}"
            self._confirmations[cid] = {
                "action": "ship_order",
                "params": {"order_sn": order_sn},
                "desc": f"Enviar pedido {order_sn}",
            }
            return f"🔄 Confirmar: *enviar pedido {order_sn}*?\nEnvie: /confirmar {cid}"

        # Read-only intents - execute immediately
        if intent == "get_status":
            return self._status_message()
        if intent == "get_orders":
            limit = int(params.get("limit", 5))
            return self._orders_message(str(limit))
        if intent == "get_inventory":
            return self._inventory_message()
        if intent == "get_financeiro":
            return self._margin_message()
        if intent == "get_email":
            limit = int(params.get("limit", 5))
            return self._email_message(limit)
        if intent == "get_help":
            return self._help_message()
        if intent == "search_articles":
            query = params.get("query", "")
            if not query:
                return "O que voce gostaria de saber? Ex: /artigo ativar retirada"
            return self._artigo_message(query)

        if intent == "search_products":
            query = params.get("query", "")
            if not query:
                return "Qual produto voce quer buscar? Ex: /produto tenis"
            return self._produto_message(query)

        if intent == "search_knowledge":
            query = params.get("query", "")
            if not query:
                return "O que voce quer aprender? Ex: curso shopee ads"
            return self._conhecimento_message(query)

        # --- Seller Center intents ---
        if intent == "get_seller_info":
            return self._seller_info_message()
        if intent == "get_shipping_settings":
            return self._shipping_settings_message()
        if intent == "get_violations":
            return self._violations_message()
        if intent == "get_ratings":
            return self._ratings_message()

        if intent == "seller_action":
            action_name = params.get("action", "")
            return self._execute_seller_action(action_name, **params)

        if intent == "list_actions":
            return self._list_seller_actions()

        # --- Per-product shipping channels ---
        if intent == "get_product_shipping_channels":
            item_id = int(params.get("item_id", 0))
            if not item_id:
                return "Qual o ID do produto?"
            return self._seller_action_by_name("get_product_shipping_channels", item_id=item_id)

        if intent == "set_product_shipping_channel":
            item_id = int(params.get("item_id", 0))
            channel = params.get("channel", "Shopee Xpress")
            enable = params.get("enable", True)
            if not item_id:
                return "Qual o ID do produto?"
            cid = f"prod_shipping_{item_id}_{channel.replace(' ', '_')}".lower()
            self._confirmations[cid] = {
                "action": "set_product_shipping_channel",
                "params": {"item_id": item_id, "channel": channel, "enable": enable},
                "desc": f"{'Ativar' if enable else 'Desativar'} canal '{channel}' no produto {item_id}",
            }
            return f"🔄 Confirmar: {'ativar' if enable else 'desativar'} *{channel}* no produto *{item_id}*?\nEnvie: /confirmar {cid}"

        if intent == "set_channel_for_all_products":
            channel = params.get("channel", "Shopee Xpress")
            enable = params.get("enable", True)
            cid = f"all_prod_shipping_{channel.replace(' ', '_')}_{enable}".lower()
            self._confirmations[cid] = {
                "action": "set_channel_for_all_products",
                "params": {"channel": channel, "enable": enable},
                "desc": f"{'Ativar' if enable else 'Desativar'} canal '{channel}' em TODOS os produtos",
            }
            return f"🔄 Confirmar: {'ativar' if enable else 'desativar'} *{channel}* em *TODOS* os produtos?\n(Primeiro verificarei cada produto, so alterarei os que precisam.)\nEnvie: /confirmar {cid}"

        # --- Novos intents mapeados para SellerCenterActions ---
        if intent in ("get_shop_overview", "get_shop_health", "get_financial_summary",
                       "get_wallet_balance", "get_account_health", "get_rating_dashboard",
                       "get_todo_summary", "get_pickup_settings"):
            return self._seller_action_by_name(intent)

        if intent == "get_products":
            limit = int(params.get("limit", 10))
            return self._seller_action_by_name("get_products", limit=limit)
        if intent == "get_chat_messages":
            limit = int(params.get("limit", 10))
            return self._seller_action_by_name("get_chat_messages", limit=limit)
        if intent == "get_returns":
            limit = int(params.get("limit", 10))
            return self._seller_action_by_name("get_returns", limit=limit)
        if intent == "get_campaigns":
            limit = int(params.get("limit", 10))
            return self._seller_action_by_name("get_campaigns", limit=limit)
        if intent == "get_vouchers":
            limit = int(params.get("limit", 10))
            return self._seller_action_by_name("get_vouchers", limit=limit)
        if intent == "get_flash_sales":
            limit = int(params.get("limit", 10))
            return self._seller_action_by_name("get_flash_sales", limit=limit)
        if intent == "get_appeals":
            limit = int(params.get("limit", 10))
            return self._seller_action_by_name("get_appeals", limit=limit)

        # --- Write intents que exigem confirmacao ---
        if intent == "enable_pickup":
            enable = params.get("enable", True)
            if not isinstance(enable, bool):
                enable = str(enable).strip().lower() in ("true", "1", "sim", "yes")
            cid = f"pickup_{'on' if enable else 'off'}"
            self._confirmations[cid] = {
                "action": "enable_pickup",
                "params": {"enable": enable},
                "desc": f"{'Ativar' if enable else 'Desativar'} retirada pelo comprador",
            }
            return f"🔄 Confirmar: {'ativar' if enable else 'desativar'} *retirada pelo comprador*?\nEnvie: /confirmar {cid}"

        if intent == "reply_to_rating":
            order_id = int(params.get("order_id", 0))
            comment = params.get("comment", "Obrigado pelo feedback!")
            cid = f"rating_reply_{order_id}"
            self._confirmations[cid] = {
                "action": "reply_to_rating",
                "params": {"order_id": order_id, "comment_id": 0, "comment": comment},
                "desc": f"Responder avaliacao do pedido {order_id}: \"{comment[:50]}\"",
            }
            return f"🔄 Confirmar: responder avaliacao do pedido *{order_id}*?\nEnvie: /confirmar {cid}"

        if intent == "update_shipping_setting":
            cid = "update_shipping"
            self._confirmations[cid] = {
                "action": "update_shipping_setting",
                "params": {"kwargs": {}},
                "desc": "Atualizar configuracoes de envio",
            }
            return f"🔄 Confirmar: *atualizar configuracoes de envio*?\nEnvie: /confirmar {cid}"

        if intent == "update_shop_profile":
            cid = "update_profile"
            self._confirmations[cid] = {
                "action": "update_shop_profile",
                "params": {"kwargs": {}},
                "desc": "Atualizar perfil da loja",
            }
            return f"🔄 Confirmar: *atualizar perfil da loja*?\nEnvie: /confirmar {cid}"

        # Unknown intent
        _log(f"Unknown intent '{intent}'", "WARNING")
        known = "status, estoque, pedidos, email, financeiro, ferias, pre-venda"
        return f"Nao tenho uma acao para '{intent}'. Acoes disponiveis: {known}. Digite /help para a lista completa."

    def _execute_confirmed_action(self, data: dict[str, Any]) -> str:
        """Execute a confirmed action from _confirmations."""
        action = data.get("action", "")
        params = data.get("params", {})

        if action == "holiday_mode":
            if not self.access_token or self.shop_id is None:
                return "Shopee não configurado"
            try:
                on = params.get("on", True)
                self.client.set_shop_holiday_mode(
                    access_token=self.access_token,
                    shop_id=self.shop_id,
                    holiday_mode_on=on,
                )
                mode = "FÉRIAS" if on else "NORMAL"
                return f"✅ Loja em modo *{mode}*!"
            except Exception as e:
                return f"Erro ao alterar modo: {e}"

        if action == "pre_order_all":
            return self._execute_pre_order_all(days=params.get("days", 3))

        if action == "ship_order":
            order_sn = params.get("order_sn", "")
            if not order_sn or not self.access_token or self.shop_id is None:
                return "Dados inválidos"
            try:
                self.client.ship_order(
                    access_token=self.access_token,
                    shop_id=self.shop_id,
                    order_sn=order_sn,
                )
                return f"✅ Pedido *{order_sn}* enviado!"
            except Exception as e:
                return f"Erro ao enviar {order_sn}: {e}"

        # --- Write ops via SellerCenterActions ---
        if action in ("enable_pickup", "reply_to_rating", "update_shipping_setting", "update_shop_profile", "set_product_shipping_channel", "set_channel_for_all_products"):
            try:
                from .seller_center_actions import execute_action
                return execute_action(action, **params)
            except Exception as e:
                return f"Erro ao executar {action}: {e}"

        return f"Ação '{action}' não reconhecida"

    def _match_keywords(self, text: str) -> tuple[str, dict] | None:
        """Match user text against keyword map. Returns (intent, params) or None."""
        lower = text.lower().strip()
        import re

        # --- ship_order (must come before get_orders) ---
        if any(w in lower for w in ["enviar pedido", "ship", "enviar agor"]) and any(c.isdigit() for c in lower):
            sn = re.search(r'(\d{8,})', lower)
            if sn:
                return ("ship_order", {"order_sn": sn.group(1)})

        # --- update_shipping_setting ---
        if any(w in lower for w in ["configurar frete", "mudar frete", "alterar frete", "atualizar frete", "configuração de envio", "configuracao de envio"]):
            return ("update_shipping_setting", {"kwargs": {}})

        # --- update_shop_profile ---
        if any(w in lower for w in ["atualizar perfil", "mudar perfil", "editar perfil", "alterar perfil"]):
            return ("update_shop_profile", {"kwargs": {}})

        # --- get_rating_dashboard (must come before get_shop_overview/dashboard) ---
        if any(w in lower for w in ["dashboard de avaliação", "dashboard de avaliacao", "métrica de avaliação", "metrica de avaliacao"]):
            return ("get_rating_dashboard", {})

        # --- get_pickup_settings (must come before enable_pickup/retirada) ---
        if any(w in lower for w in ["configuração de retirada", "configuracao de retirada", "como está a retirada"]):
            return ("get_pickup_settings", {})

        # --- get_shipping_settings (must come before get_status/como está) ---
        if any(w in lower for w in ["configuração de envio", "configuracao de envio", "frete atual", "como está o frete"]):
            return ("get_shipping_settings", {})

        # --- get_appeals (must come before get_violations/penalidade) ---
        if any(w in lower for w in ["recurso", "appeal", "contestar", "recorrer"]):
            return ("get_appeals", {"limit": 10})

        # --- get_account_health ---
        if any(w in lower for w in ["saúde da conta", "saude da conta", "health"]):
            return ("get_account_health", {})

        # --- Per-product shipping channels (must come before enable_pickup/retirada) ---
        is_prod_shipping = any(w in lower for w in [
            "ativar frete no produto", "desativar frete no produto",
            "ativar envio no produto", "desativar envio no produto",
            "ativar retirada no produto", "desativar retirada no produto",
            "ativar xpress no produto", "desativar xpress no produto",
            "canal de envio do produto", "canais de envio do produto",
            "frete do produto", "envio do produto",
            "em todos os produto", "todos os meus produto",
        ])
        if is_prod_shipping:
            m = re.search(r'(?:produto|item)\s*[:\s]*(\d+)', lower)
            is_bulk = any(w in lower for w in ["em todos", "todos os", "todos meus"])
            if is_bulk:
                enable = not any(
                    re.search(r'\b' + re.escape(w) + r'\b', lower)
                    for w in ["desativar", "desligar", "tirar", "remover", "cancelar", "parar", "nao", "não", "desabilitar"]
                )
                channel = "Shopee Xpress"
                if "retirada" in lower:
                    channel = "Retirada pelo Comprador"
                elif "xpress" in lower:
                    channel = "Shopee Xpress"
                return ("set_channel_for_all_products", {"channel": channel, "enable": enable})
            if "canai" in lower or "como esta" in lower or "ver " in lower:
                if m:
                    return ("get_product_shipping_channels", {"item_id": int(m.group(1))})
                return ("get_products", {"limit": 5})
            enable = not any(
                re.search(r'\b' + re.escape(w) + r'\b', lower)
                for w in ["desativar", "desligar", "tirar", "remover", "cancelar", "parar", "nao", "não", "desabilitar"]
            )
            channel = "Shopee Xpress"
            if "retirada" in lower:
                channel = "Retirada pelo Comprador"
            elif "xpress" in lower:
                channel = "Shopee Xpress"
            if m:
                return ("set_product_shipping_channel", {"item_id": int(m.group(1)), "channel": channel, "enable": enable})
            return None

        # --- enable_pickup: ativar/desativar retirada ---
        if any(w in lower for w in ["retirada", "retirar na loja", "retirar no local", "pickup"]):
            # Use word boundary to avoid "tir" matching inside "retirada"
            enable = not any(
                re.search(r'\b' + re.escape(w) + r'\b', lower)
                for w in ["desativar", "desligar", "tirar", "remover", "cancelar", "parar", "nao", "não", "desabilitar"]
            )
            return ("enable_pickup", {"enable": enable})

        # --- reply_to_rating: responder avaliacao ---
        if any(w in lower for w in ["responder avaliação", "responder avaliacao", "responde a avaliação", "responde a avaliacao"]):
            order_match = re.search(r'(\d{8,})', lower)
            order_id = int(order_match.group(1)) if order_match else 0
            comment = "Obrigado pelo feedback!"
            for prefix in ["dizendo ", "dizendo que ", "faland ", "'", "\""]:
                if prefix in lower:
                    comment = lower.split(prefix, 1)[1].strip().rstrip("'\"")
                    break
            return ("reply_to_rating", {"order_id": order_id, "comment_id": 0, "comment": comment})

        # --- pre_order_all ---
        if any(w in lower for w in ["pré-venda", "pre-venda", "pre venda", "prazo de envio", "pré venda", "sob encomenda", "encomenda de"]):
            days = 3
            m = re.search(r'(\d+)\s*dia', lower)
            if m:
                days = int(m.group(1))
            return ("pre_order_all", {"days": days})

        # --- holiday_mode ---
        if "férias" in lower or "ferias" in lower:
            on = not any(
                re.search(r'\b' + re.escape(w) + r'\b', lower)
                for w in ["desativar", "desligar", "tirar", "sair", "remover", "cancelar", "parar", "nao", "não"]
            )
            return ("holiday_mode", {"on": on})

        # --- get_orders ---
        if any(w in lower for w in ["pedido", "orders", "compras", "vendas"]) and not any(w in lower for w in ["artigo", "produto"]):
            return ("get_orders", {"limit": 5})

        # --- get_inventory ---
        if any(w in lower for w in ["estoque baixo", "estoque crítico", "estoque critico", "sem estoque", "reabastecer"]):
            return ("get_inventory", {})
        if any(w in lower for w in ["estoque", "inventory", "inventário", "inventario"]):
            return ("get_inventory", {})

        # --- get_financial_summary ---
        if any(w in lower for w in ["financeiro", "margem", "lucro", "receita", "faturamento", "ganho"]):
            return ("get_financial_summary", {})

        # --- get_email ---
        if any(w in lower for w in ["e-mail", "email", "emails", "mensagem", "caixa de entrada"]):
            return ("get_email", {"limit": 5})

        # --- get_status ---
        if any(w in lower for w in ["status", "situação", "situacao", "como está", "como esta", "resumo"]):
            return ("get_status", {})

        # --- get_todo_summary ---
        if any(w in lower for w in ["tarefa", "pendente", "o que precisa", "o que falta", "o que fazer"]):
            return ("get_todo_summary", {})

        # --- get_help ---
        if any(w in lower for w in ["ajuda", "help", "socorro", "o que você faz", "comandos", "oque voce faz"]):
            return ("get_help", {})

        # --- get_shop_overview ---
        if any(w in lower for w in ["visão geral", "visao geral", "painel", "dashboard", "overview"]):
            return ("get_shop_overview", {})

        # --- get_products ---
        if any(w in lower for w in ["produtos", "meus produtos", "anúncios", "anuncios", "listagem"]):
            return ("get_products", {"limit": 10})

        # --- get_ratings ---
        if any(w in lower for w in ["avaliaç", "avaliac", "rating", "comentário", "comentario", "feedback", "estrela"]):
            return ("get_ratings", {"limit": 10})

        # --- get_violations ---
        if any(w in lower for w in ["violaç", "violac", "penalidade", "penalidades", "infração", "infracao", "penalty", "multa"]):
            return ("get_violations", {})

        # --- get_wallet_balance ---
        if any(w in lower for w in ["carteira", "saldo", "wallet", "quanto tenho"]):
            return ("get_wallet_balance", {})

        # --- get_chat_messages ---
        if any(w in lower for w in ["chat", "conversa", "mensagens do chat", "bate-papo"]):
            return ("get_chat_messages", {"limit": 10})

        # --- get_returns ---
        if any(w in lower for w in ["devolução", "devolucao", "devoluções", "devolucoes", "reembolso", "troca", "return"]):
            return ("get_returns", {"limit": 10})

        # --- get_campaigns ---
        if any(w in lower for w in ["campanha", "marketing", "promoção", "promocao"]):
            return ("get_campaigns", {"limit": 10})

        # --- get_vouchers ---
        if any(w in lower for w in ["cupom", "voucher", "desconto"]):
            return ("get_vouchers", {"limit": 10})

        # --- get_flash_sales ---
        if any(w in lower for w in ["flash sale", "relâmpago", "relampago"]):
            return ("get_flash_sales", {"limit": 10})

        # --- list_actions ---
        if any(w in lower for w in ["acoes", "comandos", "o que voce faz", "oque voce faz"]):
            return ("list_actions", {})

        # --- get_product_shipping_channels ---
        if any(w in lower for w in ["canal de envio do produto", "canais de envio do produto", "frete do produto", "envio do produto", "como esta o frete do produto"]):
            m = re.search(r'(?:produto|item)\s*[:\s]*(\d+)', lower)
            if m:
                return ("get_product_shipping_channels", {"item_id": int(m.group(1))})
            return ("get_products", {"limit": 5})

        # --- set_product_shipping_channel ---
        if any(w in lower for w in ["ativar frete no produto", "desativar frete no produto", "ativar envio no produto", "desativar envio no produto", "ativar retirada no produto", "desativar retirada no produto", "ativar xpress no produto", "desativar xpress no produto"]):
            m = re.search(r'(?:produto|item)\s*[:\s]*(\d+)', lower)
            enable = not any(w in lower for w in ["desativ", "deslig", "tir", "remov", "cancel", "parar", "nao", "não", "desabilit"])
            channel = "Shopee Xpress"
            if "retirada" in lower:
                channel = "Retirada pelo Comprador"
            elif "xpress" in lower or "envio" in lower or "frete" in lower:
                channel = "Shopee Xpress"
            if m:
                return ("set_product_shipping_channel", {"item_id": int(m.group(1)), "channel": channel, "enable": enable})
            return None

        return None

    def _handle_natural_language(self, text: str, chat_id: str) -> str:
        _log(f"_handle_natural_language: text={repr(text[:80])} chat={chat_id}", "DEBUG")

        # --- KEYWORD MATCHING FIRST (mais confiavel que o LLM pequeno) ---
        kw_intent = self._match_keywords(text)
        if kw_intent:
            intent, params = kw_intent
            _log(f"Keyword match on user text: '{text}' -> {intent}", "INFO")
            action_response = self._execute_intent(intent, params)
            if intent in ("search_articles", "search_products", "search_knowledge"):
                return action_response
            return f"Claro! {action_response}" if action_response else action_response

        # --- LLM como fallback ---
        ctx = _build_shop_context(self.reports_dir, seller_center=self.seller_center)
        ctx["ultimos_pedidos"] = "N/A"
        if self.access_token and self.shop_id is not None:
            try:
                now = int(datetime.now(UTC).timestamp())
                week_ago = int((datetime.now(UTC) - timedelta(days=7)).timestamp())
                resp = self.client.get_order_list(access_token=self.access_token, shop_id=self.shop_id, time_from=week_ago, time_to=now, page_size=5)
                body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
                orders = body.get("order_list", []) if isinstance(body, dict) else []
                ctx["ultimos_pedidos"] = len(orders)
            except Exception:
                pass
        result = _llm_ask_structured(text, ctx)
        if result.get("type") == "action":
            intent = result.get("intent", "")
            params = result.get("params", {})
            action_response = self._execute_intent(intent, params)
            if intent in ("search_articles", "search_products"):
                return action_response
            response = result.get("response", "")
            return f"{response}\n\n{action_response}" if response and action_response else response or action_response
        return result.get("response", "Não entendi.")

    def _handle_confirm(self, arg: str | None, chat_id: str = "") -> str:
        if not arg:
            pending = list(self._confirmations.keys())
            if not pending:
                return "Nenhuma confirmacao pendente."
            if len(pending) == 1:
                k = pending[0]
                data = self._confirmations.pop(k)
                action = data.get("action", "")
                # Long actions que podem travar o bot: executa async
                if action in ("set_channel_for_all_products",):
                    self._async_execute_action(chat_id, action, data.get("params", {}))
                    return ""
                return self._execute_confirmed_action(data)
            lines = ["*Confirmacoes pendentes:*"]
            for k in pending[:10]:
                v = self._confirmations[k]
                lines.append(f"  /confirmar {k} — {v.get('desc', k)}")
            return "\n".join(lines)
        arg = arg.strip().lower()
        if arg in self._confirmations:
            data = self._confirmations.pop(arg)
            action = data.get("action", "")
            if action in ("set_channel_for_all_products",):
                self._async_execute_action(chat_id, action, data.get("params", {}))
                return ""
            return self._execute_confirmed_action(data)
        return f"Nenhuma confirmacao pendente para '{arg}'."

    def _execute_pre_order_all(self, days: int = 3) -> str:
        if not self.access_token or self.shop_id is None:
            return "Shopee nao configurado"
        days = max(3, int(days))
        try:
            updated = 0
            offset = 0
            while True:
                resp = self.client.get_item_list(access_token=self.access_token, shop_id=self.shop_id, offset=offset, page_size=50)
                items = resp.data.get("items", resp.data.get("response", {}).get("item_list", [])) if isinstance(resp.data, dict) else []
                if not isinstance(items, list) or not items:
                    break
                for item in items:
                    item_id = item.get("item_id")
                    if item_id:
                        try:
                            self.client.update_item(
                                access_token=self.access_token,
                                shop_id=self.shop_id,
                                item_id=item_id,
                                days_to_ship=days,
                                is_pre_order=True,
                            )
                            updated += 1
                        except Exception:
                            pass
                offset += len(items)
                if len(items) < 50:
                    break
                if offset >= 2000:
                    break
            if updated == 0:
                return "Nenhum produto atualizado (lista vazia ou falha nas chamadas)."
            return f"✅ {updated} produtos agora estao sob encomenda com prazo de *{days} dia(s)* (minimo da Open API: 3)."
        except Exception as e:
            return f"Erro ao atualizar produtos: {e}"

    def handle_text(self, text: str, from_user: str, chat_id: str = "") -> str:
        raw_text = text or ""
        _log(f"handle_text: text={repr(raw_text[:50])} from={from_user} chat={chat_id}", "DEBUG")
        cmd = parse_command(text)
        if raw_text.strip().startswith("/enviar_"):
            order_sn = raw_text.strip().split()[0][len("/enviar_"):]
            if not order_sn:
                return "Uso: /enviar_<order_sn>"
            if not self.access_token or self.shop_id is None:
                return "Tokens de Shopee nao configurados para enviar pedidos"
            try:
                _ = self.client.ship_order(access_token=self.access_token, shop_id=self.shop_id, order_sn=order_sn)
                return f"Pedido {order_sn} processado para envio"
            except Exception as exc:
                return f"Falha ao enviar {order_sn}: {exc}"
        if cmd is None:
            return self._handle_natural_language(text, chat_id)
        if cmd.name in {"/start"}:
            return _render_main_menu(chat_id)
        if cmd.name in {"/help"}:
            return self._help_message()
        if cmd.name == "/menu":
            return _render_main_menu(chat_id)
        if cmd.name == "/status":
            return self._status_message()
        if cmd.name == "/pedidos":
            try:
                return self._orders_message(cmd.arg)
            except Exception as exc:
                return f"Erro em /pedidos: {exc}"
        if cmd.name == "/estoque":
            return self._inventory_message()
        if cmd.name == "/margem":
            return self._margin_message()
        if cmd.name == "/email":
            return self._email_message()
        if cmd.name == "/ferias":
            on = (cmd.arg or "").strip().lower() not in ("off", "desativar", "desligar", "sair", "nao")
            return self._execute_intent("holiday_mode", {"on": on})
        if cmd.name == "/enviar":
            order_sn = (cmd.arg or "").strip()
            if not order_sn:
                return "Uso: /enviar <order_sn>"
            return self._execute_intent("ship_order", {"order_sn": order_sn})
        if cmd.name == "/violacoes":
            return self._violations_message()
        if cmd.name == "/avaliacoes":
            return self._ratings_message()
        if cmd.name == "/configuracoes":
            return self._seller_info_message()
        if cmd.name == "/aprovar":
            return self._approval_prompt(cmd.arg)
        if cmd.name == "/confirmar":
            return self._handle_confirm(cmd.arg, chat_id)
        if cmd.name == "/artigo":
            return self._artigo_message(cmd.arg)
        if cmd.name == "/produto":
            return self._produto_message(cmd.arg)
        if cmd.name == "/categorias":
            return self._categorias_message(cmd.arg)
        if cmd.name in {"/conhecimento", "/saber"}:
            return self._conhecimento_message(cmd.arg)
        if cmd.name in {"/ensinar", "/aprender"}:
            return self._ensinar_message(cmd.arg)
        if cmd.name in {"/acoes", "/comandos"}:
            return self._list_seller_actions()
        if cmd.name in {"/ensinar_list", "/listar_acoes"}:
            return self._ensinar_list_message()
        if cmd.name in {"/esquecer", "/esquecer_acao"}:
            return self._esquecer_message(cmd.arg)
        return "Comando nao reconhecido. Use /help"

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id", "") or "")
        data = str(callback.get("data", "") or "")
        from_user_obj = callback.get("from", {}) if isinstance(callback.get("from"), dict) else {}
        from_user = str(from_user_obj.get("username") or from_user_obj.get("id") or "telegram")
        message = callback.get("message", {}) if isinstance(callback.get("message"), dict) else {}
        chat = message.get("chat", {}) if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id", "") or "")
        message_id = int(message.get("message_id", 0) or 0)

        if not callback_id:
            return

        if data.startswith("approve:"):
            case_id = data.split(":", 1)[1].strip()
            ok, msg = approve_remediation_case(case_id=case_id, reports_dir=self.reports_dir, approved_by=from_user)
            self._answer_callback(callback_id, msg if ok else f"Falha: {msg}")
            if chat_id:
                self._send_message(chat_id, msg if ok else f"Falha ao aprovar: {msg}")
            return

        if data.startswith("cancel:"):
            case_id = data.split(":", 1)[1].strip()
            self._answer_callback(callback_id, f"Cancelado {case_id}")
            if chat_id:
                self._send_message(chat_id, f"Aprovacao cancelada para {case_id}")
            return

        # Mini-app callbacks (app:...)
        if data.startswith("app:"):
            from .telegram_mini_apps import APPS
            parts = data.split(":")
            action = parts[1] if len(parts) >= 2 else ""

            if action == "voltar":
                self._edit_message(chat_id, message_id, _render_main_menu(chat_id), self._main_menu_keyboard())
                self._answer_callback(callback_id, "Menu principal")
                return

            if action == "open" and len(parts) >= 3:
                app_name = parts[2]
                app = APPS.get(app_name)
                if not app:
                    self._answer_callback(callback_id, "App nao encontrado")
                    return
                keyboard = {"inline_keyboard": app.menu()}
                self._edit_message(chat_id, message_id, _render_app_menu(app, chat_id), keyboard)
                self._answer_callback(callback_id, f"{app.emoji} {app.label}")
                return

            if len(parts) >= 3 and parts[1] in APPS:
                app_name = parts[1]
                sub_action = parts[2]
                sub_arg = ":".join(parts[3:]) if len(parts) > 3 else None
                app = APPS[app_name]
                result = app.handle(sub_action, sub_arg, client=self.client, access_token=self.access_token, shop_id=self.shop_id, reports_dir=self.reports_dir, email_manager=self.email_manager)
                self._answer_callback(callback_id, result[:100] if result else "OK")
                if chat_id:
                    self._send_message(chat_id, result)
                return

            self._answer_callback(callback_id, "Acao desconhecida")
            return

        self._answer_callback(callback_id, "Acao desconhecida")

    def _artigo_message(self, query: str | None) -> str:
        """Buscar artigos na base de conhecimento Shopee."""
        try:
            from .article_scraper import (
                count_articles_by_category,
                get_article,
                get_articles_by_category,
                search_articles,
            )
        except ImportError:
            return "Base de artigos nao disponivel (module article_scraper nao encontrado)"

        if not query:
            return (
                "Uso: `/artigo <termo>` para buscar artigos\n"
                "Uso: `/artigo id:<numero>` para ver artigo por ID\n"
                "Uso: `/artigo cat:<id>` para listar artigos de uma categoria\n"
                "Uso: `/artigo --pag N <termo>` para paginar resultados\n"
                "Ex: `/artigo avaliacao` ou `/artigo id:2787`"
            )

        q = query.strip()
        page = 0

        # Parse --pag N
        pag_match = re.match(r"--pag\s+(\d+)\s+(.+)", q)
        if pag_match:
            page = max(0, int(pag_match.group(1)) - 1)
            q = pag_match.group(2).strip()

        # Busca por categoria
        if q.lower().startswith("cat:"):
            try:
                cat_id = int(q[4:].strip())
            except ValueError:
                return "ID de categoria invalido. Use /artigo cat:1234"
            arts = get_articles_by_category(cat_id, limit=10, offset=page * 10)
            if not arts:
                return f"Nenhum artigo na categoria {cat_id}."
            total = count_articles_by_category(cat_id)
            lines = [f"📂 *Artigos da categoria* (total: {total})"]
            for a in arts:
                from datetime import datetime
                ds = datetime.fromtimestamp(a['rtime']).strftime("%d/%m/%Y") if a.get('rtime') else ""
                lines.append(f"\n• [{a['article_id']}] *{a['title']}*")
                if ds:
                    lines.append(f"  📅 {ds}")
            if total > (page + 1) * 10:
                lines.append(f"\n(mostrando {page*10+1}-{(page+1)*10} de {total})")
            return "\n".join(lines)

        # Busca por ID
        if q.lower().startswith("id:"):
            try:
                aid = int(q[3:].strip())
            except ValueError:
                return "ID invalido. Use /artigo id:1234"
            art = get_article(aid)
            if not art:
                return f"Artigo {aid} nao encontrado na base."
            raw = (art.get("content") or "")
            content = _strip_html(raw)[:2000]
            title = art.get("title", "Sem titulo")
            cat = art.get("cat_title", "")
            from datetime import datetime
            rtime = art.get("rtime", 0)
            date_str = ""
            if rtime:
                try:
                    date_str = datetime.fromtimestamp(rtime).strftime("%d/%m/%Y")
                except Exception:
                    pass
            header = f"📄 *{title}*"
            if cat:
                header += f"\n📂 {cat}"
            if date_str:
                header += f"\n📅 {date_str}"

            # Related articles from res_list
            related = ""
            try:
                res_list = json.loads(art.get("res_list", "[]"))
            except Exception:
                res_list = []
            if res_list:
                related = "\n\n📎 *Relacionados:*"
                for rl in res_list[:3]:
                    rid = rl.get("article_id", rl.get("id", ""))
                    rtitle = rl.get("title", "")
                    if rid and rtitle:
                        related += f"\n• [{rid}] {rtitle}"

            link = f"\n\n[Ler mais](https://seller.br.shopee.cn/edu/article/{aid})"
            return f"{header}\n\n{content}{related}{link}"

        # Busca full-text com paginacao
        limit = 5
        offset_val = page * limit
        results = search_articles(q, limit=limit, offset=offset_val)
        if not results:
            return f"Nenhum artigo encontrado para \"{q}\"."

        page_info = f" (pag {page+1})" if page > 0 else ""
        lines = [f"📚 *Artigos sobre \"{q}\":*{page_info}"]
        for r in results:
            title = r.get("title", "?")
            cat_name = r.get("cat_title", "")
            snippet = _strip_html(r.get("snippet") or "")[:120]
            lines.append(f"\n• *{title}*")
            if cat_name:
                lines.append(f"  📂 {cat_name}")
            if snippet:
                lines.append(f"  {snippet}")
        if len(results) == limit:
            next_page = page + 2
            lines.append(f"\nUse `/artigo --pag {next_page} {q}` para mais resultados")
        lines.append("\nUse `/artigo id:<ID>` para ver o conteudo completo")
        return "\n".join(lines)

    def _categorias_message(self, query: str | None) -> str:
        """Listar categorias ou mostrar subcategorias."""
        try:
            from .article_scraper import _get_db
        except ImportError:
            return "Base de artigos nao disponivel"

        conn = _get_db()
        q = query.strip() if query else ""

        if q.isdigit():
            # Drill-down: show subcategories + article count
            parent_id = int(q)
            children = conn.execute(
                "SELECT cat_id, name FROM categories WHERE parent_id=? ORDER BY name",
                (parent_id,),
            ).fetchall()
            parent_name = conn.execute(
                "SELECT name FROM categories WHERE cat_id=?", (parent_id,)
            ).fetchone()
            parent_label = parent_name["name"] if parent_name else str(parent_id)

            # Count articles in this category and its children
            all_ids = [parent_id] + [c["cat_id"] for c in children]
            placeholders = ",".join("?" for _ in all_ids)
            art_count = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM articles WHERE cat_id IN ({placeholders})",
                all_ids,
            ).fetchone()["cnt"]

            lines = [f"📂 *{parent_label}* ({art_count} artigos)"]
            if children:
                for c in children:
                    cnt = conn.execute(
                        "SELECT COUNT(*) AS cnt FROM articles WHERE cat_id=?", (c["cat_id"],),
                    ).fetchone()["cnt"]
                    lines.append(f"  📂 {c['name']} ({cnt}) — ID {c['cat_id']}")
                lines.append(f"\nUse `/artigo cat:{parent_id}` para listar artigos")
            else:
                lines.append(f"\nUse `/artigo cat:{parent_id}` para ver artigos")
            conn.close()
            return "\n".join(lines)

        if q:
            # Busca categorias por nome
            rows = conn.execute(
                "SELECT cat_id, name, parent_id, level FROM categories WHERE name LIKE ? ORDER BY level, name LIMIT 20",
                (f"%{q}%",),
            ).fetchall()
            if not rows:
                conn.close()
                return f"Nenhuma categoria encontrada para \"{q}\"."
        else:
            # Lista L1 (parent_id=0)
            rows = conn.execute(
                "SELECT cat_id, name, parent_id, level FROM categories WHERE parent_id=0 ORDER BY name"
            ).fetchall()

        conn.close()

        if not rows:
            return "Nenhuma categoria cadastrada."

        lines = ["📂 *Categorias de Artigos:*"]
        for r in rows:
            prefix = "  " * r["level"] if r["level"] else ""
            emoji = "📁" if r["level"] == 0 else "📂"
            lines.append(f"{prefix}{emoji} {r['name']} (ID: {r['cat_id']})")
        if not q:
            lines.append("\nUse `/categorias <id>` para ver subcategorias")
            lines.append("Use `/categorias <termo>` para buscar")
            lines.append("Use `/artigo <termo>` para buscar artigos")
        else:
            lines.append("\nUse `/categorias <id>` para drill-down")
        return "\n".join(lines)

    def _produto_message(self, query: str | None) -> str:
        """Buscar produtos na base de dados da loja."""
        try:
            from .product_scraper import get_product, get_products_by_category, search_products
        except ImportError:
            return "Base de produtos nao disponivel (rode scrape_products primeiro)"

        if not query:
            return (
                "Uso: `/produto <termo>` para buscar produtos\n"
                "Uso: `/produto id:<numero>` para ver detalhes de um produto\n"
                "Uso: `/produto cat:<categoria>` para listar produtos de uma categoria\n"
                "Ex: `/produto tenis` ou `/produto id:123456789`"
            )

        q = query.strip()

        # Busca por ID
        if q.lower().startswith("id:"):
            try:
                pid = int(q[3:].strip())
            except ValueError:
                return "ID invalido. Use /produto id:123456789"
            prod = get_product(pid)
            if not prod:
                return f"Produto {pid} nao encontrado."
            return self._format_product_detail(prod)

        # Busca por categoria
        if q.lower().startswith("cat:"):
            cat_name = q[4:].strip()
            prods = get_products_by_category(cat_name, limit=15)
            if not prods:
                return f"Nenhum produto na categoria \"{cat_name}\"."
            lines = [f"📂 *Produtos na categoria {cat_name}:*"]
            for p in prods:
                status = "🟢" if p.get("status") == "NORMAL" else "🔴"
                lines.append(
                    f"\n{status} *{p['item_name']}*"
                    f"\n  R$ {p['current_price']:.2f} | Estoque: {p['stock']}"
                    f"\n  ID: {p['item_id']}"
                )
            return "\n".join(lines)

        # Busca full-text
        results = search_products(q, limit=8)
        if not results:
            return f"Nenhum produto encontrado para \"{q}\"."

        lines = [f"🛍️ *Produtos encontrados: \"{q}\"*"]
        for r in results:
            status = "🟢" if r.get("status") == "NORMAL" else "🔴"
            price = r.get("current_price", 0)
            stock = r.get("stock", 0)
            snippet = r.get("snippet", "")[:100]
            lines.append(
                f"\n{status} *{r['item_name']}*"
                f"\n  R$ {price:.2f} | Estoque: {stock}"
            )
            if snippet:
                lines.append(f"  {snippet}")
        lines.append("\nUse `/produto id:<ID>` para ver detalhes completos")
        return "\n".join(lines)

    def _format_product_detail(self, prod: dict) -> str:
        """Format full product details for display."""
        lines = [f"📦 *{prod.get('item_name', 'Sem nome')}*"]

        # Basic info
        sku = prod.get("item_sku", "")
        status = prod.get("status", "NORMAL")
        status_emoji = "🟢" if status == "NORMAL" else "🔴"
        category = prod.get("category_name", "")
        lines.append(f"\n{status_emoji} Status: {status}")
        if sku:
            lines.append(f"🔤 SKU: {sku}")
        if category:
            lines.append(f"📂 Categoria: {category}")
        lines.append(f"🆔 ID: {prod.get('item_id')}")

        # Pricing
        price = prod.get("current_price", 0)
        original_price = prod.get("original_price", 0)
        lines.append(f"\n💰 *Preço:* R$ {price:.2f}")
        if original_price and original_price > price:
            lines.append(f"   De: R$ {original_price:.2f}")
            discount = (1 - price / original_price) * 100
            lines.append(f"   🔥 {discount:.0f}% OFF")

        # Stock
        stock = prod.get("stock", 0)
        sold = prod.get("sold", 0)
        historical_sold = prod.get("historical_sold", 0)
        lines.append(f"\n📊 *Estoque:* {stock} unidades")
        if sold:
            lines.append(f"   Vendidos: {sold}")
        if historical_sold:
            lines.append(f"   Histórico de vendas: {historical_sold}")

        # Weight & dimensions
        weight = prod.get("weight", 0)
        dim = prod.get("dimension_json", {})
        if isinstance(dim, str):
            try:
                dim = json.loads(dim)
            except Exception:
                dim = {}
        dim_info = []
        if weight:
            dim_info.append(f"{weight}kg")
        if dim:
            l, w, h = dim.get("length", 0), dim.get("width", 0), dim.get("height", 0)
            if l and w and h:
                dim_info.append(f"{l}x{w}x{h}cm")
        if dim_info:
            lines.append(f"\n📐 *Dimensões:* {' | '.join(dim_info)}")

        # Variations
        variations = prod.get("variation_json", [])
        if isinstance(variations, str):
            try:
                variations = json.loads(variations)
            except Exception:
                variations = []
        if variations:
            lines.append(f"\n🎨 *Variações ({len(variations)}):*")
            for v in variations[:10]:
                v_name = v.get("variation_name", v.get("name", "?"))
                v_price = float(v.get("current_price", v.get("price", 0)))
                v_stock = int(v.get("stock", v.get("normal_stock", 0)))
                v_sku = v.get("variation_sku", v.get("sku", ""))
                line = f"   • {v_name}"
                if v_price:
                    line += f" — R$ {v_price:.2f}"
                if v_stock:
                    line += f" ({v_stock} unid)"
                if v_sku:
                    line += f" [{v_sku}]"
                lines.append(line)

        # Attributes (characteristics)
        attributes = prod.get("attribute_json", [])
        if isinstance(attributes, str):
            try:
                attributes = json.loads(attributes)
            except Exception:
                attributes = []
        if attributes:
            lines.append("\n🏷️ *Características:*")
            for attr in attributes:
                a_name = attr.get("attribute_name", attr.get("name", "?"))
                a_value = attr.get("value", "")
                if a_name and a_value:
                    lines.append(f"   • {a_name}: {a_value}")

        # Logistics
        logistics = prod.get("logistic_json", [])
        if isinstance(logistics, str):
            try:
                logistics = json.loads(logistics)
            except Exception:
                logistics = []
        if logistics:
            lines.append("\n🚚 *Logística:*")
            for log in logistics:
                log_name = log.get("logistic_name", log.get("logistic_channel_id", "?"))
                enabled = log.get("enabled", False)
                fee = log.get("shipping_fee", 0)
                is_free = log.get("is_free", False)
                icon = "✅" if enabled else "❌"
                fee_txt = "Grátis" if is_free else (f"R$ {fee:.2f}" if fee else "")
                lines.append(f"   {icon} {log_name}" + (f" — {fee_txt}" if fee_txt else ""))

        # Description
        description = prod.get("description", "")
        if description:
            clean_desc = _strip_html(description)[:500]
            if clean_desc:
                lines.append(f"\n📝 *Descrição:*\n{clean_desc}")

        return "\n".join(lines)

    def _conhecimento_message(self, query: str | None) -> str:
        """Buscar em todo o conhecimento (blog, cursos, webinars, colecoes)."""
        try:
            from .site_scraper import search_knowledge
        except ImportError:
            return "Base de conhecimento nao disponivel (rode scrape_all_content primeiro)"

        if not query:
            return "O que voce quer aprender? Ex: /conhecimento shopee ads curso"

        results = search_knowledge(query, limit=8)
        if not results:
            return f"Nada encontrado para \"{query}\"."

        type_icons = {
            "blog": "\U0001f4dd",
            "course": "\U0001f393",
            "webinar": "\U0001f4fa",
            "collection": "\U0001f4da",
            "article": "\U0001f4d6",
        }

        lines = [f"\U0001f50d *Conhecimento: \"{query}\"*"]
        for r in results:
            ct = r.get("content_type", "?")
            icon = type_icons.get(ct, "\U0001f4cb")
            lines.append(
                f"\n{icon} *{r['title']}*"
                f"\n   Tipo: {ct} | {r.get('snippet', '')[:120]}"
            )
        return "\n".join(lines)

    def _ensinar_message(self, arg: str | None) -> str:
        """Ensinar uma nova ação à Laura."""
        from .learned_actions import learn_action, list_actions

        if not arg:
            existing = list_actions()
            if existing:
                lines = ["📚 *Ações que já aprendi:*"]
                for a in existing:
                    lines.append(f"  • {a['name']}: {a['instructions'][:80]}")
                lines.append("\nPara ensinar: `/ensinar nome_acao : instruções`")
                lines.append("Ex: `/ensinar ativar_retirada : Vá em Configurações > Frete > Retirada pelo Comprador e ative a opção.`")
                return "\n".join(lines)
            return (
                "📖 *Ensinar Laura*\n\n"
                "Use: `/ensinar nome_acao : instruções`\n"
                "Ex: `/ensinar ativar_retirada : Vá em Configurações > Frete e ative Retirada pelo Comprador`\n\n"
                "Depois é só pedir: \"ativa a retirada pelo comprador\" que eu vou lembrar!"
            )

        # Parse "nome : instruções"
        if ":" in arg:
            name, instructions = arg.split(":", 1)
            name = name.strip().lower().replace(" ", "_")
            instructions = instructions.strip()
        else:
            parts = arg.split(maxsplit=1)
            name = parts[0].strip().lower().replace(" ", "_")
            instructions = parts[1].strip() if len(parts) > 1 else ""

        if not name or not instructions:
            return "Formato: `/ensinar nome_acao : instruções`"

        learn_action(name, instructions)
        return (
            f"✅ Aprendi! Ação *{name}* registrada.\n\n"
            f"📋 {instructions}\n\n"
            f"Agora é só pedir algo como \"{name.replace('_', ' ')}\" que eu vou lembrar!"
        )

    def _ensinar_list_message(self) -> str:
        """Listar ações aprendidas."""
        from .learned_actions import list_actions

        actions = list_actions()
        if not actions:
            return "Nenhuma ação aprendida ainda. Use `/ensinar nome : instruções` para me ensinar."

        lines = ["📚 *Ações que aprendi:*"]
        for a in actions:
            instr = a.get("instructions", "").replace("\n", " ")[:120]
            count = a.get("execution_count", 0)
            lines.append(f"  • *{a['name']}* ({count}x executada)")
            lines.append(f"    {instr}")
        lines.append("\nUse `/esquecer <nome>` para remover")
        return "\n".join(lines)

    def _esquecer_message(self, arg: str | None) -> str:
        """Esquecer uma ação aprendida."""
        from .learned_actions import forget_action

        if not arg:
            return "Uso: `/esquecer <nome_acao>`"
        name = arg.strip().lower().replace(" ", "_")
        if forget_action(name):
            return f"🗑️ Ação *{name}* esquecida."
        return f"Ação *{name}* não encontrada."

    def _approval_prompt(self, case_id: str | None) -> str:
        if not case_id:
            return "Uso: /aprovar <case_id>"
        case_id = case_id.strip()
        return f"Caso {case_id} recebido. Use os botoes abaixo para aprovar ou cancelar."

    def run(self, once: bool = False) -> int:
        self._running = True
        max_retries = 3
        for attempt in range(max_retries + 1):
            if not self._running:
                return 0
            if attempt > 0:
                backoff = min(2 ** attempt * 5, 120)
                _log(f"Auto-restart attempt {attempt}/{max_retries} in {backoff}s", "WARNING")
                time.sleep(backoff)
            try:
                self._poll_loop(once)
                return 0
            except Exception as exc:
                _log(f"Bot crash (attempt {attempt}/{max_retries}): {exc}", "ERROR")
                import traceback as _tb
                _log(f"Traceback: {''.join(_tb.format_exception(type(exc), exc, exc.__traceback__))}", "ERROR")
                if not self._running:
                    return 1
                continue
        _log("Bot stopped after max retries", "CRITICAL")
        return 1

    def _poll_loop(self, once: bool = False) -> None:
        offset = self._load_offset()
        main_menu_shown = False
        while self._running:
            updates = self._get_updates(offset)
            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = int(update.get("update_id", 0) or 0)
                # Dedup: skip updates we've already processed
                if update_id in self._processed_ids:
                    offset = max(offset, update_id + 1)
                    continue
                self._processed_ids.add(update_id)
                # Keep set bounded
                if len(self._processed_ids) > 200:
                    self._processed_ids = set(list(self._processed_ids)[-100:])
                callback = update.get("callback_query", {}) if isinstance(update.get("callback_query"), dict) else {}
                if callback:
                    self._handle_callback(callback)
                    offset = max(offset, update_id + 1)
                    continue
                message = update.get("message", {}) if isinstance(update.get("message"), dict) else {}
                text = str(message.get("text", "") or "")
                chat = message.get("chat", {}) if isinstance(message.get("chat"), dict) else {}
                chat_id = str(chat.get("id", "") or "")
                from_user_obj = message.get("from", {}) if isinstance(message.get("from"), dict) else {}
                from_user = str(from_user_obj.get("username") or from_user_obj.get("id") or "telegram")
                if self.allowed_chat_id and chat_id and chat_id != self.allowed_chat_id:
                    offset = max(offset, update_id + 1)
                    continue
                if not chat_id:
                    offset = max(offset, update_id + 1)
                    continue
                # Auto-register incoming chat IDs
                if chat_id:
                    self.register_chat_id(chat_id)
                response_text = self.handle_text(text, from_user=from_user, chat_id=chat_id)

                # If response is empty, action was handled async (already sent "processing...")
                if not response_text:
                    offset = max(offset, update_id + 1)
                    continue

                cmd = parse_command(text)
                show_menu = cmd is not None and cmd.name in {"/start", "/menu"}

                if show_menu:
                    self._send_message(chat_id, response_text, self._main_menu_keyboard())
                else:
                    self._send_message(chat_id, response_text)

                offset = max(offset, update_id + 1)
                main_menu_shown = True

            self._save_offset(offset)

            if not main_menu_shown and not once:
                pass

            if once:
                return

            time.sleep(self.sleep_seconds)


# ── Narrator bridge ───────────────────────────────────────────────────────────


def _patch_narrator(bot: LauraTelegramBot) -> None:
    """Monkey-patch the global `narrador` so its methods send via the bot."""
    try:
        from .telegram_narrator import narrador


        def _patched_send(kind: str, level: str, title: str, detail: str = "") -> None:
            if not narrador._should_send(level):
                return
            emoji = _EMOJI.get(kind, "•")
            timestamp = datetime.now(UTC).strftime("%H:%M UTC")
            message = f"{emoji} *Laura* `{timestamp}`\n{title}"
            if detail:
                message += f"\n{detail}"
            bot.broadcast(message)

        narrador._send = _patched_send  # type: ignore[method-assign]
        _log("Narrator patched to use bot broadcast", "INFO")
    except ImportError:
        _log("telegram_narrator not available, skipping patch", "WARNING")
    except Exception as e:
        _log(f"Failed to patch narrator: {e}", "WARNING")


_EMOJI = {
    "pensando": "\U0001f9e0",
    "fazendo": "\u2699\ufe0f",
    "feito": "\u2705",
    "alerta": "\u26a0\ufe0f",
    "decisao": "\U0001f3af",
    "critico": "\U0001f6a8",
    "info": "\u2139\ufe0f",
    "inicio": "\U0001f680",
    "fim": "\U0001f3c1",
    "pedido": "\U0001f4e6",
    "llm": "\U0001f916",
    "webhook": "\U0001f514",
    "backup": "\U0001f4be",
    "cron": "\u23f0",
    "dinheiro": "\U0001f4b0",
}


# ── Bootstrap ─────────────────────────────────────────────────────────────────


def start_bot(token: str | None = None, client=None, daemon_mode: bool = False) -> LauraTelegramBot:
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not provided and not set in environment")

    from pathlib import Path

    reports_dir = Path(__file__).parents[1] / "reports"
    allowed_chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip() or None

    access_token = os.environ.get("SHOPEE_DEFAULT_ACCESS_TOKEN", "").strip() or None
    shop_id_env = os.environ.get("SHOPEE_DEFAULT_SHOP_ID", "").strip()
    shop_id = int(shop_id_env) if shop_id_env else None

    if client is None:
        try:
            from .client import ShopeeClient
            from .config import load_config
            cfg = load_config()
            client = ShopeeClient(cfg)
        except Exception:
            client = None

    email_manager = None
    try:
        from .email_monitor import EmailMonitor
        email_manager = EmailMonitor()
    except Exception:
        pass

    bot = LauraTelegramBot(
        token=token,
        allowed_chat_id=allowed_chat_id,
        shopee_client=client,
        access_token=access_token,
        shop_id=shop_id,
        reports_dir=reports_dir,
        email_manager=email_manager,
    )

    _patch_narrator(bot)

    if daemon_mode:
        def _run_daemon():
            bot.run()
        t = threading.Thread(target=_run_daemon, daemon=True)
        t.start()
        bot._poll_thread = t

    return bot


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser(subparsers=None) -> argparse.ArgumentParser:
    if subparsers is None:
        parser = argparse.ArgumentParser(prog="laura telegram", description="Laura Telegram Bot CLI")
        tg = parser.add_subparsers(dest="telegram_action", required=True)
    else:
        parser = subparsers.add_parser("telegram", help="Telegram bot commands")
        tg = parser.add_subparsers(dest="telegram_action", required=True)

    p_start = tg.add_parser("start", help="Start the Telegram bot (polling)")
    p_start.add_argument("--daemon", action="store_true", help="Run in background daemon thread")
    p_start.add_argument("--token", default=None, help="Bot token (default: TELEGRAM_BOT_TOKEN env)")

    p_send = tg.add_parser("send", help="Send a message to a chat")
    p_send.add_argument("--chat-id", required=True, help="Target chat ID")
    p_send.add_argument("--text", required=True, help="Message text")
    p_send.add_argument("--token", default=None, help="Bot token")

    p_broadcast = tg.add_parser("broadcast", help="Broadcast to all known chat IDs")
    p_broadcast.add_argument("--text", required=True, help="Message text")
    p_broadcast.add_argument("--token", default=None, help="Bot token")

    p_chats = tg.add_parser("chats", help="List known chat IDs")
    p_chats.add_argument("--token", default=None, help="Bot token")

    p_status = tg.add_parser("status", help="Show bot polling status")
    p_status.add_argument("--token", default=None, help="Bot token")

    return parser


def _telegram_cli() -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[2:])  # skip "laura telegram"
    action = args.telegram_action
    token = getattr(args, "token", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if action in ("send", "broadcast", "chats", "status"):
        try:
            bot = start_bot(token=token, daemon_mode=False)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    if action == "start":
        daemon = getattr(args, "daemon", False)
        if daemon:
            print("Starting bot in daemon mode (press Ctrl+C to stop)...")
            bot = start_bot(token=token, daemon_mode=True)
            try:
                while True:
                    time.sleep(10)
            except KeyboardInterrupt:
                bot.stop()
                print("\nBot stopped.")
        else:
            print("Starting bot in foreground mode...")
            bot = start_bot(token=token, daemon_mode=False)
            bot.run()
        return 0

    if action == "send":
        ok = bot.send_message(args.chat_id, args.text)
        print(json.dumps({"sent": ok, "chat_id": args.chat_id}))
        return 0 if ok else 1

    if action == "broadcast":
        count = bot.broadcast(args.text)
        print(json.dumps({"broadcast": True, "sent_to": count}))
        return 0

    if action == "chats":
        ids = bot.get_chat_ids()
        print(json.dumps({"chat_ids": ids, "count": len(ids)}, indent=2))
        return 0

    if action == "status":
        running = bot.is_running()
        print(json.dumps({"running": running, "chat_ids_count": len(bot.get_chat_ids())}, indent=2))
        return 0

    print(f"Unknown telegram action: {action}", file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "telegram":
        return _telegram_cli()
    parser = build_parser()
    parser.parse_args()
    return _telegram_cli()


if __name__ == "__main__":
    sys.exit(main())
