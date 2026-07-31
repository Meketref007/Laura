from __future__ import annotations

from shopee_agent import cli


def test_build_parser_includes_api_serve_command():
    parser = cli.build_parser()
    args = parser.parse_args([
        "api-serve",
        "--host",
        "0.0.0.0",
        "--port",
        "9010",
        "--reload",
        "--log-level",
        "debug",
    ])

    assert args.command == "api-serve"
    assert args.host == "0.0.0.0"
    assert args.port == 9010
    assert args.reload is True
    assert args.log_level == "debug"


def test_main_dispatches_api_serve_without_loading_shopee_config(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.setattr(cli.sys, "argv", ["laura", "api-serve", "--host", "127.0.0.1", "--port", "8001"])

    exit_code = cli.main()

    assert exit_code == 0
    assert captured["app"] == "shopee_agent.api_app:app"
    assert captured["kwargs"] == {
        "host": "127.0.0.1",
        "port": 8001,
        "reload": False,
        "log_level": "info",
    }
