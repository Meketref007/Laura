"""Funcoes auxiliares do painel (sem tkinter, testaveis)."""

import os
import re
import subprocess
import urllib.request
from pathlib import Path

DOT = "\u25cf"
EMPTY = "\u25cb"


def resolve_code_dir() -> Path:
    override = os.environ.get("LAURA_HOME")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Laura" / "code"


def read_version(code_dir: Path) -> str:
    pyproject = code_dir / "pyproject.toml"
    if pyproject.exists():
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1)
    return "?"


def git_short_sha(code_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(code_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return out.stdout.strip() if out.returncode == 0 else "?"
    except Exception:
        return "?"


def parse_status(text: str) -> dict:
    result = {}
    for m in re.finditer(r"^\s*(webhook|telegram|daemon|watchdog|outro)\s+PID\s+(\d+)", text, re.M):
        result[m.group(1)] = int(m.group(2))
    return result


def health_check(port: int = 8766) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def tail_lines(path: Path, n: int = 250, max_bytes: int = 64 * 1024) -> str:
    if not path.exists():
        return "(sem log ainda — inicie os servicos)"
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read()
        lines = data.decode("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:]) if lines else "(vazio)"
    except Exception as exc:
        return f"(erro ao ler log: {exc})"


def ver_gt(a: str, b: str) -> bool:
    def parts(v: str):
        return [int(x) for x in re.split(r"[^\d]+", v) if x.isdigit()][:3]

    try:
        return parts(a) > parts(b)
    except Exception:
        return False
