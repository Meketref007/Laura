"""Laura Plugin SDK — public API for third-party plugin developers.

Usage:
    from shopee_agent.plugin_sdk import (
        PluginBase, PluginMetadata, hook, laura_api,
        Event, Context, ActionResult
    )

    class MyPlugin(PluginBase):
        metadata = PluginMetadata(
            name="my-plugin",
            version="1.0.0",
            description="My awesome plugin",
            author="Developer",
            license="MIT",
        )

        @hook("order.created")
        def on_order_created(self, event: Event, ctx: Context) -> ActionResult:
            ...
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, ClassVar

import requests

from shopee_agent.logger import error as _log_error
from shopee_agent.logger import info as _log_info
from shopee_agent.plugin_system import PluginManifest, _check_version_compatibility

# ── Public data types ────────────────────────────────────────────────────────


@dataclass
class PluginMetadata:
    """Metadata describing a plugin's identity and requirements.

    Fields
    ------
    name : str
        Unique plugin identifier (e.g. ``"my-plugin"``).
    version : str
        Semantic version string (e.g. ``"1.0.0"``).
    description : str
        Short human-readable description of what the plugin does.
    author : str
        Author name or organisation.
    license : str
        SPDX license identifier (default ``"MIT"``).
    homepage : str
        URL to the plugin's project page.
    tags : list[str]
        List of searchable tags / keywords.
    min_laura_version : str
        Minimum Laura version required (default ``"1.0.0"``).
    """

    name: str
    version: str
    description: str
    author: str
    license: str = "MIT"
    homepage: str = ""
    tags: list[str] = field(default_factory=list)
    min_laura_version: str = "1.0.0"


@dataclass
class Event:
    """An event that triggers plugin hooks.

    Fields
    ------
    type : str
        Event type identifier (e.g. ``"order.created"``).
    data : dict
        Arbitrary event payload.
    timestamp : float
        Unix timestamp when the event was produced.
    source : str
        Origin of the event (default ``"system"``).
    """

    type: str
    data: dict[str, Any]
    timestamp: float
    source: str = "system"


@dataclass
class Context:
    """Runtime context passed to every hook invocation.

    Fields
    ------
    store_id : str | None
        Active store identifier, if any.
    config : dict
        Plugin-specific configuration values.
    logger : logging.Logger
        Logger instance scoped to the current plugin.
    api : LauraAPI
        :class:`LauraAPI` instance for safe access to Laura internals.
    """

    store_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    logger: Any = None
    api: LauraAPI | None = None


@dataclass
class ActionResult:
    """Standard return type for hook handlers.

    Fields
    ------
    success : bool
        Whether the handler completed successfully.
    message : str
        Human-readable result description.
    data : dict
        Arbitrary result data returned to the caller.
    error : str | None
        Error message if *success* is ``False``.
    """

    success: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ── LauraAPI — safe access to Laura internals ────────────────────────────────


class LauraAPI:
    """Provides safe, controlled access to Laura's internal services.

    Every :class:`PluginBase` instance receives a ``LauraAPI`` object via
    :attr:`Context.api` that plugins can use to interact with the host system
    without depending on internal Laura modules directly.
    """

    def __init__(self, plugin_name: str) -> None:
        self._plugin_name = plugin_name
        self._store: dict[str, Any] = {}
        self._logger = logging.getLogger(f"laura.plugin.{plugin_name}")

    # ── Configuration ────────────────────────────────────────────────────

    def get_config(self, key: str) -> Any:
        """Return the current value of a plugin configuration key."""
        return self._store.get(f"config:{key}")

    def set_config(self, key: str, value: Any) -> None:
        """Persist a plugin configuration value for the current session."""
        self._store[f"config:{key}"] = value

    # ── Event bus ────────────────────────────────────────────────────────

    def emit_event(self, event: Event) -> None:
        """Emit an event into the Laura event bus.

        Other plugins (or Laura itself) listening for ``event.type`` will
        have their matching hooks invoked.
        """
        from shopee_agent.event_bus import get_event_bus

        bus = get_event_bus()
        bus.emit(event.type, data=event.data, source=event.source)

    # ── Logging ──────────────────────────────────────────────────────────

    def log_info(self, msg: str) -> None:
        """Log an info-level message attributed to this plugin."""
        _log_info(f"[{self._plugin_name}] {msg}")

    def log_error(self, msg: str) -> None:
        """Log an error-level message attributed to this plugin."""
        _log_error(f"[{self._plugin_name}] {msg}")

    # ── Persistent key-value store ───────────────────────────────────────

    def store_get(self, key: str, default: Any = None) -> Any:
        """Read a value from the plugin's persistent key-value store."""
        return self._store.get(key, default)

    def store_set(self, key: str, value: Any) -> None:
        """Write a value to the plugin's persistent key-value store."""
        self._store[key] = value

    # ── Rate-limited HTTP helpers ────────────────────────────────────────

    def http_get(self, url: str, headers: dict[str, str] | None = None) -> requests.Response:
        """Perform a rate-limited HTTP GET request."""
        session = self._http_session()
        return session.get(url, headers=headers, timeout=30)

    def http_post(
        self, url: str, json: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        """Perform a rate-limited HTTP POST request."""
        session = self._http_session()
        return session.post(url, json=json, headers=headers, timeout=30)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _http_session(self) -> requests.Session:
        """Return (or create) a rate-limited ``requests.Session``."""
        session = getattr(self, "_session", None)
        if session is None:
            session = requests.Session()
            session.headers.setdefault("User-Agent", f"LauraPlugin/{self._plugin_name}")
            object.__setattr__(self, "_session", session)
        return session


# ── PluginBase ───────────────────────────────────────────────────────────────


class PluginBase(ABC):
    """Abstract base class that all third-party Laura plugins must subclass.

    Example::

        class MyPlugin(PluginBase):
            metadata = PluginMetadata(
                name="my-plugin",
                version="1.0.0",
                description="Example plugin",
                author="Developer",
            )

            @hook("order.created")
            def on_order_created(self, event: Event, ctx: Context) -> ActionResult:
                ctx.api.log_info(f"Order {event.data.get('id')} created!")
                return ActionResult(success=True)
    """

    metadata: ClassVar[PluginMetadata]
    api: LauraAPI

    def __init__(self) -> None:
        self.api = LauraAPI(self.metadata.name)

    def on_load(self, ctx: Context) -> None:
        """Called when the plugin is loaded into the Laura runtime.

        Override this to perform initialisation that requires access to
        :class:`Context` (configuration, logger, API handle).

        Raises :class:`PluginLoadError` to abort loading.
        """

    def on_unload(self) -> None:
        """Called when the plugin is being unloaded.

        Override this to release resources (close files, stop threads,
        flush buffers, etc.).
        """

    def on_install(self) -> None:
        """Called once when the plugin is first installed.

        Use this for one-time setup such as creating database tables or
        registering default configuration values.
        """

    def on_upgrade(self, old_version: str) -> None:
        """Called after the plugin has been upgraded from *old_version*.

        Override this to perform data migrations or configuration changes
        when the plugin version changes.
        """

    @classmethod
    def discover_hooks(cls) -> dict[str, list[str]]:
        """Return a mapping of hook names to method names.

        Scans the class (and its ancestors) for methods decorated with
        ``@hook`` and returns ``{event_type: [method_name, ...]}``.
        """
        hooks: dict[str, list[str]] = {}
        for attr_name in dir(cls):
            method = getattr(cls, attr_name, None)
            event_type = getattr(method, "_laura_hook", None)
            if event_type is not None:
                hooks.setdefault(event_type, []).append(attr_name)
        return hooks

    def _to_legacy_manifest(self) -> PluginManifest:
        """Convert the SDK metadata to the internal ``PluginManifest`` format."""
        m = self.metadata
        return PluginManifest(
            name=m.name,
            version=m.version,
            description=m.description,
            author=m.author,
            homepage=m.homepage,
            min_laura_version=m.min_laura_version,
            hooks=list(self.discover_hooks().keys()),
        )


# ── Hook decorator ───────────────────────────────────────────────────────────


def hook(event_type: str):
    """Decorator that marks a method as a handler for the given *event_type*.

    The decorated method should accept ``(self, event: Event, ctx: Context)``
    and return an :class:`ActionResult`.

    Usage::

        class MyPlugin(PluginBase):
            @hook("order.created")
            def handle_order(self, event: Event, ctx: Context) -> ActionResult:
                ...
    """
    if not event_type or not isinstance(event_type, str):
        raise TypeError("hook(event_type) requires a non-empty string")

    def decorator(func):
        func._laura_hook = event_type
        return func

    return decorator


# ── Factory ──────────────────────────────────────────────────────────────────


class PluginLoadError(RuntimeError):
    """Raised when a plugin cannot be loaded."""


def create_plugin(config: dict[str, Any] | None = None) -> PluginBase:
    """Discover and instantiate a ``PluginBase`` subclass.

    Scans the caller's module for concrete subclasses of :class:`PluginBase`,
    instantiates the first one found, wraps it in a :class:`LauraAPI`, and
    returns the ready-to-use instance.

    Parameters
    ----------
    config : dict or None
        Optional configuration dict accessible via ``ctx.config``.

    Returns
    -------
    PluginBase
        An initialised plugin instance with ``api`` set.

    Raises
    ------
    PluginLoadError
        If no concrete ``PluginBase`` subclass is found, or if instantiation
        or ``on_load`` fails.
    """
    import inspect
    import sys

    # Walk up the stack to find the caller's module.
    caller_frame = inspect.currentframe()
    if caller_frame is None:
        raise PluginLoadError("Could not inspect call stack")

    try:
        frame = caller_frame.f_back
        if frame is None:
            raise PluginLoadError("No caller frame available")

        module_name = frame.f_globals.get("__name__", "")
        if not module_name:
            raise PluginLoadError("Could not determine caller module name")

        module = sys.modules.get(module_name)
        if module is None:
            raise PluginLoadError(f"Module {module_name!r} not found in sys.modules")
    finally:
        del caller_frame

    plugin_cls: type[PluginBase] | None = None
    for _name, obj in inspect.getmembers(module):
        if (
            isinstance(obj, type)
            and issubclass(obj, PluginBase)
            and obj is not PluginBase
            and not getattr(obj, "__abstractmethods__", None)
        ):
            plugin_cls = obj
            break

    if plugin_cls is None:
        raise PluginLoadError(
            "No concrete PluginBase subclass found in calling module"
        )

    # Validate metadata
    metadata = getattr(plugin_cls, "metadata", None)
    if metadata is None:
        raise PluginLoadError(
            f"{plugin_cls.__name__} is missing a 'metadata' attribute"
        )
    if not isinstance(metadata, PluginMetadata):
        raise PluginLoadError(
            f"{plugin_cls.__name__}.metadata must be a PluginMetadata instance"
        )

    # Version check
    if not _check_version_compatibility(metadata.min_laura_version):
        raise PluginLoadError(
            f"Plugin {metadata.name!r} requires Laura >= {metadata.min_laura_version}"
        )

    try:
        instance = plugin_cls()
    except Exception as exc:
        raise PluginLoadError(
            f"Failed to instantiate {plugin_cls.__name__}: {exc}"
        ) from exc

    ctx = Context(
        config=config or {},
        logger=instance.api._logger,
        api=instance.api,
    )

    try:
        instance.on_load(ctx)
    except Exception as exc:
        raise PluginLoadError(
            f"{plugin_cls.__name__}.on_load() raised: {exc}"
        ) from exc

    return instance
