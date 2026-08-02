"""Testes das funcoes puras do painel (installer/laura_common.py)."""

import sys
from pathlib import Path

PANEL_DIR = Path(__file__).resolve().parents[1] / "installer"
sys.path.insert(0, str(PANEL_DIR))

import laura_common  # noqa: E402


def test_parse_status_extrai_servicos_e_pids():
    text = """[laura] Servicos ATIVOS (4):
webhook   PID 17896   ".\\venv\\Scripts\\pythonw.exe" -m shopee_agent.cli webhook-start
telegram  PID 18592   ".\\venv\\Scripts\\pythonw.exe" -m shopee_agent.cli telegram-bot
daemon    PID 20832   ".\\venv\\Scripts\\pythonw.exe" -m shopee_agent.cli daemon
watchdog  PID 22192   powershell.exe -File ".\\scripts\\laura_watchdog.ps1"
"""
    result = laura_common.parse_status(text)
    assert result == {"webhook": 17896, "telegram": 18592, "daemon": 20832, "watchdog": 22192}


def test_parse_status_vazio_quando_parado():
    assert laura_common.parse_status("[laura] Servicos PARADOS") == {}


def test_parse_status_ignora_sujeira():
    text = "Nada aqui\nwebhook   PID 9999   cmd\nlixo\n"
    assert laura_common.parse_status(text) == {"webhook": 9999}


def test_read_version(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "laura"\nversion = "3.2.0"\n', encoding="utf-8")
    assert laura_common.read_version(tmp_path) == "3.2.0"


def test_read_version_sem_pyproject(tmp_path):
    assert laura_common.read_version(tmp_path) == "?"


def test_ver_gt():
    assert laura_common.ver_gt("3.2.0", "3.1.0")
    assert laura_common.ver_gt("3.10.0", "3.9.9")
    assert not laura_common.ver_gt("3.1.0", "3.2.0")
    assert not laura_common.ver_gt("3.1.0", "3.1.0")
    assert laura_common.ver_gt("4.0.0", "3.99.99")


def test_tail_lines(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_text("\n".join(f"linha {i}" for i in range(100)), encoding="utf-8")
    out = laura_common.tail_lines(log, n=3)
    assert out == "linha 97\nlinha 98\nlinha 99"


def test_tail_lines_arquivo_inexistente(tmp_path):
    assert "sem log" in laura_common.tail_lines(tmp_path / "nao-existe.log")


def test_tail_lines_arquivo_vazio(tmp_path):
    log = tmp_path / "vazio.log"
    log.write_text("", encoding="utf-8")
    assert "(vazio)" in laura_common.tail_lines(log)
