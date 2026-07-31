"""Goal Library — pre-built goal templates for common Shopee scenarios."""

from __future__ import annotations

from typing import Any

GoalTemplate = dict[str, Any]


GOAL_LIBRARY: list[dict[str, Any]] = [
    {
        "id": "protect_margin",
        "title": "Proteger margem de lucro",
        "description": "Garantir que a margem minima seja mantida em todos os produtos",
        "tags": ["margin", "pricing", "core"],
        "goal_state": {"margin_protected": True},
        "suggested_skills": ["protect_margin", "check_pricing"],
        "priority": 10,
    },
    {
        "id": "clear_inventory",
        "title": "Limpar estoque parado",
        "description": "Produtos com mais de 60 dias em estoque devem ser marcados para promocao",
        "tags": ["inventory", "clearance"],
        "goal_state": {"stock_checked": True, "excess_cleared": True},
        "suggested_skills": ["low_stock_alert", "clear_excess_stock"],
        "priority": 8,
    },
    {
        "id": "fulfill_orders",
        "title": "Processar pedidos pendentes",
        "description": "Enviar todos os pedidos que estao aguardando expedicao",
        "tags": ["orders", "fulfillment", "core"],
        "goal_state": {"orders_pending_ship": False},
        "suggested_skills": ["order_ship", "update_tracking"],
        "priority": 9,
    },
    {
        "id": "handle_support",
        "title": "Atender suporte ao cliente",
        "description": "Responder todas as mensagens de clientes pendentes",
        "tags": ["support", "customer"],
        "goal_state": {"support_handled": True},
        "suggested_skills": ["auto_support", "escalate_complex"],
        "priority": 7,
    },
    {
        "id": "optimize_ads",
        "title": "Otimizar campanhas de anuncios",
        "description": "Ajustar lances e orcamentos com base no ROAS atual",
        "tags": ["ads", "marketing"],
        "goal_state": {"ads_optimized": True},
        "suggested_skills": ["analyze_ad_roas", "adjust_ad_budget"],
        "priority": 6,
    },
    {
        "id": "restock_products",
        "title": "Reabastecer produtos criticos",
        "description": "Identificar e reabastecer produtos com estoque baixo antes de ficarem sem",
        "tags": ["inventory", "restock"],
        "goal_state": {"low_stock_restocked": True},
        "suggested_skills": ["low_stock_alert", "create_purchase_order"],
        "priority": 8,
    },
    {
        "id": "analyze_competitors",
        "title": "Analisar precos de concorrentes",
        "description": "Coletar e analisar precos dos principais concorrentes para ajuste competitivo",
        "tags": ["competitor", "pricing", "intelligence"],
        "goal_state": {"concorrente_verificado": True, "preco_ajustado": True},
        "suggested_skills": ["check_competitor_price", "adjust_price"],
        "priority": 5,
    },
    {
        "id": "daily_maintenance",
        "title": "Manutencao diaria da loja",
        "description": "Rotina completa de verificacoes diarias: estoque, precos, pedidos, metricas",
        "tags": ["maintenance", "daily", "core"],
        "goal_state": {
            "margin_protected": True,
            "stock_checked": True,
            "orders_pending_ship": False,
            "support_handled": True,
        },
        "suggested_skills": ["protect_margin", "low_stock_alert", "order_ship", "auto_support"],
        "priority": 10,
    },
]


def get_goal(goal_id: str) -> GoalTemplate | None:
    for g in GOAL_LIBRARY:
        if g["id"] == goal_id:
            return dict(g)
    return None


def search_goals(query: str) -> list[GoalTemplate]:
    q = query.lower()
    results = []
    for g in GOAL_LIBRARY:
        if q in g["title"].lower() or q in g["description"].lower() or any(q in t.lower() for t in g["tags"]):
            results.append(dict(g))
    return results


def list_goals(tag: str | None = None) -> list[GoalTemplate]:
    if tag:
        return [dict(g) for g in GOAL_LIBRARY if tag in g["tags"]]
    return [dict(g) for g in GOAL_LIBRARY]


def add_goal_template(
    goal_id: str,
    title: str,
    description: str,
    goal_state: dict[str, Any],
    tags: list[str] | None = None,
    suggested_skills: list[str] | None = None,
    priority: int = 5,
) -> GoalTemplate:
    template = {
        "id": goal_id,
        "title": title,
        "description": description,
        "tags": tags or [],
        "goal_state": goal_state,
        "suggested_skills": suggested_skills or [],
        "priority": priority,
    }
    # Replace if exists
    for i, g in enumerate(GOAL_LIBRARY):
        if g["id"] == goal_id:
            GOAL_LIBRARY[i] = template
            return template
    GOAL_LIBRARY.append(template)
    return template
