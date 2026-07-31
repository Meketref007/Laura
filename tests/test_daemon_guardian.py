"""Tests for the daemon guardian (shopee_agent.daemon_guardian)."""

import sys

from shopee_agent.daemon_guardian import (
    SIGINT_EXIT,
    WINDOWS_SIGINT_EXIT,
    DaemonGuardian,
)


def test_should_restart_on_crash():
    g = DaemonGuardian(["python", "-c", "pass"])
    assert g._should_restart(1) is True
    assert g._should_restart(2) is True
    assert g._should_restart(-9) is True
    assert g._should_restart(255) is True


def test_should_not_restart_on_clean_exit():
    g = DaemonGuardian(["python", "-c", "pass"])
    assert g._should_restart(0) is False
    assert g._should_restart(SIGINT_EXIT) is False
    assert g._should_restart(WINDOWS_SIGINT_EXIT) is False


def test_spawn_command(tmp_path):
    log = tmp_path / "guardian.log"
    g = DaemonGuardian(
        command=[sys.executable, "-c", "import time; time.sleep(5)"],
        log_path=str(log),
    )
    proc = g._spawn()
    assert proc is not None
    assert proc.poll() is None
    proc.terminate()
    proc.wait(timeout=10)
    assert log.exists()
    g.stop()


def test_backoff_increases():
    g = DaemonGuardian(["python", "-c", "pass"], backoff_base=5.0)
    assert g._backoff_delay(0) == 5.0
    assert g._backoff_delay(1) == 10.0
    assert g._backoff_delay(2) == 20.0
    assert g._backoff_delay(3) == 40.0


def test_run_forever_gives_up_after_max_restarts(tmp_path):
    log = tmp_path / "guardian.log"
    g = DaemonGuardian(
        command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        max_restarts=2,
        backoff_base=0.05,
        log_path=str(log),
    )
    g.run_forever()
    text = log.read_text(encoding="utf-8")
    assert "Gave up" in text
    assert text.count("crashed") == 2
