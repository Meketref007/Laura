from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.plugin_system import (
    Plugin,
    PluginManifest,
    PluginManager,
    _parse_version,
    _check_version_compatibility,
    _build_context,
)


class TestPluginManifest:
    def test_minimal(self):
        m = PluginManifest(name="test", version="1.0.0", description="Test plugin")
        assert m.name == "test"
        assert m.hooks == []

    def test_full(self):
        m = PluginManifest(
            name="full", version="2.0.0", description="Full plugin",
            author="me", homepage="https://example.com",
            dependencies=["requests"], min_laura_version="1.5.0",
            hooks=["on_cycle_start"],
        )
        assert m.author == "me"
        assert m.dependencies == ["requests"]


class TestHelpers:
    def test_parse_version(self):
        assert _parse_version("1.2.3") == (1, 2, 3)
        assert _parse_version("1.0") == (1, 0, 0)
        assert _parse_version("2.0.0-beta")[0] == 2

    def test_check_version_compatibility(self):
        assert _check_version_compatibility("0.9.0") is True
        assert _check_version_compatibility("1.0.0") is True
        assert _check_version_compatibility("2.0.0") is False

    def test_build_context(self):
        ctx = _build_context()
        assert "client" in ctx
        assert "config" in ctx
        assert "event_bus" in ctx
        assert "skills" in ctx
        assert "data_dir" in ctx
        assert "logger" in ctx


class TestPluginManager:
    @pytest.fixture
    def manager(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        return PluginManager(plugins_dir=str(plugins_dir))

    def test_discover_plugins_empty_dir(self, manager):
        plugins = manager.discover_plugins()
        assert plugins == []

    def test_discover_plugins_no_dir(self, tmp_path):
        m = PluginManager(plugins_dir=str(tmp_path / "nonexistent"))
        assert m.discover_plugins() == []

    def test_load_plugin_with_test_plugin(self, manager, tmp_path):
        plugin_code = textwrap.dedent("""\
            from shopee_agent.plugin_system import Plugin, PluginManifest

            class TestPlugin(Plugin):
                manifest = PluginManifest(
                    name="test_plugin",
                    version="1.0.0",
                    description="A test plugin",
                )
                loaded = False

                def on_load(self, context):
                    self.loaded = True
                    return True
        """)
        plugin_file = manager._plugins_dir / "test_plugin.py"
        plugin_file.write_text(plugin_code, encoding="utf-8")

        discovered = manager.discover_plugins()
        assert "test_plugin" in discovered
        assert manager.load_plugin("test_plugin") is True
        assert "test_plugin" in manager._loaded
        pl = manager.get_plugin("test_plugin")
        assert pl is not None

    def test_unload_plugin(self, manager):
        mock_instance = MagicMock(spec=Plugin)
        mock_instance.on_load.return_value = True
        mock_manifest = PluginManifest(name="mock_p", version="1.0.0", description="Mock")
        manager._discovered["mock_p"] = {
            "module": MagicMock(), "class": MagicMock(),
            "manifest": mock_manifest, "file": MagicMock(),
        }
        manager._loaded["mock_p"] = mock_instance
        assert manager.unload_plugin("mock_p") is True
        assert "mock_p" not in manager._loaded

    def test_unload_plugin_not_loaded(self, manager):
        assert manager.unload_plugin("unknown") is False

    def test_list_plugins(self, manager):
        manager._discovered["p1"] = {
            "module": MagicMock(), "class": MagicMock(),
            "manifest": PluginManifest(name="p1", version="1.0.0", description="First"),
            "file": MagicMock(),
        }
        manager._discovered["p2"] = {
            "module": MagicMock(), "class": MagicMock(),
            "manifest": PluginManifest(name="p2", version="2.0.0", description="Second"),
            "file": MagicMock(),
        }
        plugins = manager.list_plugins()
        assert len(plugins) == 2
        names = [p["name"] for p in plugins]
        assert "p1" in names
        assert "p2" in names

    def test_call_hook(self, manager):
        mock_instance = MagicMock(spec=Plugin)
        mock_instance.on_load.return_value = True
        mock_instance.on_cycle_start.return_value = None
        manager._loaded["hook_test"] = mock_instance
        results = manager.call_hook("cycle_start", context={"key": "val"})
        assert len(results) == 1
        mock_instance.on_cycle_start.assert_called_once_with(context={"key": "val"})

    def test_call_hook_no_plugins(self, manager):
        assert manager.call_hook("cycle_start") == []

    def test_call_hook_exception(self, manager):
        mock_instance = MagicMock(spec=Plugin)
        mock_instance.on_cycle_start.side_effect = Exception("fail")
        manager._loaded["fail"] = mock_instance
        results = manager.call_hook("cycle_start")
        assert results == [None]

    def test_install_plugin_from_local(self, manager, tmp_path):
        src = tmp_path / "my_plugin.py"
        src.write_text("# plugin code", encoding="utf-8")
        assert manager.install_plugin(str(src)) is True
        dest = manager._plugins_dir / "my_plugin.py"
        assert dest.exists()

    @patch("shopee_agent.plugin_system.urllib.request.urlretrieve")
    def test_install_plugin_from_url(self, mock_retrieve, manager, tmp_path):
        dest = manager._plugins_dir / "plugin.py"
        mock_retrieve.side_effect = lambda url, path: path.write_text("code", encoding="utf-8")
        assert manager.install_plugin("https://example.com/plugin.py") is True
        assert dest.exists()
        assert dest.name == "plugin.py"

    def test_remove_plugin(self, manager):
        plugin_file = manager._plugins_dir / "remove_me.py"
        plugin_file.write_text("code", encoding="utf-8")
        manager._discovered["remove_me"] = {
            "module": MagicMock(), "class": MagicMock(),
            "manifest": PluginManifest(name="remove_me", version="1.0.0", description="x"),
            "file": plugin_file,
        }
        assert manager.remove_plugin("remove_me") is True
        assert plugin_file.exists() is False
        assert "remove_me" not in manager._discovered

    def test_remove_plugin_not_discovered(self, manager):
        assert manager.remove_plugin("ghost") is False

    def test_load_all(self, manager):
        manager._discovered["a"] = {
            "module": MagicMock(), "class": MagicMock(),
            "manifest": PluginManifest(name="a", version="1.0.0", description="x", min_laura_version="0.0.1"),
            "file": MagicMock(),
        }
        count = manager.load_all()
        assert count == 1

    def test_get_enabled_plugins(self, manager):
        m1 = MagicMock(spec=Plugin)
        m2 = MagicMock(spec=Plugin)
        manager._loaded["a"] = m1
        manager._loaded["b"] = m2
        enabled = manager.get_enabled_plugins()
        assert len(enabled) == 2
