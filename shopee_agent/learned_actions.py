"""
learned_actions.py — Ações aprendidas pelo usuário.

Permite que Laura aprenda novas ações manualmente.
O usuário ensina o nome da ação + instruções, e Laura executa quando solicitado.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ACTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "learned_actions"
_ACTIONS_INDEX = _ACTIONS_DIR / "index.json"


def _ensure_dir() -> None:
    _ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not _ACTIONS_INDEX.exists():
        _ACTIONS_INDEX.write_text("{}", encoding="utf-8")


def _load_index() -> dict[str, dict]:
    _ensure_dir()
    try:
        data = json.loads(_ACTIONS_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_index(index: dict) -> None:
    _ensure_dir()
    _ACTIONS_INDEX.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def learn_action(
    name: str,
    instructions: str,
    steps: list[dict] | None = None,
) -> dict:
    """Ensinar uma nova ação à Laura.
    
    Args:
        name: Nome único da ação (ex: "ativar_retirada_comprador")
        instructions: Instruções em texto livre sobre como executar
        steps: Lista opcional de passos estruturados:
            - {"type": "api", "method": "GET|POST", "endpoint": "...", "params": {...}}
            - {"type": "message", "text": "..."}
            - {"type": "navigate", "url": "..."}
    
    Returns:
        Dict com a ação salva
    """
    index = _load_index()
    now = datetime.now(UTC).isoformat()

    action = {
        "name": name,
        "instructions": instructions,
        "steps": steps or [],
        "created_at": now,
        "updated_at": now,
        "execution_count": 0,
    }

    index[name] = action
    _save_index(index)

    # Save individual file for easy editing
    action_file = _ACTIONS_DIR / f"{name}.json"
    action_file.write_text(
        json.dumps(action, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return action


def get_action(name: str) -> dict | None:
    """Recuperar uma ação aprendida pelo nome."""
    index = _load_index()
    return index.get(name)


def list_actions() -> list[dict]:
    """Listar todas as ações aprendidas."""
    index = _load_index()
    return [
        {
            "name": v["name"],
            "instructions": v.get("instructions", "")[:100],
            "step_count": len(v.get("steps", [])),
            "created_at": v.get("created_at", ""),
            "execution_count": v.get("execution_count", 0),
        }
        for v in index.values()
    ]


def forget_action(name: str) -> bool:
    """Remover uma ação aprendida."""
    index = _load_index()
    if name not in index:
        return False
    del index[name]
    _save_index(index)
    action_file = _ACTIONS_DIR / f"{name}.json"
    if action_file.exists():
        action_file.unlink()
    return True


def execute_action(name: str, params: dict[str, Any] | None = None) -> str:
    """Executar uma ação aprendida e retornar resultado."""
    action = get_action(name)
    if not action:
        return f"Ação '{name}' não encontrada."

    steps = action.get("steps", [])
    if not steps:
        return action.get("instructions", f"Instruções para '{name}': sem passos definidos.")

    results = []
    for i, step in enumerate(steps):
        step_type = step.get("type", "")
        try:
            if step_type == "api":
                result = _execute_api_step(step, params)
                results.append(f"Passo {i+1} (API): {result}")
            elif step_type == "message":
                text = step.get("text", "").format(**(params or {}))
                results.append(f"📋 {text}")
            elif step_type == "navigate":
                results.append(f"🔗 Acesse: {step.get('url', '')}")
            else:
                results.append(f"Passo {i+1}: {step.get('text', str(step))}")
        except Exception as e:
            results.append(f"Passo {i+1} ERRO: {e}")

    # Update execution count
    index = _load_index()
    if name in index:
        index[name]["execution_count"] = index[name].get("execution_count", 0) + 1
        index[name]["last_executed"] = datetime.now(UTC).isoformat()
        _save_index(index)

    return "\n".join(results)


def _execute_api_step(step: dict, params: dict | None) -> str:
    """Execute an API step using requests."""
    import requests

    method = step.get("method", "GET").upper()
    endpoint = step.get("endpoint", "")
    step_params = dict(step.get("params", {}))
    if params:
        step_params.update(params)

    base_url = "https://seller.br.shopee.cn"
    url = f"{base_url}{endpoint}"

    try:
        if method == "GET":
            resp = requests.get(url, params=step_params, timeout=15)
        elif method == "POST":
            resp = requests.post(url, json=step_params, timeout=15)
        else:
            return f"Método {method} não suportado"

        data = resp.json()
        code = data.get("code", -1)
        if code == 0:
            return "✅ OK (code=0)"
        else:
            return f"⚠️ Resposta: {data.get('msg', str(data)[:200])}"
    except Exception as e:
        return f"❌ Erro HTTP: {e}"


def build_llm_context() -> str:
    """Build a context string about learned actions for the LLM prompt."""
    actions = list_actions()
    if not actions:
        return ""

    lines = ["\nAÇÕES QUE VOCÊ APRENDEU (ensinadas pelo usuário):"]
    for a in actions:
        instr = a.get("instructions", "").replace("\n", " ")[:150]
        lines.append(f"- {a['name']}: {instr}")
    lines.append(
        'Quando o usuário pedir algo que corresponda a uma ação aprendida, '
        'responda com: {"type":"action","intent":"learned_action","params":{"name":"NOME_ACAO"},"response":"Vou executar NOME_ACAO."}'
    )
    return "\n".join(lines)
