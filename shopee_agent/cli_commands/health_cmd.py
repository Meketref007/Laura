"""Comando health - diagnostico do sistema Laura."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = BASE_DIR / "reports"


def register_health_parser(sub):
    p = sub.add_parser("health", help="Diagnostico completo do sistema Laura")
    p.add_argument("--json", action="store_true", help="Saida em JSON")


def _check_seller_center() -> dict:
    try:
        from shopee_agent.seller_center import load_cookies
        session = load_cookies()
        if not session or not session.cookies or not session.is_valid():
            return {"status": "error", "detail": "Sem cookies de sessao validos"}
        from shopee_agent.seller_center import SellerCenterClient
        sc = SellerCenterClient(session=session)
        info = sc.get_shop_info()
        return {"status": "ok", "shop_name": info.get("name", "?"), "detail": "Autenticado"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _check_ollama() -> dict:
    try:
        from shopee_agent.llm_local import check_ollama_running
        ok = check_ollama_running()
        return {"status": "ok" if ok else "error", "detail": "Rodando" if ok else "Ollama nao responde"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _check_daemon() -> dict:
    pid_file = BASE_DIR / "logs" / "laura_daemon.pid"
    alive = False
    pid = None
    if pid_file.exists():
        try:
            raw = pid_file.read_text(encoding="utf-16")
        except (UnicodeDecodeError, UnicodeError):
            raw = pid_file.read_text()
        try:
            pid = int(raw.strip())
            alive = _pid_alive(pid)
        except Exception:
            alive = False
    state = REPORTS_DIR / "laura_daemon_state.json"
    last = "?"
    if state.exists():
        try:
            data = json.loads(state.read_text())
            last_ts = max((v for k, v in data.items() if k.startswith("last_") and isinstance(v, (int, float))), default=None)
            if last_ts:
                last = datetime.fromtimestamp(last_ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass
    if alive:
        return {"status": "ok", "pid": pid, "last_cycle": last, "detail": f"Rodando (PID {pid}), ultimo ciclo: {last}"}
    return {"status": "stopped", "pid": pid, "last_cycle": last, "detail": "Daemon parado"}


def _check_cdp() -> dict:
    ws_url = os.getenv("CDP_WS_URL", "")
    if not ws_url:
        ws_url = "ws://127.0.0.1:9222/devtools/browser"
    try:
        import requests
        http_url = ws_url.replace("ws://", "http://").replace("/devtools/browser", "/json/version")
        resp = requests.get(http_url, timeout=5)
        if resp.ok:
            info = resp.json()
            return {"status": "ok", "detail": f"CDP acessivel ({info.get('Browser', '?')})"}
        return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _check_pending_queues() -> dict:
    pending = {}
    for path in REPORTS_DIR.glob("*_pending.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            lines = [l for l in lines if l.strip()]
            pending[path.name] = len(lines)
        except Exception:
            pending[path.name] = 0
    total = sum(pending.values())
    if total == 0:
        return {"status": "ok", "detail": "Filas vazias", "queues": pending}
    return {"status": "warning", "detail": f"{total} evento(s) pendente(s)", "queues": pending}


def handle_health(args):
    checks = {
        "seller_center": _check_seller_center(),
        "ollama": _check_ollama(),
        "daemon": _check_daemon(),
        "cdp": _check_cdp(),
        "pending_queues": _check_pending_queues(),
    }

    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return

    print("=== Laura Health Check ===")
    print()
    for name, result in checks.items():
        status_icon = "✅" if result.get("status") == "ok" else "⚠️" if result.get("status") == "warning" else "❌"
        print(f"  {status_icon} {name}: {result.get('detail', result.get('status', '?'))}")

    print()
    errors = sum(1 for r in checks.values() if r.get("status") == "error")
    warnings = sum(1 for r in checks.values() if r.get("status") == "warning")
    if errors:
        print(f"❌ {errors} erro(s) encontrado(s)")
    if warnings:
        print(f"⚠️ {warnings} aviso(s)")
    if errors == 0 and warnings == 0:
        print("✅ Sistema saudavel")
