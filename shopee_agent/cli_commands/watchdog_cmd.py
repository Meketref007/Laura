"""Watchdog commands: start, stop, status."""
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PID_FILE = BASE_DIR / "laura_daemon.pid"
WATCHDOG_PID_FILE = BASE_DIR / "laura_watchdog.pid"


def register_subparsers(sub):
    wd = sub.add_parser("watchdog", help="Gerenciar watchdog do daemon")
    wd_sub = wd.add_subparsers(dest="watchdog_action", required=True)

    wd_start = wd_sub.add_parser("start", help="Iniciar watchdog")
    wd_start.add_argument("--foreground", action="store_true", help="Rodar em foreground (nao como processo separado)")

    wd_sub.add_parser("stop", help="Parar watchdog e daemon")

    wd_sub.add_parser("status", help="Status do watchdog e daemon")

    wd_sub.add_parser("restart", help="Reiniciar daemon via watchdog")


def _is_running(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in proc.stdout
    except Exception:
        return False


def _find_daemon_pid():
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except Exception:
            return None
    return None


def _find_watchdog_pid():
    if WATCHDOG_PID_FILE.exists():
        try:
            pid = int(WATCHDOG_PID_FILE.read_text().strip())
            if _is_running(pid):
                return pid
        except Exception:
            pass
    return None


def run(args, client=None, cfg=None):
    if args.watchdog_action == "start":
        existing = _find_watchdog_pid()
        if existing:
            print(f"Watchdog ja rodando (PID {existing})")
            return 0
        if args.foreground:
            from tools.laura_watchdog import watch
            watch()
        else:
            subprocess.Popen(
                [sys.executable, str(BASE_DIR / "tools" / "laura_watchdog.py")],
                cwd=str(BASE_DIR),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
            pid = _find_watchdog_pid()
            if pid:
                print(f"Watchdog iniciado (PID {pid})")
            else:
                print("Falha ao iniciar watchdog")
        return 0

    if args.watchdog_action == "stop":
        daemon_pid = _find_daemon_pid()
        if daemon_pid and _is_running(daemon_pid):
            subprocess.run(["taskkill", "/F", "/PID", str(daemon_pid)], capture_output=True, timeout=10)
            print(f"Daemon (PID {daemon_pid}) parado")
        watchdog_pid = _find_watchdog_pid()
        if watchdog_pid:
            subprocess.run(["taskkill", "/F", "/PID", str(watchdog_pid)], capture_output=True, timeout=10)
            print(f"Watchdog (PID {watchdog_pid}) parado")
        if PID_FILE.exists():
            PID_FILE.unlink()
        if WATCHDOG_PID_FILE.exists():
            WATCHDOG_PID_FILE.unlink()
        return 0

    if args.watchdog_action == "status":
        daemon_pid = _find_daemon_pid()
        watchdog_pid = _find_watchdog_pid()
        print("=== Status ===")
        if daemon_pid and _is_running(daemon_pid):
            print(f"Daemon: rodando (PID {daemon_pid})")
        else:
            print("Daemon: PARADO")
        if watchdog_pid:
            print(f"Watchdog: rodando (PID {watchdog_pid})")
        else:
            print("Watchdog: PARADO")
        return 0

    if args.watchdog_action == "restart":
        # Stop daemon (watchdog will restart it)
        daemon_pid = _find_daemon_pid()
        if daemon_pid and _is_running(daemon_pid):
            subprocess.run(["taskkill", "/F", "/PID", str(daemon_pid)], capture_output=True, timeout=10)
            print(f"Daemon (PID {daemon_pid}) parado. Watchdog reiniciara automaticamente...")
        else:
            print("Daemon nao estava rodando")
        return 0

    return 2
