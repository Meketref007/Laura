"""
Auto-reply para avaliacoes da loja via Seller Center API.
Gera respostas contextuais usando Ollama e envia via API v3.

Por seguranca, por padrao as respostas sao enfileiradas para revisao humana.
Defina RATING_REPLY_AUTO_SEND=1 no .env para enviar automaticamente.
"""
import json
import os
import time
from datetime import UTC, datetime

import requests

from shopee_agent.logger import error as log_error
from shopee_agent.logger import info, warning
from shopee_agent.paths import REPLIED_RATINGS
from shopee_agent.seller_center import SellerCenterClient
from shopee_agent.vilu_workers import enviar_para_canal

_REPLIED_FILE = str(REPLIED_RATINGS)
_PENDING_FILE = "reports/rating_replies_pending.jsonl"

_AUTO_SEND = os.getenv("RATING_REPLY_AUTO_SEND", "0") == "1"


def _load_replied() -> set[int]:
    try:
        if os.path.exists(_REPLIED_FILE):
            data = json.loads(open(_REPLIED_FILE, encoding="utf-8").read())
            return set(data.get("replied_ids", []))
    except Exception:
        pass
    return set()


def _save_replied(ids: set[int]) -> None:
    try:
        os.makedirs(os.path.dirname(_REPLIED_FILE) or ".", exist_ok=True)
        with open(_REPLIED_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps({"replied_ids": sorted(ids)}, ensure_ascii=False))
    except Exception as e:
        warning(f"Failed to save replied ratings: {e}")


def _gerar_resposta(rating_star: int, comment: str, product_name: str) -> str:
    """Gera resposta contextual. Tenta Ollama, fallback para templates."""
    fallbacks = {
        5: f"Obrigado pela avaliacao! Ficamos muito felizes que voce gostou do {product_name or 'produto'}. Volte sempre!",
        4: "Obrigado pela avaliacao! Estamos sempre melhorando para atender cada vez melhor.",
        3: "Obrigado pelo feedback! Vamos usar sua opiniao para melhorar nossos produtos e servicos.",
        2: "Obrigado pelo feedback. Lamentamos que sua experiencia nao tenha sido a melhor. Conte conosco para resolver qualquer questao.",
        1: "Obrigado pelo feedback. Sentimos muito por nao ter atendido suas expectativas. Entre em contato conosco para que possamos ajudar.",
    }
    if os.getenv("LAURA_RATING_LLM", "0") == "1":
        try:
            prompt = (
                f"Produto: {product_name}\nNota: {rating_star}/5\nComentario: {comment or '-'}\n\n"
                f"Resposta curta (max 150 chars, portugues, cordial, sem emojis):"
            )
            model = os.getenv("LAURA_LLM_MODEL", "qwen2.5:7b")
            host = os.getenv("LAURA_OLLAMA_HOST", "http://127.0.0.1:11434")
            resp = requests.post(f"{host}/api/generate", json={"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": 80}}, timeout=15)
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip().strip('"').strip()
                if text:
                    return text
        except Exception:
            pass
    return fallbacks.get(rating_star, fallbacks[3])


def processar_avaliacoes_pendentes() -> dict:
    """
    Busca avaliacoes pendentes e gera respostas via LLM.

    Se RATING_REPLY_AUTO_SEND=1, envia automaticamente (perigoso).
    Se RATING_REPLY_AUTO_SEND=0 (padrao), enfileira para revisao humana via Telegram.
    Retorna stats: {processadas, respondidas, erros, ignoradas, pendentes}
    """
    client = SellerCenterClient()
    if not client.is_authenticated():
        log_error("Seller Center nao autenticado")
        return {"error": "not_authenticated"}

    stats = {"processadas": 0, "respondidas": 0, "erros": 0, "ignoradas": 0, "pendentes": 0}
    ja_respondidas = _load_replied()
    cursor = 0

    for page in range(1, 11):
        comments = client.get_rating_comments(page=page, page_size=50, cursor=cursor)
        if not comments:
            break

        for item in comments:
            stats["processadas"] += 1
            cid = item["comment_id"]

            if cid in ja_respondidas:
                stats["ignoradas"] += 1
                continue

            if item.get("reply") is not None:
                ja_respondidas.add(cid)
                stats["ignoradas"] += 1
                continue

            # Avaliacoes negativas (< 3 estrelas) SEMPRE vao para fila de revisao
            rating_star = item["rating_star"]
            if rating_star < 3 and _AUTO_SEND:
                _enfileirar_resposta(item)
                stats["pendentes"] += 1
                info(f"Avaliacao negativa {cid} estrela {rating_star} enfileirada para revisao")
                continue

            resposta = _gerar_resposta(
                rating_star=rating_star,
                comment=item.get("comment") or "",
                product_name=item.get("product_name", ""),
            )

            if _AUTO_SEND:
                success = client.reply_to_rating(
                    order_id=item["order_id"],
                    comment_id=cid,
                    comment=resposta,
                )
                if success:
                    ja_respondidas.add(cid)
                    stats["respondidas"] += 1
                    info(f"Respondida avaliacao {cid}: {resposta[:60]}")
                else:
                    stats["erros"] += 1
                    warning(f"Falha ao responder avaliacao {cid}")
            else:
                _enfileirar_resposta(item, resposta)
                stats["pendentes"] += 1
                info(f"Avaliacao {cid} enfileirada para revisao")

            time.sleep(0.3)

        cursor = comments[-1].get("comment_id", cursor)

    _save_replied(ja_respondidas)

    if stats["respondidas"] > 0:
        msg = f"🤖 *Auto-resposta de Avaliacoes*\n{stats['respondidas']} respondidas, {stats['erros']} erros, {stats['ignoradas']} ja processadas"
        enviar_para_canal("sistema", msg)
    elif stats["pendentes"] > 0:
        msg = f"⏳ *Avaliacoes Pendentes*\n{stats['pendentes']} aguardando revisao. Use /revisar_avaliacoes para aprovar."
        enviar_para_canal("sistema", msg)

    return stats


def _enfileirar_resposta(item: dict, resposta_generica: str = "") -> None:
    """Enfileira uma avaliacao pendente para revisao humana."""
    import json as _json
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "order_id": item["order_id"],
        "comment_id": item["comment_id"],
        "rating_star": item["rating_star"],
        "comment": item.get("comment", ""),
        "product_name": item.get("product_name", ""),
        "suggested_reply": resposta_generica or _gerar_resposta(
            item["rating_star"], item.get("comment", ""), item.get("product_name", ""),
        ),
        "status": "pending",
    }
    try:
        os.makedirs(os.path.dirname(_PENDING_FILE) or ".", exist_ok=True)
        with open(_PENDING_FILE, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        warning(f"Falha ao enfileirar avaliacao: {e}")


def processar_fila_pendentes(aprovar_ids: list[int] | None = None) -> dict:
    """
    Processa a fila de avaliacoes pendentes.
    Se aprovar_ids for None, lista as pendentes.
    Se aprovar_ids for uma lista, envia as aprovadas.
    """
    client = SellerCenterClient()
    if not client.is_authenticated():
        return {"error": "not_authenticated"}

    if not os.path.exists(_PENDING_FILE):
        return {"pendentes": 0, "mensagem": "Nenhuma avaliacao pendente."}

    linhas = []
    with open(_PENDING_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    linhas.append(json.loads(line))
                except Exception:
                    pass

    if aprovar_ids is None:
        pendentes = [e for e in linhas if e.get("status") == "pending"]
        return {
            "pendentes": len(pendentes),
            "itens": [{"id": e["comment_id"], "produto": e["product_name"], "nota": e["rating_star"], "comentario": e["comment"][:100], "resposta": e["suggested_reply"][:100]} for e in pendentes[:20]],
        }

    stats = {"aprovadas": 0, "erros": 0}
    ja_respondidas = _load_replied()
    aprovar_set = set(aprovar_ids)
    restantes = []

    for entry in linhas:
        cid = entry["comment_id"]
        if cid in aprovar_set and entry.get("status") == "pending":
            success = client.reply_to_rating(
                order_id=entry["order_id"],
                comment_id=cid,
                comment=entry["suggested_reply"],
            )
            if success:
                ja_respondidas.add(cid)
                stats["aprovadas"] += 1
                info(f"Avaliacao {cid} aprovada e enviada")
            else:
                stats["erros"] += 1
                warning(f"Falha ao enviar avaliacao {cid} aprovada")
                restantes.append(entry)
        else:
            restantes.append(entry)

    _save_replied(ja_respondidas)

    # Reescrever arquivo com nao processadas
    with open(_PENDING_FILE, "w", encoding="utf-8") as f:
        for entry in restantes:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if stats["aprovadas"] > 0:
        enviar_para_canal("sistema", f"✅ {stats['aprovadas']} avaliacoes aprovadas e enviadas, {stats['erros']} erros")

    return stats
