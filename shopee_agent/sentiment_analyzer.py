"""Analise de sentimento das avaliacoes - extrai padroes e sugestoes."""
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
SENTIMENT_FILE = REPORTS_DIR / "sentiment_analysis.json"


# Palavras-chave positivas e negativas em portugues
POSITIVE_WORDS = {
    "otimo", "excelente", "perfeito", "maravilhoso", "amei", "adorei", "rapido",
    "bom", "boa", "qualidade", "recomendo", "gostei", "nota 10", "satisfeito",
    "entrega rapida", "bem embalado", "funciona", "lindo", "material", "resistente",
}
NEGATIVE_WORDS = {
    "pessimo", "horrivel", "péssimo", "ruim", "quebrou", "quebrado", "defeito",
    "defeituoso", "veio", "errado", "nao funciona", "nao presta", "lento",
    "demorou", "atrasou", "faltou", "incompleto", "diferente", "enganado",
    "frustrado", "devolver", "devolucao", "tamanho", "pequeno", "grande",
    "cor diferente", "descascando", "soltando", "mal acabado", "fragil",
}


def analyze_sentiment(comment: str) -> tuple[str, float]:
    """Retorna (positivo/neutro/negativo, score)."""
    text = comment.lower()
    pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)
    score = pos_count - neg_count
    if score > 0:
        return "positivo", score
    elif score < 0:
        return "negativo", score
    return "neutro", 0


def extract_complaint_patterns(comments: list[str]) -> list[dict]:
    """Extrai padroes de reclamacao das avaliacoes negativas."""
    patterns: dict[str, int] = Counter()
    for c in comments:
        text = c.lower()
        # Problemas comuns em portugues
        checks = [
            (r"quebr", "produto quebrado/deformado"),
            (r"defeit", "produto com defeito"),
            (r"tamanho", "tamanho incorreto"),
            (r"atras", "atraso na entrega"),
            (r"veio (errado|incompleto|diferente)", "produto errado/incompleto"),
            (r"cor (diferente|errada)", "cor diferente do anunciado"),
            (r"nao funci", "nao funciona"),
            (r"mal acabado|acabamento", "mal acabado"),
            (r"embalagem", "embalagem danificada"),
            (r"descasc|soltando", "descascando/soltando"),
        ]
        for pattern, label in checks:
            if re.search(pattern, text):
                patterns[label] += 1

    return [{"pattern": p, "count": c} for p, c in patterns.most_common()]


def generate_suggestions(patterns: list[dict], ratings_count: int) -> list[str]:
    """Gera sugestoes de melhoria baseadas nos padroes."""
    suggestions = []
    pattern_counts = {p["pattern"]: p["count"] for p in patterns}

    total_neg = sum(p["count"] for p in patterns)
    if total_neg == 0:
        return ["Nenhum padrao de insatisfacao detectado."]

    if pattern_counts.get("produto quebrado/deformado", 0) > 2:
        suggestions.append("Melhorar embalagem - muitos produtos chegando quebrados")
    if pattern_counts.get("tamanho incorreto", 0) > 2:
        suggestions.append("Adicionar tabela de medidas mais detalhada na descricao")
    if pattern_counts.get("atraso na entrega", 0) > 2:
        suggestions.append("Revisar transportadora ou definir prazo mais realista")
    if pattern_counts.get("produto errado/incompleto", 0) > 1:
        suggestions.append("Implementar checklist de separacao antes do envio")
    if pattern_counts.get("cor diferente do anunciado", 0) > 1:
        suggestions.append("Ajustar fotos para representar cor real do produto")
    if pattern_counts.get("descascando/soltando", 0) > 1:
        suggestions.append("Revisar qualidade do material do fornecedor")

    if not suggestions:
        suggestions.append("Manter qualidade atual - sem padroes criticos de reclamacao")

    return suggestions


def analyze_ratings(seller_client) -> dict:
    """Analisa avaliacoes recentes e retorna insights."""
    try:
        ratings_data = seller_client.get_ratings(limit=200)
        ratings = ratings_data if isinstance(ratings_data, list) else ratings_data.get("ratings", [])

        total = len(ratings)
        if total == 0:
            return {"total": 0, "message": "Nenhuma avaliacao encontrada"}

        sentiment_counter: dict[str, int] = Counter()
        star_counter: dict[int, int] = Counter()
        comments_neg = []

        for r in ratings:
            stars = r.get("rating", r.get("star", 0))
            comment = r.get("comment", "")
            star_counter[stars] += 1
            sent, _ = analyze_sentiment(comment)
            sentiment_counter[sent] += 1
            if sent == "negativo" and comment:
                comments_neg.append(comment)

        patterns = extract_complaint_patterns(comments_neg) if comments_neg else []
        suggestions = generate_suggestions(patterns, total) if patterns else []

        # Media de estrelas
        avg_stars = sum(k * v for k, v in star_counter.items()) / total if total > 0 else 0

        result = {
            "total_ratings": total,
            "avg_stars": round(avg_stars, 2),
            "stars_distribution": dict(sorted(star_counter.items())),
            "sentiment": dict(sentiment_counter),
            "complaint_patterns": patterns,
            "suggestions": suggestions,
            "generated_at": datetime.now(UTC).isoformat(),
        }

        # Salvar
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        SENTIMENT_FILE.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    except Exception as e:
        return {"error": str(e)}
