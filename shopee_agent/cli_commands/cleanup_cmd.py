"""Comando cleanup - limpa arquivos JSONL antigos."""
import json
import time
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"

DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_MAX_LINES = 5000


def register_cleanup_parser(sub):
    p = sub.add_parser("cleanup", help="Limpa arquivos JSONL antigos")
    p.add_argument("--days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                   help="Idade maxima em dias (default: 30)")
    p.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES,
                   help="Maximo de linhas por arquivo (default: 5000)")
    p.add_argument("--dry-run", action="store_true",
                   help="Mostra o que seria apagado sem apagar")


def _jsonl_age_days(path: Path) -> float:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return 0
        last = lines[-1].strip()
        if not last:
            return 0
        item = json.loads(last)
        ts = item.get("timestamp", item.get("generated_at", ""))
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return (datetime.now(UTC) - dt).total_seconds() / 86400
    except Exception:
        pass
    return 0


def handle_cleanup(args):
    max_age = args.days
    max_lines = args.max_lines
    dry_run = args.dry_run
    total_removed = 0

    for path in sorted(REPORTS_DIR.glob("*_pending.jsonl")):
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        lines = [l.strip() for l in lines if l.strip()]

        # Remove por idade (baseado no timestamp do ultimo item)
        age = _jsonl_age_days(path)
        if age > max_age:
            if dry_run:
                print(f"[DRY-RUN] Removeria {path.name} ({age:.0f} dias)")
            else:
                path.unlink()
                print(f"Removido {path.name} ({age:.0f} dias)")
            total_removed += 1
            continue

        # Remove linhas excedentes (mantem as mais recentes)
        if len(lines) > max_lines:
            keep = lines[-max_lines:]
            if dry_run:
                print(f"[DRY-RUN] Truncaria {path.name}: {len(lines)} -> {len(keep)} linhas")
            else:
                path.write_text("\n".join(keep) + "\n", encoding="utf-8")
                print(f"Truncado {path.name}: {len(lines)} -> {len(keep)} linhas")
            total_removed += 1

    # Limpar logs antigos
    log_dir = BASE_DIR / "logs"
    if log_dir.exists():
        for path in log_dir.glob("*.log.*"):
            age_days = (time.time() - path.stat().st_mtime) / 86400
            if age_days > max_age * 2:
                if dry_run:
                    print(f"[DRY-RUN] Removeria log {path.name} ({age_days:.0f} dias)")
                else:
                    path.unlink()
                    print(f"Removido log {path.name}")
                total_removed += 1

    if total_removed == 0:
        print("Nada para limpar")
    else:
        print(f"{total_removed} arquivo(s) processado(s)")
