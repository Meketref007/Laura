"""
Gerenciador de modelo de linguagem (LLM).

Verifica se Ollama esta rodando, se o modelo existe,
baixa automaticamente se necessario, e inicia se parado.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_PATH = os.getenv("OLLAMA_PATH", "ollama")


def _ollama_cmd(*args: str) -> list[str]:
    return [OLLAMA_PATH, *args]


def ollama_rodando() -> bool:
    try:
        r = subprocess.run(
            _ollama_cmd("list"),
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def iniciar_ollama() -> bool:
    """Tenta iniciar o Ollama em background."""
    if ollama_rodando():
        return True
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(
            _ollama_cmd("serve"),
            startupinfo=startupinfo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(1)
            if ollama_rodando():
                return True
        return False
    except FileNotFoundError:
        return False


def modelos_disponiveis() -> list[dict]:
    """Retorna lista de modelos disponiveis localmente."""
    try:
        r = subprocess.run(
            _ollama_cmd("list"),
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return []
        lines = r.stdout.strip().splitlines()
        models = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 3:
                models.append({
                    "nome": parts[0],
                    "id": parts[1],
                    "tamanho": parts[2],
                })
        return models
    except Exception:
        return []


def modelo_existe(nome: str) -> bool:
    return any(m["nome"] == nome for m in modelos_disponiveis())


def baixar_modelo(nome: str) -> bool:
    """Baixa modelo via ollama pull."""
    print(f"Baixando modelo {nome}... (pode demorar alguns minutos)")
    try:
        r = subprocess.run(
            _ollama_cmd("pull", nome),
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode == 0:
            print(f"Modelo {nome} baixado com sucesso!")
            return True
        print(f"Erro ao baixar: {r.stderr[:200]}")
        return False
    except subprocess.TimeoutExpired:
        print(f"Timeout ao baixar {nome}")
        return False
    except FileNotFoundError:
        print("Ollama nao encontrado. Instale em https://ollama.com")
        return False


def garantir_modelo(nome: str) -> bool:
    """
    Verifica se o modelo esta disponivel.
    Se nao, baixa automaticamente.
    """
    if nome in ("", "none"):
        return True

    if not iniciar_ollama():
        print("ERRO: Nao foi possivel iniciar Ollama")
        return False

    if modelo_existe(nome):
        print(f"Modelo {nome} ja disponivel")
        return True

    print(f"Modelo {nome} nao encontrado localmente. Baixando...")
    return baixar_modelo(nome)


def garantir_todos_modelos() -> bool:
    """Verifica e baixa todos os modelos necessarios."""
    modelos = [
        os.getenv("LAURA_LLM_MODEL", "llama3.2:3b"),
    ]
    vision = os.getenv("LAURA_VISION_MODEL", "bakllava:7b").strip()
    if vision and vision != "none":
        modelos.append(vision)

    todos_ok = True
    for m in modelos:
        ok = garantir_modelo(m)
        if not ok:
            print(f"[LLM] Modelo {m} falhou")
            todos_ok = False
    return todos_ok


if __name__ == "__main__":
    ok = garantir_todos_modelos()
    print(f"Resultado: {'OK' if ok else 'FALHOU'}")
