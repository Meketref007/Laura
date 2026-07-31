"""
Watchdog para o daemon Laura (Windows-compatible).
Monitora o processo do daemon e reinicia se morrer.
Uso: python tools/laura_watchdog.py
"""
import os, subprocess, sys, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PID_FILE = BASE_DIR / "laura_daemon.pid"
WATCHDOG_PID_FILE = BASE_DIR / "laura_watchdog.pid"
CHECK_INTERVAL = 30
RESTART_DELAY = 5

def _is_running(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in proc.stdout
    except Exception:
        return False

def _start_daemon():
    daemon_script = str(BASE_DIR / "shopee_agent" / "laura_daemon.py")
    proc = subprocess.Popen(
        [sys.executable, daemon_script],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    print(f"[Watchdog] Daemon iniciado (PID {proc.pid})")
    return proc

def _stop_daemon(proc):
    if proc is None:
        return
    print(f"[Watchdog] Parando daemon (PID {proc.pid})...")
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/F"],
                   capture_output=True, timeout=10)
    if PID_FILE.exists():
        PID_FILE.unlink()

def watch():
    print("[Watchdog] Iniciado (Windows mode)")
    WATCHDOG_PID_FILE.write_text(str(os.getpid()))
    proc = None

    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if _is_running(old_pid):
                print(f"[Watchdog] Daemon ja rodando (PID {old_pid}), monitorando...")
                proc = subprocess.Popen(["python", "-c", f"import time; time.sleep(999999)"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc.pid = old_pid
                proc._killed = False
            else:
                PID_FILE.unlink()
        except Exception:
            pass

    if proc is None:
        proc = _start_daemon()

    try:
        while True:
            time.sleep(CHECK_INTERVAL)
            if not _is_running(proc.pid):
                print(f"[Watchdog] Daemon morreu (PID {proc.pid}), reiniciando...")
                proc = _start_daemon()
    except KeyboardInterrupt:
        print("[Watchdog] Encerrando...")
        _stop_daemon(proc)

if __name__ == "__main__":
    watch()
