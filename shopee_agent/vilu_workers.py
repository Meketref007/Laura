"""
Sistema de workers bots da ViluShop.

Cada worker posta notificacoes da sua categoria diretamente no canal.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime

import requests

COMMUNITY_CHAT_ID = os.getenv("LAURA_TELEGRAM_COMMUNITY_CHAT_ID", "").strip()
LAURA_TOKEN = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()

_BOT_TOKENS = {
    "pedidos": os.getenv("VILU_BOT_PEDIDOS_TOKEN", "").strip(),
    "estoque": os.getenv("VILU_BOT_ESTOQUE_TOKEN", "").strip(),
    "financeiro": os.getenv("VILU_BOT_FINANCEIRO_TOKEN", "").strip(),
    "marketing": os.getenv("VILU_BOT_MARKETING_TOKEN", "").strip(),
    "logistica": os.getenv("VILU_BOT_LOGISTICA_TOKEN", "").strip(),
    "atendimento": os.getenv("VILU_BOT_ATENDIMENTO_TOKEN", "").strip(),
    "sistema": LAURA_TOKEN,
}

_HEADERS = {
    "pedidos": "📦 *Pedidos*",
    "estoque": "📦 *Estoque*",
    "financeiro": "💰 *Financeiro*",
    "marketing": "📢 *Marketing*",
    "logistica": "🚚 *Logistica*",
    "atendimento": "💬 *Atendimento*",
    "sistema": "⚙️ *Sistema*",
}


def enviar_para_canal(categoria: str, mensagem: str) -> None:
    """Alias publico para _post: envia mensagem para um canal do Telegram."""
    _post(categoria, mensagem)


def _post(category: str, message: str) -> None:
    """Posta mensagem padronizada no canal usando o token da categoria."""
    token = _BOT_TOKENS.get(category) or LAURA_TOKEN
    if not token or not COMMUNITY_CHAT_ID:
        return

    header = _HEADERS.get(category, "•")
    timestamp = datetime.now(UTC).strftime("%H:%M UTC")
    full = f"{header} • `{timestamp}`\n\n{message}"

    def _send():
        session = requests.Session()
        for attempt in range(3):
            try:
                r = session.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": COMMUNITY_CHAT_ID,
                        "text": full,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
                if r.status_code == 200:
                    return
                if r.status_code == 429:
                    continue
            except Exception:
                pass

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def pedido_novo(order_sn: str, produto: str, valor: float, quantidade: int = 1, cliente: str = "") -> None:
    msg = f"🆕 *Novo Pedido*\n`{order_sn}`\n\n"
    msg += f"Produto: {produto}\n"
    msg += f"Quantidade: {quantidade}\n"
    msg += f"Valor: R$ {valor:.2f}\n"
    if cliente:
        msg += f"Cliente: {cliente}"
    _post("pedidos", msg)


def pedido_status(order_sn: str, status: str, status_br: str = "") -> None:
    status_fmt = status_br or status.replace("_", " ").title()
    msg = f"📋 *Status Atualizado*\n`{order_sn}`\n\nNovo status: {status_fmt}"
    _post("pedidos", msg)


def pedido_cancelado(order_sn: str, motivo: str = "") -> None:
    msg = f"❌ *Pedido Cancelado*\n`{order_sn}`"
    if motivo:
        msg += f"\n\nMotivo: {motivo}"
    _post("pedidos", msg)


def pedido_devolucao(order_sn: str, razao: str = "") -> None:
    msg = f"🔄 *Devolucao/Reembolso*\n`{order_sn}`"
    if razao:
        msg += f"\n\nRazao: {razao}"
    _post("pedidos", msg)


def estoque_baixo(produto: str, estoque: int, sku: str = "") -> None:
    msg = f"⚠️ *Estoque Baixo*\n\nProduto: {produto}\nEstoque atual: {estoque} unidade(s)"
    if sku:
        msg += f"\nSKU: {sku}"
    _post("estoque", msg)


def produto_sem_estoque(produto: str) -> None:
    msg = f"🚫 *Sem Estoque*\n\nProduto: {produto}\nEstoque esgotado!"
    _post("estoque", msg)


def produto_banido(produto: str, motivo: str = "") -> None:
    msg = f"⛔ *Produto Banido/Limitado*\n\nProduto: {produto}"
    if motivo:
        msg += f"\nMotivo: {motivo}"
    _post("estoque", msg)


def receita_diaria(valor: float, pedidos: int) -> None:
    msg = f"📊 *Receita do Dia*\n\nValor: R$ {valor:.2f}\nPedidos: {pedidos}"
    _post("financeiro", msg)


def custo_registrado(descricao: str, valor: float, categoria: str = "") -> None:
    msg = f"💸 *Custo Registrado*\n\nDescricao: {descricao}\nValor: R$ {valor:.2f}"
    if categoria:
        msg += f"\nCategoria: {categoria}"
    _post("financeiro", msg)


def margem_atualizada(produto: str, margem: float, anterior: float | None = None) -> None:
    msg = f"📈 *Margem Atualizada*\n\nProduto: {produto}\nMargem atual: {margem:.1f}%"
    if anterior is not None:
        diff = margem - anterior
        sinal = "+" if diff > 0 else ""
        msg += f" ({sinal}{diff:.1f}%)"
    _post("financeiro", msg)


def promocao_iniciada(nome: str, tipo: str, desconto: str = "") -> None:
    msg = f"🎉 *Promocao Ativa*\n\n{nome} ({tipo})"
    if desconto:
        msg += f"\nDesconto: {desconto}"
    _post("marketing", msg)


def campanha_ads_resultado(campanha: str, impressoes: int, cliques: int, gasto: float) -> None:
    msg = f"📣 *Resultado de Ads*\n\nCampanha: {campanha}\n"
    msg += f"Impressoes: {impressoes:,}\nCliques: {cliques:,}\n"
    msg += f"Gasto: R$ {gasto:.2f}"
    _post("marketing", msg)


def envio_atualizado(order_sn: str, status: str, transportadora: str = "") -> None:
    msg = f"📬 *Envio Atualizado*\n`{order_sn}`\n\nStatus: {status}"
    if transportadora:
        msg += f"\nTransportadora: {transportadora}"
    _post("logistica", msg)


def envio_processado(order_sn: str) -> None:
    msg = f"✅ *Pedido Processado*\n`{order_sn}`\n\nPedido pronto para envio!"
    _post("logistica", msg)


def avaliacao_recebida(produto: str, nota: float, comentario: str = "") -> None:
    msg = f"⭐ *Nova Avaliacao*\n\nProduto: {produto}\nNota: {'⭐' * int(round(nota))} ({nota}/5)"
    if comentario:
        msg += f"\n\nComentario: {comentario[:200]}"
    _post("atendimento", msg)


def disputa_aberta(return_sn: str, motivo: str = "") -> None:
    msg = f"⚖️ *Disputa Aberta*\n`{return_sn}`"
    if motivo:
        msg += f"\n\nMotivo: {motivo}"
    _post("atendimento", msg)


def chat_nova_mensagem(comprador: str, preview: str = "", intent: str = "") -> None:
    msg = f"💬 *Nova Mensagem*\n\nDe: {comprador}"
    if intent:
        msg += f"\nAssunto: {intent}"
    if preview:
        msg += f"\n\n_{preview[:200]}_"
    _post("atendimento", msg)


def chat_auto_respondida(comprador: str, intent: str, confianca: float) -> None:
    msg = f"🤖 *Resposta Automatica Enviada*\n\nPara: {comprador}\nAssunto: {intent}\nConfianca: {int(confianca * 100)}%"
    _post("atendimento", msg)


def chat_precisa_ajuda(comprador: str, intent: str, motivo: str = "") -> None:
    msg = f"🔴 *Precisa de Atencao!*\n\nCliente: {comprador}\nAssunto: {intent}"
    if motivo:
        msg += f"\n{motivo}"
    msg += "\n\n👉 Responda manualmente na Central do Vendedor"
    _post("atendimento", msg)


def testar() -> list:
    """Envia mensagem de teste de cada categoria no canal."""
    results = []
    for category in ("pedidos", "estoque", "financeiro", "marketing", "logistica", "atendimento"):
        try:
            _post(category, f"✅ Sistema de notificacoes ativo!\nCategoria *{category}* operacional.")
            results.append(f"{category}: OK")
        except Exception as e:
            results.append(f"{category}: {e}")
    return results
