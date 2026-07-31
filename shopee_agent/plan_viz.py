"""Plan visualization — export plans as Mermaid diagrams."""

from __future__ import annotations

from typing import Any


def plan_to_mermaid(
    actions: list[dict[str, Any]],
    start_state: dict[str, Any] | None = None,
    goal_state: dict[str, Any] | None = None,
    title: str = "GOAP Plan",
) -> str:
    """Convert a plan (list of action dicts) to a Mermaid flowchart.

    Each action dict must have at least: name, cost, preconditions, effects.
    """
    lines = ["```mermaid", "flowchart TD"]
    lines.append(f"    title[{title}]")
    lines.append("")

    # Start node
    if start_state:
        state_label = _format_state(start_state, max_len=30)
        lines.append(f"    START([Start: {state_label}])")
        next_id = "START"
    else:
        lines.append("    START([Start])")
        next_id = "START"

    for i, action in enumerate(actions):
        node_id = f"A{i}"
        name = action.get("name", f"action_{i}")
        cost = action.get("cost", "?")
        pre = action.get("preconditions", {})
        eff = action.get("effects", {})
        pre_label = _format_state(pre, max_len=25)
        eff_label = _format_state(eff, max_len=25)
        label = f"{name}\\n(cost: {cost})"
        if pre:
            label += f"\\nif: {pre_label}"
        if eff:
            label += f"\\nthen: {eff_label}"
        lines.append(f"    {node_id}[{label}]")
        lines.append(f"    {next_id} --> {node_id}")
        next_id = node_id

    # Goal node
    if goal_state:
        goal_label = _format_state(goal_state, max_len=30)
        lines.append(f"    GOAL([Goal: {goal_label}])")
        lines.append(f"    {next_id} --> GOAL")
    else:
        lines.append("    END([End])")
        lines.append(f"    {next_id} --> END")

    lines.append("```")
    return "\n".join(lines)


def plan_to_mermaid_gantt(
    actions: list[dict[str, Any]],
    title: str = "GOAP Plan Timeline",
) -> str:
    """Convert a plan to a Mermaid Gantt chart."""
    lines = ["```mermaid", "gantt"]
    lines.append(f"    title {title}")
    lines.append("    dateFormat  HH:mm")
    lines.append("    axisFormat  %H:%M")
    lines.append("")

    current_minute = 0
    for i, action in enumerate(actions):
        name = action.get("name", f"action_{i}")
        cost = action.get("cost", 1)
        duration = max(1, int(cost * 10))
        start_str = f"00:{current_minute:02d}"
        end_min = current_minute + duration
        lines.append(f"    section Step {i+1}")
        lines.append(f"    {name} :{start_str},{duration}min")
        current_minute = end_min

    lines.append("```")
    return "\n".join(lines)


def _format_state(state: dict[str, Any], max_len: int = 30) -> str:
    """Format a state dict into a short string for diagram labels."""
    parts = []
    for k, v in state.items():
        parts.append(f"{k}={v}")
    text = ", ".join(parts)
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text
