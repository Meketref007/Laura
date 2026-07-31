"""Natural language goal input — LLM translates text to GOAP goal_state."""

from __future__ import annotations

import json
from typing import Any

from shopee_agent.logger import warning

_GOAL_KEYWORDS: dict[str, dict[str, Any]] = {
    "aumentar margem": {"margin_protected": True},
    "proteger margem": {"margin_protected": True},
    "margem baixa": {"margin_protected": True},
    "lucro": {"margin_protected": True},
    "estoque": {"stock_checked": True},
    "repor estoque": {"stock_checked": True},
    "inventory": {"stock_checked": True},
    "reembolso": {"losses_reduced": True},
    "perda": {"losses_reduced": True},
    "refund": {"losses_reduced": True},
    "preço": {"prices_optimized": True},
    "preco": {"prices_optimized": True},
    "reprecificar": {"prices_optimized": True},
    "suporte": {"support_handled": True},
    "atendimento": {"support_handled": True},
    "cliente": {"support_handled": True},
    "tudo": {"margin_protected": True, "stock_checked": True, "prices_optimized": True, "support_handled": True},
    "completo": {"margin_protected": True, "stock_checked": True, "prices_optimized": True, "support_handled": True},
    "full": {"margin_protected": True, "stock_checked": True, "prices_optimized": True, "support_handled": True},
    "monitorar": {"monitor_ok": True},
    "monitor": {"monitor_ok": True},
    "normal": {"monitor_ok": True},
}


def synthesize_from_text(text: str) -> dict[str, Any]:
    """Translate a natural language goal description into a GOAP goal_state dict.

    Uses keyword matching + fuzzy scoring. Can be extended to use LLM.
    """
    text_lower = text.lower().strip()

    # Explicit keyword match (highest priority)
    for keyword, goal in sorted(_GOAL_KEYWORDS.items(), key=lambda x: -len(x[0])):
        if keyword in text_lower:
            return dict(goal)

    # Fallback: extract goal-related words
    goal: dict[str, Any] = {}

    margin_words = {"margem", "margin", "lucro", "profit", "preço", "preco", "reprecificar"}
    stock_words = {"estoque", "stock", "inventory", "repor"}
    loss_words = {"perda", "loss", "reembolso", "refund", "chargeback"}
    support_words = {"suporte", "support", "atendimento", "cliente", "ticket", "reclamac"}
    monitor_words = {"monitorar", "monitor", "observar", "normal", "nada", "ok"}

    if any(w in text_lower for w in margin_words):
        goal["margin_protected"] = True
    if any(w in text_lower for w in stock_words):
        goal["stock_checked"] = True
    if any(w in text_lower for w in loss_words):
        goal["losses_reduced"] = True
    if any(w in text_lower for w in support_words):
        goal["support_handled"] = True
    if not goal or any(w in text_lower for w in monitor_words):
        goal["monitor_ok"] = True

    return goal


def synthesize_with_llm(text: str, llm_func: Any | None = None) -> dict[str, Any]:
    """Translate text using an LLM function. Falls back to keyword matching.

    llm_func should be a callable that accepts a prompt string and returns a JSON string.
    """
    if llm_func is None:
        return synthesize_from_text(text)

    prompt = f"""Given the user request: "{text}"

Return a JSON object representing the GOAP goal state. Examples:
- "aumentar margem" -> {{"margin_protected": true}}
- "repor estoque" -> {{"stock_checked": true}}
- "tudo" -> {{"margin_protected": true, "stock_checked": true, "prices_optimized": true}}

Return ONLY valid JSON with boolean values."""
    try:
        raw = llm_func(prompt)
        raw_clean = raw.strip().strip("```json").strip("```").strip()
        parsed = json.loads(raw_clean)
        if isinstance(parsed, dict):
            return {k: bool(v) for k, v in parsed.items()}
    except Exception as exc:
        warning(f"LLM goal synthesis failed, falling back to keywords: {exc}")
    return synthesize_from_text(text)
