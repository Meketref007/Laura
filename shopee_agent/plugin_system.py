"""
Third-party plugin system for Laura.

Plugins are Python files placed in a ``plugins/`` directory (relative to the
project root, or an absolute path). Each file should define a class that
inherits from ``Plugin`` and sets a ``manifest`` attribute.

Usage::

    manager = PluginManager()
    manager.discover_plugins()
    manager.load_all()
    manager.call_hook("on_cycle_start", context=ctx)

Example plugin saved to ``plugins/my_plugin.py``::

    from shopee_agent.plugin_system import Plugin, PluginManifest

    class MyPlugin(Plugin):
        manifest = PluginManifest(
            name="my_plugin",
            version="1.0.0",
            description="Example plugin that logs every cycle.",
        )

        def on_load(self, context):
            print(f"{self.manifest.name} loaded")
            return True

        def on_cycle_start(self, context):
            print(f"Cycle started with {len(context.get('skills', []))} skills")
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shopee_agent.logger import error, info, warning
from shopee_agent.paths import BASE_DIR, REPORTS_DIR

# ── Public API ──────────────────────────────────────────────────────────────

PLUGINS_STATE_FILE = REPORTS_DIR / "plugins_state.json"


@dataclass
class PluginManifest:
    """Metadata describing a plugin's identity, requirements, and capabilities."""

    name: str
    version: str
    description: str
    author: str = ""
    homepage: str = ""
    dependencies: list[str] = field(default_factory=list)
    min_laura_version: str = "1.0.0"
    hooks: list[str] = field(default_factory=list)


class Plugin(ABC):
    """Base class that all Laura plugins must subclass."""

    manifest: PluginManifest

    @abstractmethod
    def on_load(self, context: dict) -> bool:
        """Called when the plugin is loaded.

        Return ``True`` to confirm loading, or ``False`` to abort.
        """
        ...

    def on_unload(self) -> None:
        """Called when the plugin is unloaded (cleanup resources)."""

    def on_cycle_start(self, context: dict) -> None:
        """Called at the beginning of every daemon / autonomous cycle."""

    def on_cycle_end(self, context: dict, result: dict) -> None:
        """Called at the end of every daemon / autonomous cycle."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_LAURA_VERSION: str = "1.0.0"  # bump when the core plugin contract changes


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Convert a semver-like string ``"1.2.3"`` to a comparable tuple."""
    parts = version_str.replace("-", ".").split(".")
    cleaned = []
    for p in parts:
        try:
            cleaned.append(int(p))
        except ValueError:
            cleaned.append(0)
    # Pad to at least 3 elements (major.minor.patch)
    while len(cleaned) < 3:
        cleaned.append(0)
    return tuple(cleaned)


def _check_version_compatibility(min_required: str) -> bool:
    """Return ``True`` when ``_LAURA_VERSION >= min_required``."""
    return _parse_version(_LAURA_VERSION) >= _parse_version(min_required)


def _build_context() -> dict:
    """Return a default context dict passed to plugin hooks.

    Callers may enrich this with additional keys before passing it to plugins.
    """
    return {
        "client": None,
        "config": {},
        "event_bus": None,
        "skills": [],
        "data_dir": str(REPORTS_DIR),
        "logger": info,
    }


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------


class PluginManager:
    """Discovers, loads, unloads, and manages third-party plugins."""

    def __init__(self, plugins_dir: str = "plugins"):
        self._plugins_dir: Path = Path(plugins_dir)
        if not self._plugins_dir.is_absolute():
            self._plugins_dir = BASE_DIR / self._plugins_dir

        # name -> {"module": module, "class": type, "manifest": PluginManifest, "file": Path}
        self._discovered: dict[str, dict] = {}

        # name -> Plugin instance
        self._loaded: dict[str, Plugin] = {}

        self._plugins_state_file: Path = PLUGINS_STATE_FILE

        # Ensure state directory exists
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # -- Discovery -----------------------------------------------------------

    def discover_plugins(self) -> list[str]:
        """Scan *plugins_dir* for ``.py`` files and find ``Plugin`` subclasses.

        Returns a list of plugin *names* that were found.
        """
        self._discovered.clear()

        plugins_dir = self._plugins_dir
        if not plugins_dir.is_dir():
            info("Plugin directory not found, skipping discovery", path=str(plugins_dir))
            return []

        py_files = sorted(plugins_dir.glob("*.py"))

        for py_file in py_files:
            if py_file.name == "__init__.py":
                continue

            name = py_file.stem  # filename without extension

            try:
                spec = importlib.util.spec_from_file_location(name, py_file)
                if spec is None or spec.loader is None:
                    warning("Could not load spec for plugin", file=str(py_file))
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as exc:
                warning("Failed to import plugin file", file=str(py_file), error=str(exc))
                continue

            # Look for classes that are concrete subclasses of Plugin
            plugin_cls = None
            manifest = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Plugin)
                    and attr is not Plugin
                ):
                    plugin_cls = attr
                    manifest = getattr(attr, "manifest", None)
                    if manifest is None:
                        # Try an instance default
                        try:
                            manifest = attr.manifest
                        except AttributeError:
                            warning(
                                "Plugin class missing manifest attribute",
                                class_name=attr_name,
                                file=str(py_file),
                            )
                            continue
                    break  # use first Plugin subclass found

            if plugin_cls is None or manifest is None:
                warning(
                    "No valid Plugin subclass found in file",
                    file=str(py_file),
                )
                continue

            if not isinstance(manifest, PluginManifest):
                warning(
                    "Plugin manifest is not a PluginManifest instance",
                    file=str(py_file),
                )
                continue

            self._discovered[name] = {
                "module": module,
                "class": plugin_cls,
                "manifest": manifest,
                "file": py_file,
            }

            info("Discovered plugin", name=name, version=manifest.version)

        return list(self._discovered.keys())

    # -- Loading / unloading -------------------------------------------------

    def load_plugin(self, name: str) -> bool:
        """Load (instantiate and call ``on_load``) a specific discovered plugin.

        Returns ``True`` on success.
        """
        if name in self._loaded:
            info("Plugin already loaded", name=name)
            return True

        entry = self._discovered.get(name)
        if entry is None:
            warning("Plugin not discovered, cannot load", name=name)
            return False

        manifest: PluginManifest = entry["manifest"]

        # Version compatibility check
        if not _check_version_compatibility(manifest.min_laura_version):
            warning(
                "Plugin requires newer Laura version",
                plugin=name,
                required=manifest.min_laura_version,
                current=_LAURA_VERSION,
            )
            return False

        plugin_cls = entry["class"]
        try:
            instance: Plugin = plugin_cls()
        except Exception as exc:
            error("Failed to instantiate plugin", name=name, error=str(exc))
            return False

        context = _build_context()
        try:
            ok = instance.on_load(context)
        except Exception as exc:
            error("Plugin on_load raised exception", name=name, error=str(exc))
            return False

        if not ok:
            info("Plugin declined loading (on_load returned False)", name=name)
            return False

        self._loaded[name] = instance
        info("Plugin loaded", name=name, version=manifest.version)
        self._persist_state()
        return True

    def unload_plugin(self, name: str) -> bool:
        """Unload a previously loaded plugin.

        Returns ``True`` if the plugin was found and unloaded.
        """
        instance = self._loaded.pop(name, None)
        if instance is None:
            warning("Plugin not loaded, cannot unload", name=name)
            return False

        try:
            instance.on_unload()
        except Exception as exc:
            warning("Plugin on_unload raised exception", name=name, error=str(exc))

        info("Plugin unloaded", name=name)
        self._persist_state()
        return True

    def load_all(self) -> int:
        """Load every discovered plugin.

        Returns the number of plugins successfully loaded.
        """
        count = 0
        for name in list(self._discovered.keys()):
            if self.load_plugin(name):
                count += 1
        info("Plugin load_all complete", loaded=count, total=len(self._discovered))
        return count

    # -- Accessors -----------------------------------------------------------

    def get_plugin(self, name: str) -> Plugin | None:
        """Return the loaded ``Plugin`` instance by name, or ``None``."""
        return self._loaded.get(name)

    def list_plugins(self) -> list[dict]:
        """Return metadata for all discovered plugins.

        Each dict contains: ``name``, ``version``, ``description``, ``author``,
        ``homepage``, ``dependencies``, ``hooks``, ``loaded``.
        """
        results: list[dict] = []
        for name, entry in self._discovered.items():
            m: PluginManifest = entry["manifest"]
            results.append(
                {
                    "name": m.name,
                    "version": m.version,
                    "description": m.description,
                    "author": m.author,
                    "homepage": m.homepage,
                    "dependencies": list(m.dependencies),
                    "hooks": list(m.hooks),
                    "loaded": name in self._loaded,
                }
            )
        return results

    def get_enabled_plugins(self) -> list[Plugin]:
        """Return all currently loaded/enabled ``Plugin`` instances."""
        return list(self._loaded.values())

    # -- Hooks ---------------------------------------------------------------

    def call_hook(self, hook_name: str, **kwargs: Any) -> list:
        """Invoke *hook_name* on every loaded plugin that defines it.

        Any extra keyword arguments are forwarded to the hook method.
        Returns a list of return values (one per plugin that handled the hook).
        """
        results: list = []
        method_name = f"on_{hook_name}" if not hook_name.startswith("on_") else hook_name
        for name, instance in list(self._loaded.items()):
            handler = getattr(instance, method_name, None)
            if handler is None or not callable(handler):
                continue
            # Skip abstract (unimplemented) hooks – the base Plugin class
            # provides default no-op implementations, so we always call.
            try:
                result = handler(**kwargs)
                results.append(result)
            except Exception as exc:
                warning(
                    "Plugin hook raised exception",
                    plugin=name,
                    hook=method_name,
                    error=str(exc),
                )
                results.append(None)
        return results

    # -- Installation / removal ----------------------------------------------

    def install_plugin(self, source: str) -> bool:
        """Install a plugin from a URL or local file path.

        The source is downloaded / copied into the plugins directory.
        Returns ``True`` on success.
        """
        plugins_dir = self._plugins_dir
        plugins_dir.mkdir(parents=True, exist_ok=True)

        source = source.strip()

        # Determine destination filename
        if source.startswith(("http://", "https://", "ftp://")):
            dest_name = source.rstrip("/").rsplit("/", 1)[-1]
            if not dest_name.endswith(".py"):
                dest_name += ".py"
            dest_path = plugins_dir / dest_name
            try:
                info("Downloading plugin from URL", url=source, dest=str(dest_path))
                urllib.request.urlretrieve(source, dest_path)
            except Exception as exc:
                error("Failed to download plugin", url=source, error=str(exc))
                return False
        else:
            src_path = Path(source)
            if not src_path.exists():
                error("Plugin source file not found", path=source)
                return False
            dest_path = plugins_dir / src_path.name
            try:
                shutil.copy2(str(src_path), str(dest_path))
            except Exception as exc:
                error("Failed to copy plugin", src=source, dest=str(dest_path), error=str(exc))
                return False

        info("Plugin installed", source=source, dest=str(dest_path))

        # Try to discover the newly installed plugin immediately
        before = set(self._discovered.keys())
        self.discover_plugins()
        after = set(self._discovered.keys())
        new = after - before
        if new:
            for n in new:
                info("Newly installed plugin discovered", name=n)

        return True

    def remove_plugin(self, name: str) -> bool:
        """Remove (delete) a plugin file from the filesystem.

        The plugin is unloaded first if it is currently loaded.
        Returns ``True`` on success.
        """
        # Unload if loaded
        if name in self._loaded:
            self.unload_plugin(name)

        entry = self._discovered.pop(name, None)
        if entry is None:
            warning("Plugin not found in discovered list", name=name)
            return False

        plugin_file: Path = entry["file"]
        try:
            plugin_file.unlink(missing_ok=True)
        except Exception as exc:
            error("Failed to delete plugin file", file=str(plugin_file), error=str(exc))
            return False

        info("Plugin removed", name=name, file=str(plugin_file))
        self._persist_state()
        return True

    # -- Persistence ---------------------------------------------------------

    def _persist_state(self) -> None:
        """Save the list of currently enabled plugin names to disk."""
        enabled = list(self._loaded.keys())
        try:
            self._plugins_state_file.write_text(
                json.dumps({"enabled_plugins": enabled, "_version": _LAURA_VERSION}, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            warning("Failed to persist plugin state", error=str(exc))

    def _load_state(self) -> list[str]:
        """Load the previously enabled plugin names from disk."""
        try:
            data = json.loads(self._plugins_state_file.read_text(encoding="utf-8"))
            return data.get("enabled_plugins", [])
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            return []

    def restore_enabled_plugins(self) -> int:
        """Re-enable plugins that were enabled in the last session.

        Returns the number of successfully restored plugins.
        """
        enabled_names = self._load_state()
        if not enabled_names:
            return 0

        count = 0
        for name in enabled_names:
            if name in self._discovered and name not in self._loaded:
                if self.load_plugin(name):
                    count += 1
        info("Restored enabled plugins from previous session", restored=count, total=len(enabled_names))
        return count
