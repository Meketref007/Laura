"""Plugin marketplace — discover, install, and manage plugins from remote sources."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from shopee_agent.logger import error, info, warning
from shopee_agent.plugin_system import PluginManager


class PluginMarketplaceError(Exception):
    """Base exception for marketplace operations."""


class RegistryUnreachableError(PluginMarketplaceError):
    """Raised when the remote plugin registry cannot be reached."""


class PluginNotFoundError(PluginMarketplaceError):
    """Raised when a plugin is not found in the registry."""


class PluginMarketplace:
    """Discover, install, and manage plugins from remote sources."""

    def __init__(
        self,
        registry_url: str = "https://raw.githubusercontent.com/anomalyco/laura-plugins/main/registry.json",
        cache_dir: str = "reports/plugin_cache",
    ):
        self._registry_url = registry_url
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._registry_cache_path = self._cache_dir / "registry_cache.json"
        self._plugin_manager = PluginManager()

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def _fetch_registry(self) -> list[dict]:
        """Fetch the remote registry JSON, falling back to a cached copy."""
        # Try remote first
        try:
            req = urllib.request.Request(
                self._registry_url,
                headers={"User-Agent": "Laura/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data: list[dict] = json.loads(resp.read().decode("utf-8"))
                # Cache locally for offline use
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._registry_cache_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            info("Remote registry unreachable, trying local cache", error=str(exc)[:100])
            return self._load_registry_cache()

    def _load_registry_cache(self) -> list[dict]:
        """Load the locally cached registry."""
        try:
            if self._registry_cache_path.exists():
                return json.loads(self._registry_cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            warning("Failed to load registry cache", error=str(exc)[:100])
        return []

    def _find_in_registry(self, plugin_name: str, registry: list[dict]) -> dict | None:
        """Find a plugin by name in the registry list."""
        for entry in registry:
            if entry.get("name", "").lower() == plugin_name.lower():
                return entry
            # Also match by filename without .py
            filename = entry.get("file", "")
            if Path(filename).stem.lower() == plugin_name.lower():
                return entry
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_available(self) -> list[dict]:
        """List all available plugins from the remote registry."""
        return self._fetch_registry()

    def search(self, query: str) -> list[dict]:
        """Search available plugins by name, description, or author."""
        q = query.lower()
        registry = self._fetch_registry()
        results = []
        for entry in registry:
            name = entry.get("name", "").lower()
            description = entry.get("description", "").lower()
            author = entry.get("author", "").lower()
            tags = [t.lower() for t in entry.get("tags", [])]
            if (
                q in name
                or q in description
                or q in author
                or any(q in t for t in tags)
            ):
                results.append(entry)
        return results

    def get_info(self, plugin_name: str) -> dict:
        """Get plugin info from the registry."""
        registry = self._fetch_registry()
        entry = self._find_in_registry(plugin_name, registry)
        if entry is None:
            raise PluginNotFoundError(f"Plugin '{plugin_name}' not found in registry")
        return entry

    def install(self, plugin_name: str, source: str = "") -> bool:
        """Download and install a plugin from the registry or a custom source URL.

        If *source* is provided, it is used directly as the download URL.
        Otherwise the registry is consulted to find the plugin's download URL.
        """
        if source:
            url = source
        else:
            registry = self._fetch_registry()
            entry = self._find_in_registry(plugin_name, registry)
            if entry is None:
                error("Plugin not found in registry", name=plugin_name)
                return False
            url = entry.get("download_url") or entry.get("source", "")

        if not url:
            error("No source URL available for plugin", name=plugin_name)
            return False

        info("Installing plugin from URL", name=plugin_name, url=url)
        return self._plugin_manager.install_plugin(url)

    def uninstall(self, plugin_name: str) -> bool:
        """Remove a plugin that was previously installed."""
        info("Uninstalling plugin", name=plugin_name)
        return self._plugin_manager.remove_plugin(plugin_name)

    def update(self, plugin_name: str) -> bool:
        """Update a plugin to the latest version by re-downloading it."""
        info("Updating plugin", name=plugin_name)
        # Uninstall first (removes the file)
        self._plugin_manager.remove_plugin(plugin_name)
        # Re-install from registry
        return self.install(plugin_name)

    def list_installed(self) -> list[dict]:
        """List currently installed plugins (delegates to PluginManager)."""
        return self._plugin_manager.list_plugins()


# ------------------------------------------------------------------
# CLI integration
# ------------------------------------------------------------------


def build_parser(subparsers) -> None:
    """Add the ``laura plugin`` subcommand tree to *subparsers*."""
    parser = subparsers.add_parser(
        "plugin",
        help="Plugin marketplace — discover, install, and manage plugins",
    )
    plugin_sub = parser.add_subparsers(dest="plugin_action", required=True)

    # plugin search
    search_parser = plugin_sub.add_parser("search", help="Search available plugins")
    search_parser.add_argument("query", help="Search term (matched against name, description, author, tags)")

    # plugin list
    plugin_sub.add_parser("list", help="List all available plugins from the registry")

    # plugin install
    install_parser = plugin_sub.add_parser("install", help="Install a plugin")
    install_parser.add_argument("name", help="Plugin name")
    install_parser.add_argument("--source", default="", help="Custom download URL (overrides registry)")

    # plugin uninstall
    uninstall_parser = plugin_sub.add_parser("uninstall", help="Uninstall a plugin")
    uninstall_parser.add_argument("name", help="Plugin name")

    # plugin update
    update_parser = plugin_sub.add_parser("update", help="Update a plugin to the latest version")
    update_parser.add_argument("name", help="Plugin name")

    # plugin info
    info_parser = plugin_sub.add_parser("info", help="Get detailed plugin info from the registry")
    info_parser.add_argument("name", help="Plugin name")

    # plugin installed
    plugin_sub.add_parser("installed", help="List currently installed plugins")


def handle_plugin_command(args) -> int:
    """Dispatch plugin subcommands."""
    marketplace = PluginMarketplace()

    try:
        if args.plugin_action == "search":
            results = marketplace.search(args.query)
            if not results:
                print(f"No plugins found matching '{args.query}'")
                return 0
            print(f"Found {len(results)} plugin(s) matching '{args.query}':")
            for p in results:
                print(f"  {p.get('name'):<25} {p.get('version', '-'):<10} {p.get('description', '')}")
            return 0

        elif args.plugin_action == "list":
            plugins = marketplace.list_available()
            if not plugins:
                print("No plugins available (registry unreachable or empty).")
                return 0
            print(f"Available plugins ({len(plugins)}):")
            for p in plugins:
                print(f"  {p.get('name'):<25} {p.get('version', '-'):<10} {p.get('description', '')}")
            return 0

        elif args.plugin_action == "install":
            ok = marketplace.install(args.name, source=args.source)
            if ok:
                print(f"Plugin '{args.name}' installed successfully.")
                return 0
            else:
                print(f"Failed to install plugin '{args.name}'.")
                return 1

        elif args.plugin_action == "uninstall":
            ok = marketplace.uninstall(args.name)
            if ok:
                print(f"Plugin '{args.name}' uninstalled successfully.")
                return 0
            else:
                print(f"Failed to uninstall plugin '{args.name}' (not found?).")
                return 1

        elif args.plugin_action == "update":
            ok = marketplace.update(args.name)
            if ok:
                print(f"Plugin '{args.name}' updated successfully.")
                return 0
            else:
                print(f"Failed to update plugin '{args.name}'.")
                return 1

        elif args.plugin_action == "info":
            try:
                info = marketplace.get_info(args.name)
                print(json.dumps(info, ensure_ascii=False, indent=2))
            except PluginNotFoundError as e:
                print(str(e))
                return 1
            return 0

        elif args.plugin_action == "installed":
            installed = marketplace.list_installed()
            if not installed:
                print("No plugins installed.")
                return 0
            print(f"Installed plugins ({len(installed)}):")
            for p in installed:
                status = "loaded" if p.get("loaded") else "discovered"
                print(f"  {p.get('name'):<25} {p.get('version', '-'):<10} [{status}]")
            return 0

    except RegistryUnreachableError as e:
        print(f"Registry error: {e}")
        return 1
    except PluginMarketplaceError as e:
        print(f"Marketplace error: {e}")
        return 1

    return 1
