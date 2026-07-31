"""Tests for the CLI parser and command handlers."""

import pytest
import sys
from unittest.mock import patch, MagicMock


def test_parser_creates_successfully():
    from shopee_agent.cli import build_parser
    parser = build_parser()
    assert parser is not None


def test_parser_root_help():
    from shopee_agent.cli import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])


def test_parser_all_commands_have_help():
    from shopee_agent.cli import build_parser
    parser = build_parser()
    for cmd in ["dashboard", "doctor", "health", "api-serve", "shell",
                "daemon", "export", "plan-store", "planner-alerts",
                "campaign", "workers", "cross-sell", "sc", "vision",
                "chat", "telegram", "report"]:
        with pytest.raises(SystemExit):
            parser.parse_args([cmd, "--help"])


def test_parser_unknown_command():
    from shopee_agent.cli import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["unknown_command_xyz"])


def test_handle_doctor(monkeypatch):
    from shopee_agent.cli import main
    monkeypatch.setattr(sys, 'argv', ["laura", "doctor"])
    monkeypatch.setattr("shopee_agent.cli.info", MagicMock())
    monkeypatch.setattr("shopee_agent.cli.debug", MagicMock())
    monkeypatch.setattr("shopee_agent.cli.initialize_default_circuit_breakers", MagicMock())
    monkeypatch.setattr("shopee_agent.cli._doctor_report", MagicMock(return_value={
        "overall_ok": True, "python": {"ok": True, "version": "3.12.0"},
        "env_file": {}, "shopee_config": {}, "llm_local": {},
    }))
    monkeypatch.setattr("shopee_agent.cli._print_doctor_text", MagicMock())
    result = main()
    assert result == 0


def test_handle_health(monkeypatch):
    from shopee_agent.cli import main
    monkeypatch.setattr(sys, 'argv', ["laura", "health"])
    monkeypatch.setattr("shopee_agent.cli.info", MagicMock())
    monkeypatch.setattr("shopee_agent.cli.debug", MagicMock())
    monkeypatch.setattr("shopee_agent.cli.initialize_default_circuit_breakers", MagicMock())
    monkeypatch.setattr("shopee_agent.cli_commands.health_cmd.handle_health", MagicMock())
    result = main()
    assert result == 0


def test_no_cred_commands(monkeypatch):
    from shopee_agent.cli import main
    monkeypatch.setattr("shopee_agent.cli.info", MagicMock())
    monkeypatch.setattr("shopee_agent.cli.debug", MagicMock())
    monkeypatch.setattr("shopee_agent.cli.initialize_default_circuit_breakers", MagicMock())
    monkeypatch.setattr("shopee_agent.cli.load_config", MagicMock(side_effect=Exception("no creds needed")))
    monkeypatch.setattr("shopee_agent.cli.ConfigError", Exception)
    for cmd in ["doctor", "health"]:
        monkeypatch.setattr(sys, 'argv', ["laura", cmd])
        monkeypatch.setattr("shopee_agent.cli._doctor_report", MagicMock(return_value={
            "overall_ok": True, "python": {"ok": True, "version": "3.12.0"},
            "env_file": {}, "shopee_config": {}, "llm_local": {},
        }))
        monkeypatch.setattr("shopee_agent.cli._print_doctor_text", MagicMock())
        monkeypatch.setattr("shopee_agent.cli_commands.health_cmd.handle_health", MagicMock())
        main()
