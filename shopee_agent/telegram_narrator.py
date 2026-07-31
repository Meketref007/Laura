"""
Narração opcional para Telegram dos eventos operacionais da Laura.

Este módulo é propositalmente isolado do logger central para evitar
duplicar o fluxo de logs: ele só envia mensagens quando a narração estiver
explicitamente habilitada no ambiente.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime

import requests

_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "CRITICAL": 3}
_EMOJI = {
    "pensando": "🧠",
    "fazendo": "⚙️",
    "feito": "✅",
    "alerta": "⚠️",
    "decisao": "🎯",
    "critico": "🚨",
    "info": "ℹ️",
    "inicio": "🚀",
    "fim": "🏁",
    "pedido": "📦",
    "llm": "🤖",
    "webhook": "🔔",
    "backup": "💾",
    "cron": "⏰",
    "dinheiro": "💰",
}


def _friendly_order_status(status: object) -> str:
    raw = str(status or "").strip()
    if not raw:
        return "não informado"

    normalized = raw.upper()
    labels = {
        "READY_TO_SHIP": "pronto para envio",
        "UNPAID": "aguardando pagamento",
        "PROCESSED": "em processamento",
        "SHIPPED": "enviado",
        "COMPLETED": "concluído",
        "TO_CONFIRM_RECEIVE": "aguardando confirmação de recebimento",
        "CANCELLED": "cancelado",
        "IN_CANCEL": "cancelamento em andamento",
        "INCOMPLETED": "incompleto",
        "TO_RETURN": "devolução em andamento",
    }
    return labels.get(normalized, raw.replace("_", " ").strip().lower())


class LauraTelegramNarrator:
    def __init__(self) -> None:
        self._token = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
        self._chat_id = os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip()
        self._community_chat_id = os.getenv("LAURA_TELEGRAM_COMMUNITY_CHAT_ID", "").strip()
        self._enabled = os.getenv("LAURA_TELEGRAM_NARRATOR", "0").strip().lower() in {"1", "true", "yes", "on"}
        level_name = os.getenv("LAURA_TELEGRAM_NARRATOR_LEVEL", "INFO").strip().upper()
        self._min_level = _LEVELS.get(level_name, _LEVELS["INFO"])
        self._lock = threading.Lock()
        self._session = requests.Session()
        # rate-limiting for noisy events: map key -> last sent timestamp
        self._last_sent: dict[str, float] = {}

    def _should_send(self, level: str) -> bool:
        if not self._enabled or not self._token or not self._chat_id:
            return False
        return _LEVELS.get(level, _LEVELS["INFO"]) >= self._min_level

    def _send(self, kind: str, level: str, title: str, detail: str = "") -> None:
        if not self._should_send(level):
            return

        emoji = _EMOJI.get(kind, "•")
        timestamp = datetime.now(UTC).strftime("%H:%M UTC")
        message = f"{emoji} *Laura* `{timestamp}`\n{title}"
        if detail:
            message += f"\n{detail}"

        thread = threading.Thread(target=self._post_message, args=(message,), daemon=True)
        thread.start()

    def _post_message(self, message: str, attempts: int = 3) -> None:
        targets = [self._chat_id]
        if self._community_chat_id:
            targets.append(self._community_chat_id)
        for target in targets:
            for attempt in range(attempts):
                try:
                    response = self._session.post(
                        f"https://api.telegram.org/bot{self._token}/sendMessage",
                        json={
                            "chat_id": target,
                            "text": message,
                            "parse_mode": "Markdown",
                            "disable_web_page_preview": True,
                        },
                        timeout=8,
                    )
                    if response.status_code == 200:
                        break
                    if response.status_code == 429:
                        continue
                except Exception:
                    pass

    def pensando(self, texto: str, detalhe: str = "") -> None:
        self._send("pensando", "INFO", texto, detalhe)

    def fazendo(self, texto: str, detalhe: str = "") -> None:
        self._send("fazendo", "INFO", texto, detalhe)

    def feito(self, texto: str, detalhe: str = "") -> None:
        self._send("feito", "INFO", texto, detalhe)

    def alerta(self, texto: str, detalhe: str = "") -> None:
        self._send("alerta", "WARNING", texto, detalhe)

    def decisao(self, acao: str, raciocinio: str = "", confianca: float = 0.0, fallback: bool = False) -> None:
        status = "fallback heurístico" if fallback else "modelo ativo"
        detalhe = f"{status} | confiança {int(max(confianca, 0.0) * 100)}%"
        if raciocinio:
            detalhe += f"\n💭 _{raciocinio[:300]}{'...' if len(raciocinio) > 300 else ''}_"
        self._send("decisao", "INFO", f"Decisão: *{acao}*", detalhe)

    def critico(self, texto: str, detalhe: str = "") -> None:
        self._send("critico", "CRITICAL", texto, detalhe)

    def info(self, texto: str, detalhe: str = "") -> None:
        self._send("info", "INFO", texto, detalhe)

    def inicio_ciclo(self, nome: str, detalhe: str = "") -> None:
        self._send("inicio", "INFO", f"*{nome}* iniciado", detalhe)

    def fim_ciclo(self, nome: str, detalhe: str = "") -> None:
        self._send("fim", "INFO", f"*{nome}* concluído", detalhe)

    def novo_pedido(
        self,
        order_sn: str,
        valor: float = 0.0,
        *,
        status: str | None = None,
        buyer: str | None = None,
        product: str | None = None,
        quantity: object | None = None,
    ) -> None:
        detalhe_linhas = []
        if product:
            detalhe_linhas.append(f"Produto: {product}")
        if quantity not in (None, "", 0, "0"):
            detalhe_linhas.append(f"Quantidade: {quantity}")
        if buyer:
            detalhe_linhas.append(f"Cliente: {buyer}")
        if status:
            detalhe_linhas.append(f"Situação: {_friendly_order_status(status)}")
        if valor > 0:
            detalhe_linhas.append(f"Valor estimado: R$ {valor:.2f}")

        detalhe = "\n".join(detalhe_linhas)
        title = f"Pedido recebido: `{order_sn}`"
        self._send("pedido", "INFO", title, detalhe)

    def llm_resultado(
        self,
        modelo: str,
        decisao: str,
        confianca: float,
        raciocinio: str = "",
        fallback: bool = False,
    ) -> None:
        status = "fallback heurístico" if fallback else f"modelo `{modelo}`"
        detalhe = f"{int(max(confianca, 0.0) * 100)}% confiança via {status}"
        if raciocinio:
            detalhe += f"\n\n💭 _{raciocinio[:300]}{'...' if len(raciocinio) > 300 else ''}_"
        self._send("llm", "INFO", f"LLM → *{decisao}*", detalhe)

    def webhook_evento(self, tipo: str, detalhe: str = "", source: str | None = None, valid: bool = True) -> None:
        # Backwards-compatible signature: allow callers to pass source and valid as keywords
        # Example: webhook_evento(tipo, detalhe, source=<src>, valid=<bool>)
        # We implement basic filtering and rate-limiting here to avoid Telegram spam.
        # Accept optional attributes passed as part of detalhe if callers don't use keywords.
        # For safety, inspect environment override for cooldown.
        try:
            # If caller passed additional kwargs via position, they will be ignored here;
            # higher-level callers should pass `source` and `valid` by keyword.
            source = None
            valid = True
        except Exception:
            source = None
            valid = True

        # If detalhe encodes source like "Fonte: `shopee` ...", try to extract it (best-effort)
        if detalhe and "Fonte: `" in detalhe:
            try:
                start = detalhe.index("Fonte: `") + len("Fonte: `")
                end = detalhe.index("`", start)
                source = detalhe[start:end]
            except Exception:
                pass

        # Basic filters: suppress generic/unknown noisy events
        noisy_types = {"unknown", "shopee_updates"}
        if tipo in noisy_types:
            return

        # If signature invalid (valid==False) don't notify for non-critical types
        if not valid:
            critical = {"shopee.order_created", "shopee.buyer_rating", "shopee.order_cancelled"}
            if tipo not in critical:
                return

        # Rate-limit by (tipo, source)
        key = f"{tipo}|{source or ''}"
        cooldown = int(os.getenv("LAURA_TELEGRAM_WEBHOOK_COOLDOWN", "300"))
        now = time.time()
        last = self._last_sent.get(key)
        if last and (now - last) < cooldown:
            return
        self._last_sent[key] = now

        self._send("webhook", "INFO", f"Webhook: *{tipo}*", detalhe)

    def backup_feito(self, arquivo: str) -> None:
        self._send("backup", "INFO", "Backup concluído", arquivo)

    def testar(self) -> bool:
        if not self._token or not self._chat_id:
            print("ERRO: LAURA_ALERT_TELEGRAM_BOT_TOKEN ou LAURA_ALERT_TELEGRAM_CHAT_ID ausentes no .env")
            return False

        try:
            response = self._session.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": "🚀 *Laura* conectada ao Telegram!\nNarração em tempo real ativada.",
                    "parse_mode": "Markdown",
                },
                timeout=8,
            )
            ok = response.status_code == 200
            if ok:
                print("✅ Telegram OK")
            else:
                print(f"❌ Telegram erro {response.status_code}: {response.text}")
            return ok
        except Exception as exc:
            print(f"❌ Telegram falhou: {exc}")
            return False


narrador = LauraTelegramNarrator()
