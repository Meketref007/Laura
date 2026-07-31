"""Multi-tenancy support — fully isolated shops/stores with thread-safe tenant switching."""

from __future__ import annotations

import json
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Thread-local storage for the currently active tenant ───────────────────

_tlocal = threading.local()


def get_current_tenant() -> str | None:
    """Return the store_id of the currently active tenant in this thread."""
    return getattr(_tlocal, "current_tenant", None)


# ── TenantConfig dataclass ─────────────────────────────────────────────────


@dataclass
class TenantConfig:
    store_id: str
    shop_id: int
    access_token: str
    reports_dir: Path
    secrets_dir: Path
    db_dir: Path
    settings: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = ""
    last_active: str = ""


# ── JSON serialisation helpers ────────────────────────────────────────────


def _config_to_dict(cfg: TenantConfig) -> dict[str, Any]:
    d = asdict(cfg)
    d["reports_dir"] = str(cfg.reports_dir)
    d["secrets_dir"] = str(cfg.secrets_dir)
    d["db_dir"] = str(cfg.db_dir)
    return d


def _config_from_dict(d: dict[str, Any]) -> TenantConfig:
    cfg = TenantConfig(
        store_id=d["store_id"],
        shop_id=d["shop_id"],
        access_token=d["access_token"],
        reports_dir=Path(d["reports_dir"]),
        secrets_dir=Path(d["secrets_dir"]),
        db_dir=Path(d["db_dir"]),
        settings=d.get("settings", {}),
        enabled=d.get("enabled", True),
        created_at=d.get("created_at", ""),
        last_active=d.get("last_active", ""),
    )
    return cfg


# ── TenantManager ─────────────────────────────────────────────────────────


class TenantManager:
    """Persistent multi-tenant manager.

    Each tenant gets an isolated directory under *tenants_dir* with the
    following structure::

        tenants_dir/
          {store_id}/
            config.json          # TenantConfig serialised as JSON
            reports/             # Isolated reports
            secrets/             # Isolated secrets
            data/
              tenant.db          # Isolated SQLite DB
              goap_learning.json
              plan_store.db
    """

    def __init__(self, tenants_dir: str | Path = "tenants") -> None:
        self._tenants_dir = Path(tenants_dir)
        self._tenants_dir.mkdir(parents=True, exist_ok=True)

    # -- public helpers --------------------------------------------------------

    def tenant_dir(self, store_id: str) -> Path:
        """Return the isolated root directory for *store_id*."""
        return self._tenants_dir / store_id

    def config_path(self, store_id: str) -> Path:
        return self.tenant_dir(store_id) / "config.json"

    def reports_dir(self, store_id: str) -> Path:
        return self.tenant_dir(store_id) / "reports"

    def secrets_dir(self, store_id: str) -> Path:
        return self.tenant_dir(store_id) / "secrets"

    def db_dir(self, store_id: str) -> Path:
        return self.tenant_dir(store_id) / "data"

    def db_path(self, store_id: str, db_name: str = "tenant.db") -> Path:
        """Return the path to an isolated database for *store_id*."""
        return self.db_dir(store_id) / db_name

    # -- CRUD ------------------------------------------------------------------

    def register_tenant(self, config: TenantConfig) -> bool:
        """Register a new tenant.

        Creates the directory structure and writes *config.json*.
        Returns ``False`` if the tenant already exists.
        """
        td = self.tenant_dir(config.store_id)
        if td.exists():
            return False

        td.mkdir(parents=True, exist_ok=True)
        (td / "reports").mkdir(exist_ok=True)
        (td / "secrets").mkdir(exist_ok=True)
        (td / "data").mkdir(exist_ok=True)

        now = datetime.now(UTC).isoformat()
        config.reports_dir = config.reports_dir or self.reports_dir(config.store_id)
        config.secrets_dir = config.secrets_dir or self.secrets_dir(config.store_id)
        config.db_dir = config.db_dir or self.db_dir(config.store_id)
        config.created_at = config.created_at or now
        config.last_active = config.last_active or now

        self._write_config(config)
        return True

    def get_tenant(self, store_id: str) -> TenantConfig | None:
        """Load and return the config for *store_id*, or ``None``."""
        path = self.config_path(store_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return _config_from_dict(raw)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def list_tenants(self) -> list[dict[str, Any]]:
        """Return a summary dict for every registered tenant."""
        results: list[dict[str, Any]] = []
        for child in sorted(self._tenants_dir.iterdir()):
            if not child.is_dir():
                continue
            cfg = self.get_tenant(child.name)
            if cfg is None:
                continue
            results.append({
                "store_id": cfg.store_id,
                "shop_id": cfg.shop_id,
                "enabled": cfg.enabled,
                "created_at": cfg.created_at,
                "last_active": cfg.last_active,
                "settings_count": len(cfg.settings),
                "reports_dir": str(cfg.reports_dir),
                "secrets_dir": str(cfg.secrets_dir),
                "db_dir": str(cfg.db_dir),
            })
        return results

    def remove_tenant(self, store_id: str) -> bool:
        """Delete all data for *store_id*.  Returns ``False`` if it does not exist."""
        td = self.tenant_dir(store_id)
        if not td.is_dir():
            return False
        shutil.rmtree(td)
        return True

    # -- enable / disable ------------------------------------------------------

    def enable_tenant(self, store_id: str) -> bool:
        return self._set_enabled(store_id, True)

    def disable_tenant(self, store_id: str) -> bool:
        return self._set_enabled(store_id, False)

    # -- internal helpers ------------------------------------------------------

    def _write_config(self, config: TenantConfig) -> None:
        path = self.config_path(config.store_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_config_to_dict(config), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _set_enabled(self, store_id: str, enabled: bool) -> bool:
        cfg = self.get_tenant(store_id)
        if cfg is None:
            return False
        cfg.enabled = enabled
        self._write_config(cfg)
        return True


# ── TenantContext (thread-safe context manager) ───────────────────────────


class TenantContext:
    """Context manager that sets the active tenant for the current thread.

    Usage::

        with TenantContext(manager, "shop_123"):
            assert get_current_tenant() == "shop_123"
            # … all operations are scoped to shop_123
    """

    def __init__(self, manager: TenantManager, store_id: str) -> None:
        self._manager = manager
        self._store_id = store_id
        self._previous: str | None = None

    def __enter__(self) -> TenantConfig:
        cfg = self._manager.get_tenant(self._store_id)
        if cfg is None:
            raise ValueError(
                f"Tenant '{self._store_id}' is not registered. "
                f"Call manager.register_tenant(...) first."
            )
        if not cfg.enabled:
            raise RuntimeError(f"Tenant '{self._store_id}' is disabled.")
        self._previous = get_current_tenant()
        _tlocal.current_tenant = self._store_id
        return cfg

    def __exit__(self, *exc: Any) -> None:
        _tlocal.current_tenant = self._previous


# ═══════════════════════════════════════════════════════════════════════════
# CLI integration hints
# ═══════════════════════════════════════════════════════════════════════════
#
# These classes are designed to be used from the Laura CLI (or any other
# entry-point) as follows:
#
# 1. Initialise a global TenantManager early in the startup::
#
#        manager = TenantManager("tenants")
#
# 2. Register shops when they are first linked::
#
#        cfg = TenantConfig(
#            store_id="shop_123",
#            shop_id=456,
#            access_token="...",
#            reports_dir=...,       # optional — auto-computed if omitted
#            secrets_dir=...,       # optional
#            db_dir=...,            # optional
#            settings={"lang": "pt_BR"},
#        )
#        manager.register_tenant(cfg)
#
# 3. Wrap every store-scoped operation in a TenantContext::
#
#        with TenantContext(manager, store_id):
#            # get_current_tenant() == store_id
#            planner = GOAPPlanner(
#                learning_path=str(
#                    manager.db_dir(store_id) / "goap_learning.json"
#                )
#            )
#            ...
#
# 4. CLI commands (click / argparse) accept ``--store`` / ``-s``::
#
#        @cli.command()
#        @click.option("-s", "--store", required=True)
#        def run(store: str):
#            manager = TenantManager()
#            with TenantContext(manager, store):
#                ...
#
# 5. Use ``get_current_tenant()`` anywhere deep in the call stack to obtain
#    the active store_id without threading it through every parameter.
