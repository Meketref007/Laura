# Phase 36: Event-Driven Architecture

Phase 36 introduces a small async event bus so webhook events can be processed by background workers instead of only synchronous callbacks.

## What changed

- Added `shopee_agent/event_bus.py` with an asyncio-backed worker pool.
- Wired `shopee_agent/webhook_server.py` to submit handler work to the bus.
- Kept synchronous fallback behavior when the bus is not running.
- Added focused tests in `tests/test_event_bus.py`.

## Runtime behavior

- Incoming webhook events are accepted as before.
- Handler execution is queued onto a background worker pool.
- Multiple workers can process independent events concurrently.
- Sync handlers and async handlers are both supported.

## Usage

Run the webhook server as usual; the async bus starts automatically with the server.

For test or standalone usage:

```bash
.venv/bin/python -m pytest -q tests/test_event_bus.py tests/test_webhook_server.py
```
