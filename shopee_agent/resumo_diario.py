"""
Resumo diario automatico da ViluShop.

Posta no canal viluhshop todo dia um resumo com:
- Faturamento do dia
- Pedidos recebidos
- Produtos com estoque baixo
- Cancelamentos/devolucoes
- Situacao geral da loja
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

HORARIO_POST = int(os.getenv("VILU_RESUMO_HORARIO", "21"))  # 21h


def _gerar_analise_llm(faturamento: float, pedidos: int, cancelados: int, baixo_estoque: list[str]) -> str:
    """Gera paragrafo de analise via LLM local."""
    try:
        import requests as _req
        host = os.getenv("LAURA_OLLAMA_HOST", "http://127.0.0.1:11434")
        model = os.getenv("LAURA_LLM_MODEL", "qwen2.5:7b")
        prompt = (
            "Voce e Laura, analista da loja ViluShop na Shopee. "
            "Com base nos dados abaixo, escreva UM paragrafo curto e direto analisando o desempenho do dia. "
            "Seja honesta, mencione pontos positivos e negativos. Maximo 3 frases.\n\n"
            f"Dados do dia:\n- Pedidos: {pedidos}\n- Faturamento: R$ {faturamento:.2f}\n"
            f"- Cancelamentos: {cancelados}\n- Itens com estoque baixo: {len(baixo_estoque)}\n\n"
            "Analise:"
        )
        resp = _req.post(f"{host}/api/generate", json={"model": model, "prompt": prompt, "stream": False}, timeout=30)
        if resp.status_code == 200:
            texto = resp.json().get("response", "").strip()
            return texto[:500]
    except Exception:
        pass
    return ""


def gerar_resumo(client, access_token: str, shop_id: int) -> str:
    """Gera texto do resumo diario."""
    agora = datetime.now(UTC) - timedelta(hours=3)  # BRT
    data_br = agora.strftime("%d/%m/%Y")
    inicio = int((agora - timedelta(days=1)).timestamp())
    fim = int(agora.timestamp())

    faturamento = 0.0
    pedidos_count = 0
    cancelados = 0
    baixo_estoque = []

    try:
        resp = client.get_order_list(
            access_token=access_token, shop_id=shop_id,
            time_from=inicio, time_to=fim, page_size=100,
        )
        orders = []
        if resp and hasattr(resp, "data"):
            orders = resp.data.get("order_list", []) if isinstance(resp.data, dict) else []
        for o in (orders or []):
            pedidos_count += 1
            status = str(o.get("order_status", ""))
            if status == "CANCELLED":
                cancelados += 1
            try:
                faturamento += float(o.get("total_amount", 0) or 0) / 100000
            except Exception:
                pass
    except Exception:
        pass

    try:
        resp2 = client.get_item_list(
            access_token=access_token, shop_id=shop_id,
            offset=0, page_size=100,
        )
        items = []
        if resp2 and hasattr(resp2, "data"):
            items = resp2.data.get("item", []) if isinstance(resp2.data, dict) else []
            if not items:
                items = resp2.data.get("item_list", [])
        for it in (items or []):
            try:
                stock = int(it.get("stock", 0) or 0)
            except Exception:
                stock = 0
            if 0 < stock <= 5:
                nome = (it.get("item_name", "") or "")[:40]
                baixo_estoque.append(f"{nome} ({stock} un)")
            elif stock == 0:
                nome = (it.get("item_name", "") or "")[:40]
                baixo_estoque.append(f"{nome} (ESGOTADO)")
    except Exception:
        pass

    analise_llm = _gerar_analise_llm(faturamento, pedidos_count, cancelados, baixo_estoque)

    linhas = [
        f"📊 *Resumo Diario - {data_br}*",
        "",
    ]

    if analise_llm:
        linhas.append(f"🤖 *Analise:* {analise_llm}")
        linhas.append("")

    if pedidos_count > 0:
        linhas.append(f"📦 *Pedidos:* {pedidos_count}")
        linhas.append(f"💰 *Faturamento:* R$ {faturamento:.2f}")
        if cancelados > 0:
            linhas.append(f"❌ *Cancelados:* {cancelados}")
        linhas.append("")
    else:
        linhas.append("📦 Nenhum pedido no periodo")
        linhas.append("")

    if baixo_estoque:
        linhas.append("⚠️ *Estoque Baixo:*")
        for p in baixo_estoque[:5]:
            linhas.append(f"  - {p}")
        linhas.append("")

    if faturamento > 0:
        meta_diaria = float(os.getenv("VILU_META_DIARIA", "500"))
        if faturamento >= meta_diaria:
            status = "✅ *Meta atingida!*"
        else:
            pct = (faturamento / meta_diaria) * 100
            status = f"⚠️ *{pct:.0f}% da meta* (R$ {meta_diaria:.2f}/dia)"
        linhas.append(f"🎯 {status}")

    return "\n".join(linhas)


def deve_postar_agora() -> bool:
    """Verifica se esta na hora de postar o resumo."""
    agora = datetime.now(UTC) - timedelta(hours=3)
    return agora.hour == HORARIO_POST


def postar_resumo(client, access_token, shop_id):
    """Gera e posta o resumo no canal."""
    from .vilu_workers import _post
    texto = gerar_resumo(client, access_token, shop_id)
    _post("financeiro", texto)
