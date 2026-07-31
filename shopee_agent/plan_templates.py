"""Plan Templates — reusable plan templates with parameter substitution ({{param}})."""

from __future__ import annotations

import re
from typing import Any

PARAM_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def resolve_template(template: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Substitute {{param}} placeholders in a template dict with actual values.

    Supports recursion into nested dicts and lists.
    """
    result: dict[str, Any] = {}
    for key, value in template.items():
        new_key = _substitute(key, params)
        if isinstance(value, dict):
            result[new_key] = resolve_template(value, params)
        elif isinstance(value, list):
            result[new_key] = [_resolve_item(item, params) for item in value]
        elif isinstance(value, str):
            result[new_key] = _substitute(value, params)
        else:
            result[new_key] = value
    return result


def _resolve_item(item: Any, params: dict[str, Any]) -> Any:
    if isinstance(item, dict):
        return resolve_template(item, params)
    elif isinstance(item, list):
        return [_resolve_item(i, params) for i in item]
    elif isinstance(item, str):
        return _substitute(item, params)
    return item


def _substitute(text: str, params: dict[str, Any]) -> str:
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return str(params.get(key, match.group(0)))
    return PARAM_PATTERN.sub(replacer, text)


# Built-in plan templates
BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "daily_margin_check",
        "title": "Daily Margin Check for {{item_id}}",
        "description": "Check and protect margin for a specific item",
        "goal_state": {"margin_protected": True},
        "suggested_skills": ["protect_margin"],
        "params": ["item_id"],
    },
    {
        "id": "restock_alert",
        "title": "Restock Alert for {{product_name}}",
        "description": "Alert when {{product_name}} stock falls below {{threshold}}",
        "goal_state": {"stock_checked": True, "low_stock_restocked": True},
        "suggested_skills": ["low_stock_alert", "create_purchase_order"],
        "params": ["product_name", "threshold"],
    },
    {
        "id": "competitor_price_check",
        "title": "Competitor Price Check for {{sku}}",
        "description": "Check competitor pricing for a specific SKU and adjust if needed",
        "goal_state": {"concorrente_verificado": True, "preco_ajustado": True},
        "suggested_skills": ["check_competitor_price", "adjust_price"],
        "params": ["sku"],
    },
]


def list_templates() -> list[dict[str, Any]]:
    return [dict(t) for t in BUILTIN_TEMPLATES]


def get_template(template_id: str) -> dict[str, Any] | None:
    for t in BUILTIN_TEMPLATES:
        if t["id"] == template_id:
            return dict(t)
    return None


def render_template(template_id: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Render a template with given params substitution."""
    template = get_template(template_id)
    if template is None:
        return None
    return resolve_template(template, params)
