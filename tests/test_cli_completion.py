"""Tests for shell completion script generators."""

import argparse
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_commands():
    return [
        {
            "name": "doctor",
            "full": "doctor",
            "help": "Diagnostico rapido",
            "args": [
                {"flags": ["--env-file"], "dest": "env_file", "metavar": "VALUE",
                 "help": "Caminho do .env", "choices": None, "required": False,
                 "nargs": None, "const": None, "type": "arg"},
                {"flags": ["--json"], "dest": "json", "metavar": "VALUE",
                 "help": "Saida em JSON", "choices": None, "required": False,
                 "nargs": None, "const": None, "type": "flag"},
            ],
            "subcommands": [],
        },
        {
            "name": "health",
            "full": "health",
            "help": "Health check",
            "args": [],
            "subcommands": [],
        },
    ]


def test_generate_bash_script(sample_commands):
    from shopee_agent.cli_completion import generate_bash_script
    script = generate_bash_script(sample_commands)
    assert "doctor" in script
    assert "health" in script
    assert "complete -F _laura_completions laura" in script
    assert "--env-file" in script or "--json" in script


def test_generate_zsh_script(sample_commands):
    from shopee_agent.cli_completion import generate_zsh_script
    script = generate_zsh_script(sample_commands)
    assert "doctor" in script
    assert "health" in script
    assert "#compdef laura" in script


def test_generate_powershell_script(sample_commands):
    from shopee_agent.cli_completion import generate_powershell_script
    script = generate_powershell_script(sample_commands)
    assert "doctor" in script
    assert "health" in script
    assert "Register-ArgumentCompleter" in script


def test_build_parser():
    from shopee_agent.cli_completion import build_parser
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    build_parser(sub)
    args = parser.parse_args(["completion", "bash"])
    assert args.shell == "bash"
    assert args.cmd == "completion"


def test_main(monkeypatch):
    from shopee_agent.cli_completion import main
    monkeypatch.setattr(sys, 'argv', ["laura", "completion", "bash"])
    monkeypatch.setattr("shopee_agent.cli_completion.generate_bash_script", MagicMock(return_value="# completion script"))
    monkeypatch.setattr("shopee_agent.cli_completion._iter_subcommands", MagicMock(return_value=[]))
    with patch("shopee_agent.cli_completion.build_parser") as mock_bp:
        result = main()
        assert result == 0


def test_iter_subcommands():
    from shopee_agent.cli_completion import _iter_subcommands
    parser = argparse.ArgumentParser(prog="test")
    sub = parser.add_subparsers(dest="cmd")
    sp = sub.add_parser("test-cmd", description="A test command")
    sp.add_argument("--flag", action="store_true")
    commands = _iter_subcommands(parser)
    assert isinstance(commands, list)
    names = [c["name"] for c in commands]
    assert "test-cmd" in names
