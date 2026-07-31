"""Backup module — compressed backups of reports, databases, and config."""

from __future__ import annotations

import json
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shopee_agent.logger import error, info, warning
from shopee_agent.paths import BACKUPS_DIR, BASE_DIR, SECRETS_DIR

BACKUP_DIR = BACKUPS_DIR
MAX_BACKUPS = int(os.getenv("VILU_MAX_BACKUPS", "30"))

ARQUIVOS_PARA_BACKUP = [
    ".env",
    str(SECRETS_DIR / "gmail_token.json"),
    str(SECRETS_DIR / "Credencial.Laura.json"),
    str(SECRETS_DIR / "seller_center_cookies.json"),
    str(SECRETS_DIR / "seller_center_credentials.json"),
]

EXCLUDE_DIRS = {"__pycache__", ".venv", "node_modules", ".git", ".tox", "venv"}


def _formato_br() -> str:
    agora = datetime.now(UTC) - timedelta(hours=3)
    return agora.strftime("%Y%m%d_%H%M%S")


class BackupManager:
    """Creates, lists, restores, and prunes compressed backups."""

    def __init__(self, backup_dir: str | None = None, source_dirs: list[str] | None = None):
        self._backup_dir = Path(backup_dir) if backup_dir else BACKUP_DIR
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._source_dirs = source_dirs or ["reports"]

    def create_backup(self, name: str = "") -> dict[str, Any]:
        ts = _formato_br()
        safe_name = name.strip().replace(" ", "_") if name else ""
        base_name = f"{safe_name}_{ts}" if safe_name else ts
        zip_path = self._backup_dir / f"{base_name}.zip"

        sources: list[Path] = []
        for rel in self._source_dirs:
            p = Path(rel)
            if not p.is_absolute():
                p = BASE_DIR / rel
            if p.exists():
                sources.append(p)
        db_files = list(BASE_DIR.rglob("*.db"))
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            sources.append(env_file)
        plugin_dir = BASE_DIR / "plugins"
        if plugin_dir.exists():
            sources.append(plugin_dir)

        file_count = 0
        total_bytes = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src in sources:
                if src.is_file():
                    try:
                        arcname = str(src.relative_to(BASE_DIR))
                    except ValueError:
                        arcname = src.name
                    zf.write(src, arcname)
                    file_count += 1
                    total_bytes += src.stat().st_size
                elif src.is_dir():
                    for fpath in src.rglob("*"):
                        if fpath.is_file() and not self._is_excluded(fpath):
                            try:
                                arcname = str(fpath.relative_to(BASE_DIR))
                            except ValueError:
                                try:
                                    arcname = str(fpath.relative_to(src))
                                except ValueError:
                                    arcname = fpath.name
                            zf.write(fpath, arcname)
                            file_count += 1
                            total_bytes += fpath.stat().st_size
            for db in db_files:
                if db.parent == BASE_DIR or any(db.parent == p for p in sources):
                    continue
                if not self._is_excluded(db):
                    try:
                        arcname = str(db.relative_to(BASE_DIR))
                    except ValueError:
                        arcname = db.name
                    zf.write(db, arcname)
                    file_count += 1
                    total_bytes += db.stat().st_size

            info_data = {
                "name": safe_name or ts,
                "created_at": datetime.now(UTC).isoformat(),
                "file_count": file_count,
                "total_bytes": total_bytes,
                "backup_version": "2.0",
            }
            zf.writestr("_backup_info.json", json.dumps(info_data, ensure_ascii=False, indent=2))

        info(f"Backup created: {zip_path} ({file_count} files, {total_bytes} bytes)")
        return {
            "path": str(zip_path),
            "name": safe_name or ts,
            "file_count": file_count,
            "size_bytes": total_bytes,
            "created_at": info_data["created_at"],
        }

    def _is_excluded(self, path: Path) -> bool:
        for part in path.parts:
            if part in EXCLUDE_DIRS:
                return True
        return False

    def list_backups(self) -> list[dict[str, Any]]:
        backups: list[dict[str, Any]] = []
        if not self._backup_dir.exists():
            return backups
        for f in sorted(self._backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.suffix == ".zip" and f.is_file():
                backups.append({
                    "name": f.stem,
                    "path": str(f),
                    "size_bytes": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat(),
                })
        return backups

    def restore_backup(self, backup_name: str) -> bool:
        zip_path = self._backup_dir / f"{backup_name}.zip"
        if not zip_path.exists():
            zip_path = self._backup_dir / backup_name
        if not zip_path.exists() or not zip_path.is_file():
            error(f"Backup not found: {backup_name}")
            return False

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(path=BASE_DIR)
            info(f"Backup restored from {zip_path}")
            return True
        except Exception as exc:
            error(f"Restore failed: {exc}")
            return False

    def prune_backups(self, keep: int = 7) -> int:
        backups = sorted(
            [f for f in self._backup_dir.iterdir() if f.suffix == ".zip" and f.is_file()],
            key=lambda p: p.stat().st_mtime,
        )
        removed = 0
        while len(backups) > keep:
            old = backups.pop(0)
            try:
                old.unlink()
                removed += 1
                info(f"Pruned old backup: {old.name}")
            except Exception as exc:
                warning(f"Failed to prune {old.name}: {exc}")
        return removed

    def get_backup_size(self, backup_name: str) -> int:
        zip_path = self._backup_dir / f"{backup_name}.zip"
        if not zip_path.exists():
            zip_path = self._backup_dir / backup_name
        if zip_path.exists() and zip_path.is_file():
            return zip_path.stat().st_size
        return 0


def fazer_backup() -> Path:
    mgr = BackupManager()
    result = mgr.create_backup()
    return Path(result["path"])


def limpar_antigos() -> int:
    mgr = BackupManager()
    return mgr.prune_backups(keep=MAX_BACKUPS)


def executar() -> dict:
    destino = fazer_backup()
    removidos = limpar_antigos()
    return {
        "destino": str(destino),
        "status": "ok",
        "backups_antigos_removidos": removidos,
    }


def handle_backup(args: Any) -> None:
    mgr = BackupManager()
    if args.backup_action == "create":
        result = mgr.create_backup(name=args.name)
        print(f"Backup created: {result['path']} ({result['file_count']} files, {result['size_bytes']} bytes)")
    elif args.backup_action == "list":
        backups = mgr.list_backups()
        if not backups:
            print("No backups found.")
            return
        print(f"{'Name':<30} {'Size':<12} {'Modified':<30}")
        print("-" * 72)
        for b in backups:
            modified = b["modified"][:19].replace("T", " ")
            size_str = f"{b['size_bytes']:,} bytes"
            print(f"{b['name']:<30} {size_str:<12} {modified}")
    elif args.backup_action == "restore":
        ok = mgr.restore_backup(backup_name=args.name)
        print("Backup restored successfully." if ok else "Restore failed.")
    elif args.backup_action == "prune":
        removed = mgr.prune_backups(keep=args.keep)
        print(f"Pruned {removed} old backup(s). Kept {args.keep} newest.")


def build_parser(subparsers) -> None:
    backup_parser = subparsers.add_parser("backup", help="Compressed backup management for Laura")
    backup_sub = backup_parser.add_subparsers(dest="backup_action", required=True)

    create_p = backup_sub.add_parser("create", help="Create a new compressed backup")
    create_p.add_argument("--name", default="", help="Optional backup name")

    backup_sub.add_parser("list", help="List available backups")

    restore_p = backup_sub.add_parser("restore", help="Restore from a backup")
    restore_p.add_argument("name", help="Backup name (without .zip)")

    prune_p = backup_sub.add_parser("prune", help="Remove old backups")
    prune_p.add_argument("--keep", type=int, default=7, help="Number of newest backups to keep")
