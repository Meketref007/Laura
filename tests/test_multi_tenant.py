"""Tests for multi-tenancy support."""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


@pytest.fixture
def manager(tmp_path):
    from shopee_agent.multi_tenant import TenantManager
    return TenantManager(tenants_dir=str(tmp_path / "tenants"))


def test_tenant_config():
    from shopee_agent.multi_tenant import TenantConfig
    from pathlib import Path
    cfg = TenantConfig(
        store_id="shop_001",
        shop_id=12345,
        access_token="tok_abc",
        reports_dir=Path("/tmp/reports"),
        secrets_dir=Path("/tmp/secrets"),
        db_dir=Path("/tmp/data"),
        settings={"lang": "pt_BR"},
    )
    assert cfg.store_id == "shop_001"
    assert cfg.shop_id == 12345
    assert cfg.access_token == "tok_abc"
    assert cfg.enabled is True


def test_tenant_manager_register(manager):
    from shopee_agent.multi_tenant import TenantConfig
    from pathlib import Path
    cfg = TenantConfig(
        store_id="shop_001",
        shop_id=12345,
        access_token="tok_abc",
        reports_dir=Path(""),
        secrets_dir=Path(""),
        db_dir=Path(""),
    )
    result = manager.register_tenant(cfg)
    assert result is True
    assert manager.register_tenant(cfg) is False  # duplicate


def test_tenant_manager_get(manager):
    from shopee_agent.multi_tenant import TenantConfig
    from pathlib import Path
    cfg = TenantConfig(
        store_id="shop_002",
        shop_id=67890,
        access_token="tok_xyz",
        reports_dir=Path(""),
        secrets_dir=Path(""),
        db_dir=Path(""),
    )
    manager.register_tenant(cfg)
    loaded = manager.get_tenant("shop_002")
    assert loaded is not None
    assert loaded.shop_id == 67890
    assert loaded.access_token == "tok_xyz"
    assert manager.get_tenant("nonexistent") is None


def test_tenant_manager_remove(manager):
    from shopee_agent.multi_tenant import TenantConfig
    from pathlib import Path
    cfg = TenantConfig(
        store_id="shop_003",
        shop_id=11111,
        access_token="tok_remove",
        reports_dir=Path(""),
        secrets_dir=Path(""),
        db_dir=Path(""),
    )
    manager.register_tenant(cfg)
    assert manager.remove_tenant("shop_003") is True
    assert manager.get_tenant("shop_003") is None
    assert manager.remove_tenant("nonexistent") is False


def test_tenant_manager_list(manager):
    from shopee_agent.multi_tenant import TenantConfig
    from pathlib import Path
    for i in range(3):
        manager.register_tenant(TenantConfig(
            store_id=f"shop_{i:03d}",
            shop_id=10000 + i,
            access_token=f"tok_{i}",
            reports_dir=Path(""),
            secrets_dir=Path(""),
            db_dir=Path(""),
        ))
    tenants = manager.list_tenants()
    assert len(tenants) == 3
    store_ids = [t["store_id"] for t in tenants]
    assert "shop_000" in store_ids
    assert "shop_002" in store_ids


def test_enable_disable_tenant(manager):
    from shopee_agent.multi_tenant import TenantConfig
    from pathlib import Path
    manager.register_tenant(TenantConfig(
        store_id="shop_toggle",
        shop_id=99999,
        access_token="tok_toggle",
        reports_dir=Path(""),
        secrets_dir=Path(""),
        db_dir=Path(""),
    ))
    assert manager.disable_tenant("shop_toggle") is True
    cfg = manager.get_tenant("shop_toggle")
    assert cfg is not None
    assert cfg.enabled is False
    assert manager.enable_tenant("shop_toggle") is True
    cfg2 = manager.get_tenant("shop_toggle")
    assert cfg2.enabled is True
    assert manager.disable_tenant("nonexistent") is False


def test_tenant_context(manager):
    from shopee_agent.multi_tenant import TenantConfig, TenantContext, get_current_tenant
    from pathlib import Path
    manager.register_tenant(TenantConfig(
        store_id="ctx_shop",
        shop_id=55555,
        access_token="tok_ctx",
        reports_dir=Path(""),
        secrets_dir=Path(""),
        db_dir=Path(""),
    ))
    assert get_current_tenant() is None
    with TenantContext(manager, "ctx_shop") as cfg:
        assert get_current_tenant() == "ctx_shop"
        assert cfg.shop_id == 55555
    assert get_current_tenant() is None


def test_tenant_persistence(tmp_path):
    from shopee_agent.multi_tenant import TenantManager, TenantConfig, _config_from_dict
    from pathlib import Path
    mgr = TenantManager(tenants_dir=str(tmp_path / "tenants"))
    mgr.register_tenant(TenantConfig(
        store_id="persist_shop",
        shop_id=77777,
        access_token="tok_persist",
        reports_dir=Path(""),
        secrets_dir=Path(""),
        db_dir=Path(""),
    ))
    mgr2 = TenantManager(tenants_dir=str(tmp_path / "tenants"))
    loaded = mgr2.get_tenant("persist_shop")
    assert loaded is not None
    assert loaded.shop_id == 77777
    assert loaded.access_token == "tok_persist"
