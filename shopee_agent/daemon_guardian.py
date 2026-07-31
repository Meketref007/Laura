"""Daemon guardian — restarts the daemon automatically if it crashes.

Windows: uses a watchdog thread + Windows Task Scheduler fallback.
Linux: uses systemd restart policy (already configured in deploy/laura.service).
Cross-platform: parent process monitors child via exit codes and restarts with backoff.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PID_FILE = BASE_DIR / "laura_guardian.pid"
DAEMON_PID_FILE = BASE_DIR / "laura_daemon.pid"
DEFAULT_LOG_PATH = BASE_DIR / "reports" / "daemon_guardian.log"

SIGINT_EXIT = 130
WINDOWS_SIGINT_EXIT = 3221225786  # 0xC000013A — Ctrl+C / terminated by console
WINDOWS_SCHEDULED_TASK = "LauraDaemonRestart"


class DaemonGuardian:
    """Supervises a command (the daemon), restarting it on crashes with backoff."""

    def __init__(
        self,
        command: list[str],
        max_restarts: int = 5,
        backoff_base: float = 5.0,
        log_path: str | None = None,
    ):
        self.command = list(command)
        self.max_restarts = max_restarts
        self.backoff_base = float(backoff_base)
        self.log_path = Path(log_path) if log_path else DEFAULT_LOG_PATH
        self._stopped = False
        self._process: subprocess.Popen | None = None
        self._log_handle = None

    def stop(self) -> None:
        self._stopped = True
        proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _backoff_delay(self, attempt: int) -> float:
        return self.backoff_base * (2 ** max(0, attempt))

    def _should_restart(self, exit_code: int) -> bool:
        """Don't restart on clean exit (0) or SIGINT (130 / Windows Ctrl+C)."""
        if exit_code == 0:
            return False
        if exit_code in (SIGINT_EXIT, WINDOWS_SIGINT_EXIT):
            return False
        return True

    def _spawn(self) -> subprocess.Popen:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self._log_handle is None:
            self._log_handle = open(self.log_path, "a", encoding="utf-8")
        self._process = subprocess.Popen(
            self.command,
            cwd=str(BASE_DIR),
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
        )
        return self._process

    def _log(self, message: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        try:
            if self._log_handle is not None:
                self._log_handle.write(line)
                self._log_handle.flush()
            else:
                print(line, end="")
        except Exception:
            pass

    def run_forever(self) -> None:
        attempt = 0
        while not self._stopped:
            if attempt > 0 and attempt >= self.max_restarts:
                self._log(
                    f"Gave up after {attempt} restart(s) — max_restarts={self.max_restarts}"
                )
                return
            self._log(f"Starting daemon: {' '.join(self.command)} (attempt={attempt})")
            proc = self._spawn()
            exit_code = proc.wait()
            if self._stopped:
                self._log("Guardian stopped by request")
                return
            if not self._should_restart(exit_code):
                self._log(f"Daemon exited cleanly (code={exit_code}) — not restarting")
                return
            attempt += 1
            delay = self._backoff_delay(attempt - 1)
            self._log(
                f"Daemon crashed (code={exit_code}) — restarting in {delay:.1f}s "
                f"(restart #{attempt}/{self.max_restarts})"
            )
            deadline = time.time() + delay
            while time.time() < deadline and not self._stopped:
                time.sleep(min(0.5, deadline - time.time()))


def _kill_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def _is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    except Exception:
        return False


def _guardian_pid() -> int | None:
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except Exception:
        pass
    return None


def restart_daemon_windows() -> bool:
    """Register a Windows scheduled task that starts the daemon on logon."""
    if os.name != "nt":
        return False
    try:
        tr = " ".join(f'"{c}"' for c in [sys.executable, "-m", "shopee_agent.laura_daemon"])
        result = subprocess.run(
            [
                "schtasks", "/Create", "/F",
                "/SC", "ONLOGON",
                "/TN", WINDOWS_SCHEDULED_TASK,
                "/TR", tr,
            ],
            capture_output=True, text=True, timeout=20,
        )
        return result.returncode == 0
    except Exception:
        return False


def guardian_main() -> None:
    """Entry point for ``python -m shopee_agent.daemon_guardian``."""
    guardian = DaemonGuardian([sys.executable, "-m", "shopee_agent.laura_daemon"])
    try:
        PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass
    try:
        guardian.run_forever()
    except KeyboardInterrupt:
        guardian.stop()
    finally:
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI: laura guardian start | stop | status
# ---------------------------------------------------------------------------


def build_parser(subparsers) -> None:
    g = subparsers.add_parser(
        "guardian",
        help="Daemon guardian — reinicia o daemon automaticamente se ele cair",
    )
    gsub = g.add_subparsers(dest="guardian_action", required=True)
    gsub.add_parser("start", help="Inicia o guardian supervisionando o daemon")
    gsub.add_parser("stop", help="Para o guardian e o daemon supervisionado")
    gsub.add_parser("status", help="Status do guardian e do daemon")


def handle_guardian(args, client=None, cfg=None) -> int:
    action = getattr(args, "guardian_action", "")
    if action == "start":
        pid = _guardian_pid()
        if pid and _is_running(pid):
            print(f"Guardian ja rodando (PID {pid})")
            return 0
        subprocess.Popen(
            [sys.executable, "-m", "shopee_agent.daemon_guardian"],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)
        pid = _guardian_pid()
        if pid and _is_running(pid):
            print(f"Guardian iniciado (PID {pid})")
            if restart_daemon_windows():
                print(f"Tarefa agendada '{WINDOWS_SCHEDULED_TASK}' registrada (fallback ONLOGON)")
        else:
            print("Falha ao iniciar guardian")
            return 1
        return 0

    if action == "stop":
        pid = _guardian_pid()
        if pid and _is_running(pid):
            _kill_pid(pid)
            print(f"Guardian (PID {pid}) parado")
        else:
            print("Guardian nao estava rodando")
        if PID_FILE.exists():
            PID_FILE.unlink()
        return 0

    if action == "status":
        print("=== Status ===")
        gpid = _guardian_pid()
        if gpid and _is_running(gpid):
            print(f"Guardian: rodando (PID {gpid})")
        else:
            print("Guardian: PARADO")
        dpid = 0
        try:
            if DAEMON_PID_FILE.exists():
                dpid = int(DAEMON_PID_FILE.read_text().strip())
        except Exception:
            dpid = 0
        if dpid and _is_running(dpid):
            print(f"Daemon: rodando (PID {dpid})")
        else:
            print("Daemon: PARADO")
        return 0

    return 2


if __name__ == "__main__":
    guardian_main()
