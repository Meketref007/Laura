# Laura Plugin SDK

The **Laura Plugin SDK** provides a clean, stable public API for third-party
developers to create plugins that integrate with the Laura e-commerce
automation agent.

- **Package**: `shopee_agent.plugin_sdk`
- **Min Laura version**: `1.0.0`
- **License**: MIT

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Plugin Structure](#plugin-structure)
3. [Available Hooks](#available-hooks)
4. [Plugin Lifecycle](#plugin-lifecycle)
5. [Configuration](#configuration)
6. [Context & API](#context--api)
7. [Events & Action Results](#events--action-results)
8. [Logging](#logging)
9. [Persistent Storage](#persistent-storage)
10. [HTTP Requests](#http-requests)
11. [Best Practices](#best-practices)
12. [Full Example](#full-example)
13. [Distribution](#distribution)

---

## Quick Start

### 1. Create a plugin file

Save the following as `plugins/my_first_plugin.py`:

```python
from shopee_agent.plugin_sdk import (
    PluginBase, PluginMetadata, hook,
    Event, Context, ActionResult,
)

class MyFirstPlugin(PluginBase):
    metadata = PluginMetadata(
        name="my-first-plugin",
        version="1.0.0",
        description="My first Laura plugin",
        author="Your Name",
    )

    @hook("order.created")
    def on_order_created(self, event: Event, ctx: Context) -> ActionResult:
        order_id = event.data.get("id")
        ctx.api.log_info(f"New order received: {order_id}")
        return ActionResult(success=True, message=f"Handled order {order_id}")
```

### 2. Install & enable

```bash
laura plugin install path/to/my_first_plugin.py
laura plugin list
```

Laura automatically discovers plugins in the `plugins/` directory and
re-enables previously loaded plugins on startup.

---

## Plugin Structure

Every plugin must:

1. **Subclass `PluginBase`**
2. **Define a `metadata` class attribute** — a `PluginMetadata` instance
3. **Optionally decorate methods with `@hook("event.type")`**

### PluginMetadata fields

| Field                 | Type     | Default      | Description                              |
|-----------------------|----------|--------------|------------------------------------------|
| `name`                | `str`    | *(required)* | Unique plugin identifier                 |
| `version`             | `str`    | *(required)* | Semantic version (e.g. `"1.2.3"`)       |
| `description`         | `str`    | *(required)* | Short description of the plugin          |
| `author`              | `str`    | *(required)* | Author name or organisation              |
| `license`             | `str`    | `"MIT"`      | SPDX license identifier                  |
| `homepage`            | `str`    | `""`         | Project URL                              |
| `tags`                | `list`   | `[]`         | Keywords for marketplace search          |
| `min_laura_version`   | `str`    | `"1.0.0"`    | Minimum Laura version required           |

---

## Available Hooks

Hooks are event-driven callbacks. Decorate methods with `@hook("event.type")`
to register them. The method signature is:

```python
@hook("event.type")
def handler(self, event: Event, ctx: Context) -> ActionResult: ...
```

### Core system events

| Hook event               | Triggered when                         | `event.data` includes                         |
|--------------------------|----------------------------------------|-----------------------------------------------|
| `"agent.started"`        | Laura daemon starts                    | `{}`                                          |
| `"agent.stopped"`        | Laura daemon shuts down                | `{}`                                          |
| `"cycle.start"`          | A new autonomous cycle begins          | `{"cycle": int, "skills": list}`              |
| `"cycle.end"`            | An autonomous cycle ends               | `{"cycle": int, "result": dict}`              |
| `"order.created"`        | A new order is detected                | `{"id": str, "total": float, "items": list}`  |
| `"order.updated"`        | An existing order changes status       | `{"id": str, "status": str}`                  |
| `"order.cancelled"`      | An order is cancelled                  | `{"id": str, "reason": str}`                  |
| `"message.received"`     | A new chat message arrives             | `{"chat_id": str, "from": str, "text": str}`  |
| `"product.updated"`      | Product details change                 | `{"product_id": str, "field": str}`           |
| `"price.changed"`        | A product price is adjusted            | `{"product_id": str, "old": float, "new": float}` |
| `"inventory.low"`        | Stock falls below threshold            | `{"product_id": str, "stock": int, "threshold": int}` |
| `"alert.triggered"`      | A system or business alert fires       | `{"level": str, "message": str}`              |
| `"config.changed"`       | Plugin configuration is updated        | `{"plugin": str, "key": str, "value": any}`   |
| `"error.occurred"`       | A non-fatal error happens              | `{"source": str, "message": str}`             |

> **Note**: The set of available hooks is defined by Laura's internal event
> bus. Custom events emitted by your own (or other) plugins can also be
> subscribed to.

---

## Plugin Lifecycle

```
[Install] → [Load] → [Handle events] → [Unload] → [Remove]
                ↑                                      │
                └────────── [Upgrade] ←────────────────┘
```

### `on_install()`
Called **once** when the plugin file is first placed in the `plugins/`
directory. Use this for one-time setup:

```python
def on_install(self) -> None:
    self.api.store_set("installed_at", datetime.now().isoformat())
```

### `on_load(ctx: Context)`
Called every time Laura starts (or when a plugin is hot-loaded). The
`Context` object provides access to configuration, logging, and the
`LauraAPI`. Raise `PluginLoadError` to abort loading.

```python
def on_load(self, ctx: Context) -> None:
    if not ctx.config.get("api_key"):
        raise PluginLoadError("api_key is required")
    ctx.api.log_info("Plugin loaded successfully")
```

### `on_unload()`
Called when Laura shuts down or when the plugin is explicitly unloaded.
Clean up resources here (close files, stop threads, flush buffers).

```python
def on_unload(self) -> None:
    self._my_thread.join(timeout=5)
```

### `on_upgrade(old_version: str)`
Called automatically when the plugin file is replaced with a newer version.
Use this for data migrations:

```python
def on_upgrade(self, old_version: str) -> None:
    if old_version < "1.1.0":
        self.api.store_set("migrated", True)
```

---

## Configuration

Plugins receive configuration through `ctx.config` (a plain `dict`).

At load time, Laura merges:
- Default values set in the plugin code
- Values persisted from a previous session
- Values supplied via the CLI or configuration UI

```python
def on_load(self, ctx: Context) -> None:
    interval = ctx.config.get("poll_interval", 60)
    self.api.set_config("poll_interval", interval)
```

You can read / write config values at runtime using the API:

```python
value = self.api.get_config("my_key")
self.api.set_config("my_key", new_value)
```

---

## Context & API

### `Context`

| Attribute   | Type         | Description                             |
|-------------|--------------|-----------------------------------------|
| `store_id`  | `str | None` | Active store context (if any)           |
| `config`    | `dict`       | Plugin configuration values             |
| `logger`    | `Logger`     | Logger instance (pre-configured)        |
| `api`       | `LauraAPI`   | Safe access to Laura internals          |

### `LauraAPI`

| Method                                   | Description                              |
|------------------------------------------|------------------------------------------|
| `get_config(key) -> Any`                 | Read a configuration value               |
| `set_config(key, value) -> None`         | Write a configuration value              |
| `emit_event(event: Event) -> None`       | Emit an event to the bus                 |
| `log_info(msg) -> None`                  | Log an info message                      |
| `log_error(msg) -> None`                 | Log an error message                     |
| `store_get(key, default=None) -> Any`    | Read from persistent key-value store     |
| `store_set(key, value) -> None`          | Write to persistent key-value store      |
| `http_get(url, headers=None) -> Response`| Rate-limited HTTP GET                    |
| `http_post(url, json, headers=None) -> Response`| Rate-limited HTTP POST          |

---

## Events & Action Results

### `Event`

| Field       | Type     | Description                     |
|-------------|----------|---------------------------------|
| `type`      | `str`    | Event type (e.g. `"order.created"`) |
| `data`      | `dict`   | Arbitrary payload               |
| `timestamp` | `float`  | Unix timestamp                  |
| `source`    | `str`    | Origin of the event             |

### `ActionResult`

Returned by every hook handler.

| Field     | Type     | Description                           |
|-----------|----------|---------------------------------------|
| `success` | `bool`   | Whether handling succeeded            |
| `message` | `str`    | Human-readable result                 |
| `data`    | `dict`   | Arbitrary result data                 |
| `error`   | `str | None` | Error message (if failed)         |

---

## Logging

Use `ctx.api.log_info()` and `ctx.api.log_error()` for structured logging.
Messages are prefixed with the plugin name automatically:

```python
ctx.api.log_info("Processing order")  # → [my-plugin] Processing order
ctx.api.log_error("Request failed")   # → [my-plugin] Request failed
```

Logs are written to `logs/laura_operations.log` with JSON formatting and
rotation.

---

## Persistent Storage

The plugin SDK provides a simple key-value store scoped to your plugin:

```python
# Write
self.api.store_set("last_order_id", "12345")

# Read
last_id = self.api.store_get("last_order_id", default="none")
```

Values are kept in memory for the lifetime of the plugin. For durable
storage across restarts, use `store_set` / `store_get` combined with file
I/O in `on_load` / `on_unload`, or the Laura `reports/` directory
accessible via `ctx.config["data_dir"]`.

---

## HTTP Requests

The SDK's HTTP methods apply rate-limiting and set a proper
`User-Agent` header automatically:

```python
# GET
resp = self.api.http_get("https://api.example.com/data")
data = resp.json()

# POST
resp = self.api.http_post(
    "https://api.example.com/webhook",
    json={"event": "test"},
    headers={"Authorization": "Bearer xxx"},
)
```

Both methods use `requests.Session` internally for connection reuse and
timeout after 30 seconds.

---

## Best Practices

1. **Use `ActionResult` consistently** — always return it from hooks so
   Laura can track success/failure.

2. **Be defensive** — wrap external calls in try/except and return
   `ActionResult(success=False, error=str(e))`.

3. **Keep hooks fast** — long-running work should be offloaded to a
   background thread. Use `on_load` to start threads and `on_unload` to
   join them.

4. **Use `@hook` only on methods** — the decorator works on instance
   methods of `PluginBase` subclasses.

5. **Version your plugin** — increment `metadata.version` on every
   release and implement `on_upgrade` to handle migrations.

6. **Avoid importing internal Laura modules** — use `self.api.*`
   methods instead. Importing `shopee_agent.plugin_system` or
   `shopee_agent.logger` directly couples your plugin to internal APIs
   that may change.

7. **Handle `on_load` failures gracefully** — raise
   `PluginLoadError` with a clear message if prerequisites are not met.

8. **Clean up resources** — always implement `on_unload` to stop
   threads, close sessions, and flush state.

9. **Use tags** — populate `metadata.tags` so your plugin appears in
   marketplace search results.

10. **Test with the factory** — use `create_plugin()` in unit tests:

    ```python
    from shopee_agent.plugin_sdk import create_plugin

    plugin = create_plugin({"api_key": "test"})
    ```

---

## Full Example

```python
"""plugins/order_notifier.py — Sends a notification on every new order."""

from datetime import datetime

from shopee_agent.plugin_sdk import (
    PluginBase,
    PluginMetadata,
    hook,
    Event,
    Context,
    ActionResult,
)


class OrderNotifier(PluginBase):
    metadata = PluginMetadata(
        name="order-notifier",
        version="1.1.0",
        description="Notifies an external webhook when orders arrive",
        author="Acme Corp",
        license="MIT",
        homepage="https://github.com/acme/laura-order-notifier",
        tags=["orders", "notifications", "webhook"],
        min_laura_version="1.0.0",
    )

    def on_load(self, ctx: Context) -> None:
        self.webhook_url = ctx.config.get("webhook_url")
        if not self.webhook_url:
            from shopee_agent.plugin_sdk import PluginLoadError
            raise PluginLoadError("webhook_url is required in config")
        ctx.api.log_info(f"OrderNotifier loaded, webhook: {self.webhook_url}")

    def on_unload(self) -> None:
        self.api.log_info("OrderNotifier unloaded")

    def on_install(self) -> None:
        self.api.store_set("installed_at", datetime.now().isoformat())

    def on_upgrade(self, old_version: str) -> None:
        self.api.log_info(f"Upgraded from {old_version}")

    @hook("order.created")
    def handle_order_created(self, event: Event, ctx: Context) -> ActionResult:
        order = event.data
        try:
            resp = self.api.http_post(
                self.webhook_url,
                json={"order_id": order.get("id"), "total": order.get("total")},
            )
            resp.raise_for_status()
            return ActionResult(
                success=True,
                message=f"Notified webhook for order {order.get('id')}",
                data={"status_code": resp.status_code},
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=str(e),
                message="Failed to notify webhook",
            )

    @hook("order.cancelled")
    def handle_order_cancelled(self, event: Event, ctx: Context) -> ActionResult:
        ctx.api.log_info(f"Order {event.data.get('id')} was cancelled")
        return ActionResult(success=True)


# Allow manual instantiation for testing:
#   from shopee_agent.plugin_sdk import create_plugin
#   plugin = create_plugin({"webhook_url": "https://hook.example.com/notify"})
```

---

## Distribution

Share your plugin by:

1. **Publishing the `.py` file** on GitHub, GitLab, or any public URL.
2. **Adding it to the Laura Plugin Registry** — submit a pull request to
   the [laura-plugins](https://github.com/anomalyco/laura-plugins)
   repository.

Users can install from URL:

```bash
laura plugin install order-notifier --source https://raw.githubusercontent.com/.../order_notifier.py
```

Or from a local file:

```bash
laura plugin install path/to/order_notifier.py
```
