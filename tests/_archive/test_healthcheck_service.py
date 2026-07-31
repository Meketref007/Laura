from __future__ import annotations

import json
from subprocess import CompletedProcess

from shopee_agent.healthcheck_service import LauraHealthcheckRunner


class TestLauraHealthcheckRunner:
    def test_run_appends_log_and_notifies_on_low_score(self, monkeypatch, tmp_path):
        root_dir = tmp_path
        (root_dir / "logs").mkdir(parents=True)
        (root_dir / "reports").mkdir(parents=True)
        (root_dir / ".env").write_text("LAURA_ALERT_TELEGRAM_BOT_TOKEN=test\nLAURA_ALERT_TELEGRAM_CHAT_ID=123\n", encoding="utf-8")
        (root_dir / "reports" / "laura_health_latest.json").write_text(
            json.dumps({"health_score": 40, "product_count": 12}),
            encoding="utf-8",
        )

        runner = LauraHealthcheckRunner(root_dir=root_dir)

        monkeypatch.setattr(
            runner,
            "_run_healthcheck_command",
            lambda: CompletedProcess(args=["health-check"], returncode=0, stdout="[INFO] Laura health-check finished\n", stderr=""),
        )

        sent: list[tuple[str, str]] = []
        monkeypatch.setattr(runner, "_send_telegram", lambda title, body: sent.append((title, body)))

        result = runner.run()

        assert result.exit_code == 0
        assert runner.log_file.exists()
        assert any("Running Laura health-check" in line for line in runner.log_file.read_text(encoding="utf-8" ).splitlines())
        assert sent == [("✅ API Shopee respondendo", "Score: 40/100 | Produtos ativos: 12\nHealth-check OK — próximo em 3h")]
        assert json.loads(runner.last_status_file.read_text(encoding="utf-8"))["score"] == 40
