"""Plan explainability — explains plans in natural language (Portuguese)."""

from __future__ import annotations

from typing import Any


def explain_plan_nl(
    planner: Any,
    start_state: dict[str, Any],
    goal_state: dict[str, Any],
) -> str:
    """Generate a Portuguese natural-language explanation of a GOAP plan."""
    explanation = planner.explain(start_state, goal_state)
    if explanation.get("error") == "no_plan_found":
        return (
            "Não foi possível encontrar um plano para atingir o objetivo. "
            "Verifique se as skills necessárias estão registradas e se as pré-condições podem ser satisfeitas."
        )

    plan = explanation.get("plan", [])
    actions = explanation.get("actions", [])
    total_cost = explanation.get("total_cost", 0)

    lines = [
        f"📋 **Plano GOAP** — {len(plan)} ações, custo total: {total_cost:.1f}",
        "",
    ]

    for i, action in enumerate(actions, 1):
        name = action.get("name", f"Passo {i}")
        cost = action.get("cost", 1.0)
        pre = action.get("preconditions", {})
        eff = action.get("effects_applied", {})
        matched = action.get("matched", {})
        missed = action.get("missed", {})

        lines.append(f"**Passo {i}:** `{name}` (custo: {cost})")

        if pre:
            if missed:
                lines.append(f"  ⚠️  Pré-condições pendentes: {_fmt_dict(missed)}")
            if matched:
                lines.append(f"  ✅  Pré-condições satisfeitas: {_fmt_dict(matched)}")

        if eff:
            lines.append(f"  ➡️  Efeitos: {_fmt_dict(eff)}")
        lines.append("")

    lines.append(f"**Estado final esperado:** {_fmt_dict(explanation.get('final_state', {}))}")
    lines.append(f"**Custo total estimado:** {total_cost:.1f}")

    return "\n".join(lines)


def _fmt_dict(d: dict[str, Any]) -> str:
    """Format a dict for NL display."""
    parts = []
    for k, v in d.items():
        if isinstance(v, dict):
            parts.append(f"{k}={_fmt_dict(v)}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


def explain_with_llm(
    planner: Any,
    start_state: dict[str, Any],
    goal_state: dict[str, Any],
) -> str:
    """Use LLM to generate a richer explanation of the plan."""
    explanation = planner.explain(start_state, goal_state)
    if explanation.get("error") == "no_plan_found":
        return "O planejador não encontrou um plano viável para o objetivo solicitado."

    try:
        from shopee_agent.llm_local import create_analyzer

        plan_summary = f"""
Goal: {goal_state}
Start: {start_state}
Plan: {explanation.get('plan', [])}
Actions: {len(explanation.get('actions', []))} steps
Total cost: {explanation.get('total_cost', 0)}
"""

        analyzer = create_analyzer()
        prompt = f"""Você é um assistente especializado em explicar planos do sistema GOAP da Laura,
um agente autônomo de e-commerce Shopee.

Dado o seguinte plano, explique em português claro por que cada ação foi escolhida,
o que ela faz, e como contribui para o objetivo final.

{plan_summary}

Explique de forma concisa e prática, como se fosse para um lojista."""
        result = analyzer.analyze(prompt)
        return result if result else explain_plan_nl(planner, start_state, goal_state)
    except Exception:
        return explain_plan_nl(planner, start_state, goal_state)
