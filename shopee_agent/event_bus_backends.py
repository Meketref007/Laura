"""
Redis and RabbitMQ backends for AsyncEventBus.

Provides distributed event bus implementations that extend the in-memory
AsyncEventBus with Redis or RabbitMQ as the transport layer, while
preserving the same public API (register_handler, start, stop, submit,
stats, dlq, replay_dlq, wait_until_idle). Both implementations gracefully
fall back to in-memory mode when the required library is unavailable or
the connection fails.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from .event_bus import (
    AsyncEventBus,
    DeadLetterEvent,
    Event,
    EventBusStats,
    EventHandler,
    _event_to_dict,
)
from .logger import info, warning


class RedisEventBus:
    """AsyncEventBus backed by Redis lists (queue) and pub/sub (distribution).

    Uses ``redis.asyncio`` for async Redis operations. If the library is
    unavailable or the connection fails, silently falls back to the
    in-memory AsyncEventBus.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        queue_key: str = "event_bus:queue",
        pubsub_channel: str = "event_bus:events",
        stats_key: str = "event_bus:stats",
        worker_count: int = 2,
        queue_maxsize: int = 0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        journal_path: str | None = None,
    ):
        self._redis_config: dict[str, Any] = {
            "host": host,
            "port": port,
            "db": db,
        }
        if password is not None:
            self._redis_config["password"] = password
        self._queue_key = queue_key
        self._pubsub_channel = pubsub_channel
        self._stats_key = stats_key

        self._fallback = AsyncEventBus(
            worker_count=worker_count,
            queue_maxsize=queue_maxsize,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            journal_path=journal_path,
        )

        self._redis: Any = None
        self._pubsub: Any = None
        self._consumer_task: asyncio.Task | None = None
        self._pubsub_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_handler(self, event_type: str, handler: EventHandler, name: str = "") -> None:
        self._fallback.register_handler(event_type, handler, name)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._fallback.start()

        loop = self._fallback._loop
        if loop is None:
            warning("RedisEventBus: fallback bus has no event loop, in-memory only")
            return

        future = asyncio.run_coroutine_threadsafe(self._async_start(), loop)
        try:
            future.result(timeout=10)
        except Exception as exc:
            warning(f"RedisEventBus async start failed: {exc}")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        loop = self._fallback._loop
        if loop is not None and self._redis is not None:
            future = asyncio.run_coroutine_threadsafe(self._async_stop(), loop)
            try:
                future.result(timeout=10)
            except Exception as exc:
                warning(f"RedisEventBus async stop error: {exc}")

        self._fallback.stop()
        info("RedisEventBus stopped")

    def submit(self, event: Any) -> None:
        self._fallback._journal_write(event)

        if not self._running:
            self._fallback._dispatch_sync(event)
            return

        if self._redis is None:
            self._fallback.submit(event)
            return

        loop = self._fallback._loop
        if loop is None:
            self._fallback.submit(event)
            return

        event_dict = _event_to_dict(event)
        event_dict["__event_type__"] = getattr(event, "event_type", "")
        payload = json.dumps(event_dict, ensure_ascii=False, default=str)

        async def _publish():
            try:
                await self._redis.lpush(self._queue_key, payload)
                await self._redis.publish(self._pubsub_channel, payload)
                await self._redis.hincrby(self._stats_key, "queued", 1)
            except Exception as exc:
                warning(f"Redis publish failed: {exc}")

        asyncio.run_coroutine_threadsafe(_publish(), loop)

    def stats(self) -> EventBusStats:
        if self._redis is None:
            return self._fallback.stats()
        loop = self._fallback._loop
        if loop is None:
            return self._fallback.stats()
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._redis.hgetall(self._stats_key), loop
            )
            raw = future.result(timeout=5)
            return EventBusStats(
                queued=int(raw.get(b"queued", 0) or 0),
                processed=int(raw.get(b"processed", 0) or 0),
                failed=int(raw.get(b"failed", 0) or 0),
                retried=int(raw.get(b"retried", 0) or 0),
                dlq_count=len(self._fallback.dlq()),
            )
        except Exception:
            return self._fallback.stats()

    def dlq(self) -> list[DeadLetterEvent]:
        return self._fallback.dlq()

    def replay_dlq(self, max_events: int = 0) -> int:
        return self._fallback.replay_dlq(max_events)

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return self._fallback.wait_until_idle(timeout)

    # ------------------------------------------------------------------
    # Async internals (run in the fallback bus event loop)
    # ------------------------------------------------------------------

    async def _async_start(self) -> None:
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.Redis(**self._redis_config)
            await self._redis.ping()

            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self._pubsub_channel)

            self._consumer_task = asyncio.create_task(self._consume_loop())
            self._pubsub_task = asyncio.create_task(self._pubsub_listener())

            info("RedisEventBus connected", host=self._redis_config["host"])
        except ImportError:
            warning("redis.asyncio not installed; RedisEventBus running in-memory")
            self._redis = None
        except Exception as exc:
            warning(f"RedisEventBus connection failed, falling back to in-memory: {exc}")
            self._redis = None

    async def _async_stop(self) -> None:
        tasks = []
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            tasks.append(self._consumer_task)
        if self._pubsub_task is not None:
            self._pubsub_task.cancel()
            tasks.append(self._pubsub_task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(self._pubsub_channel)
            except Exception:
                pass
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:
                pass

        self._consumer_task = None
        self._pubsub_task = None
        self._pubsub = None
        self._redis = None

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                result = await self._redis.brpop(self._queue_key, timeout=1)
                if result is None:
                    continue
                _, payload = result
                event = self._deserialize_event(payload)
                if event is None:
                    continue
                await self._fallback._queue.put(event)
                await self._redis.hincrby(self._stats_key, "processed", 1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                warning(f"Redis consumer error: {exc}")
                try:
                    await self._redis.hincrby(self._stats_key, "failed", 1)
                except Exception:
                    pass

    async def _pubsub_listener(self) -> None:
        while self._running:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                if not raw:
                    continue
                event = self._deserialize_event(raw)
                if event is not None:
                    await self._fallback._queue.put(event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                warning(f"Redis pubsub listener error: {exc}")

    def _deserialize_event(self, payload: str) -> Event | None:
        try:
            data: dict = json.loads(payload)
            data.pop("__event_type__", None)
            event_type = data.pop("event_type", "")
            ts_raw = data.pop("timestamp", None)
            ts: datetime | None = None
            if isinstance(ts_raw, str):
                try:
                    ts = datetime.fromisoformat(ts_raw)
                except (ValueError, TypeError):
                    ts = None
            ev = Event(event_type=event_type, timestamp=ts)
            for k, v in data.items():
                setattr(ev, k, v)
            return ev
        except Exception as exc:
            warning(f"Failed to deserialize event: {exc}")
            return None


class RabbitMQEventBus:
    """AsyncEventBus backed by RabbitMQ exchanges and queues.

    Uses ``aio_pika`` for async AMQP operations. If the library is
    unavailable or the connection fails, silently falls back to the
    in-memory AsyncEventBus.
    """

    def __init__(
        self,
        url: str = "amqp://guest:guest@localhost:5672/",
        exchange_name: str = "event_bus",
        exchange_type: str = "topic",
        queue_name: str = "event_bus_queue",
        routing_key: str = "event.#",
        worker_count: int = 2,
        queue_maxsize: int = 0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        journal_path: str | None = None,
    ):
        self._url = url
        self._exchange_name = exchange_name
        self._exchange_type = exchange_type
        self._queue_name = queue_name
        self._routing_key = routing_key

        self._fallback = AsyncEventBus(
            worker_count=worker_count,
            queue_maxsize=queue_maxsize,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            journal_path=journal_path,
        )

        self._connection: Any = None
        self._channel: Any = None
        self._exchange: Any = None
        self._queue: Any = None
        self._consumer_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_handler(self, event_type: str, handler: EventHandler, name: str = "") -> None:
        self._fallback.register_handler(event_type, handler, name)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._fallback.start()

        loop = self._fallback._loop
        if loop is None:
            warning("RabbitMQEventBus: fallback bus has no event loop, in-memory only")
            return

        future = asyncio.run_coroutine_threadsafe(self._async_start(), loop)
        try:
            future.result(timeout=15)
        except Exception as exc:
            warning(f"RabbitMQEventBus async start failed: {exc}")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        loop = self._fallback._loop
        if loop is not None and self._connection is not None:
            future = asyncio.run_coroutine_threadsafe(self._async_stop(), loop)
            try:
                future.result(timeout=15)
            except Exception as exc:
                warning(f"RabbitMQEventBus async stop error: {exc}")

        self._fallback.stop()
        info("RabbitMQEventBus stopped")

    def submit(self, event: Any) -> None:
        self._fallback._journal_write(event)

        if not self._running:
            self._fallback._dispatch_sync(event)
            return

        if self._connection is None:
            self._fallback.submit(event)
            return

        loop = self._fallback._loop
        if loop is None:
            self._fallback.submit(event)
            return

        event_dict = _event_to_dict(event)
        event_dict["__event_type__"] = getattr(event, "event_type", "")
        payload = json.dumps(event_dict, ensure_ascii=False, default=str)

        async def _publish():
            try:
                message = self._Message(
                    body=payload.encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=2,  # persistent
                )
                await self._exchange.publish(
                    message, routing_key=self._routing_key
                )
            except Exception as exc:
                warning(f"RabbitMQ publish failed: {exc}")

        asyncio.run_coroutine_threadsafe(_publish(), loop)

    def stats(self) -> EventBusStats:
        return self._fallback.stats()

    def dlq(self) -> list[DeadLetterEvent]:
        return self._fallback.dlq()

    def replay_dlq(self, max_events: int = 0) -> int:
        return self._fallback.replay_dlq(max_events)

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return self._fallback.wait_until_idle(timeout)

    # ------------------------------------------------------------------
    # Async internals (run in the fallback bus event loop)
    # ------------------------------------------------------------------

    async def _async_start(self) -> None:
        try:
            import aio_pika

            self._Message = aio_pika.Message

            self._connection = await aio_pika.connect_robust(self._url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=1)

            self._exchange = await self._channel.declare_exchange(
                self._exchange_name, type=self._exchange_type, durable=True
            )
            self._queue = await self._channel.declare_queue(
                self._queue_name, durable=True
            )
            await self._queue.bind(self._exchange, routing_key=self._routing_key)

            self._consumer_task = asyncio.create_task(self._consume_loop())
            info("RabbitMQEventBus connected", url=self._url)
        except ImportError:
            warning("aio_pika not installed; RabbitMQEventBus running in-memory")
            self._connection = None
        except Exception as exc:
            warning(f"RabbitMQEventBus connection failed, falling back to in-memory: {exc}")
            self._connection = None

    async def _async_stop(self) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        if self._channel is not None:
            try:
                await self._channel.close()
            except Exception:
                pass
            self._channel = None
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                pass
            self._connection = None
        self._exchange = None
        self._queue = None

    async def _consume_loop(self) -> None:
        try:
            async with self._queue.iterator() as queue_iter:
                async for message in queue_iter:
                    if not self._running:
                        break
                    async with message.process(ignore_processed=True):
                        try:
                            payload = message.body.decode("utf-8")
                            event = self._deserialize_event(payload)
                            if event is not None:
                                await self._fallback._queue.put(event)
                        except Exception as exc:
                            warning(f"RabbitMQ consumer message error: {exc}")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            warning(f"RabbitMQ consumer loop error: {exc}")

    def _deserialize_event(self, payload: str) -> Event | None:
        try:
            data: dict = json.loads(payload)
            data.pop("__event_type__", None)
            event_type = data.pop("event_type", "")
            ts_raw = data.pop("timestamp", None)
            ts: datetime | None = None
            if isinstance(ts_raw, str):
                try:
                    ts = datetime.fromisoformat(ts_raw)
                except (ValueError, TypeError):
                    ts = None
            ev = Event(event_type=event_type, timestamp=ts)
            for k, v in data.items():
                setattr(ev, k, v)
            return ev
        except Exception as exc:
            warning(f"Failed to deserialize event: {exc}")
            return None


def auto_event_bus(backend: str = "memory", **kwargs: Any) -> Any:
    """Factory that returns the appropriate event bus backend.

    Parameters
    ----------
    backend : str
        One of ``"memory"``, ``"redis"``, or ``"rabbitmq"``.
    **kwargs
        Forwarded to the backend constructor.

    Returns
    -------
    AsyncEventBus-compatible instance
        If the requested backend's library is not installed, logs a
        warning and returns an in-memory AsyncEventBus.
    """
    backend = backend.lower().strip()

    if backend == "memory":
        return AsyncEventBus(
            worker_count=kwargs.pop("worker_count", 2),
            queue_maxsize=kwargs.pop("queue_maxsize", 0),
            max_retries=kwargs.pop("max_retries", 3),
            retry_backoff=kwargs.pop("retry_backoff", 1.0),
            journal_path=kwargs.pop("journal_path", None),
        )

    if backend == "redis":
        try:
            import redis.asyncio  # noqa: F401
            return RedisEventBus(**kwargs)
        except ImportError:
            warning(
                "redis.asyncio is not installed. "
                "Install it with: pip install redis"
            )
        except Exception as exc:
            warning(f"Failed to initialize RedisEventBus: {exc}")

        info("Falling back to in-memory AsyncEventBus")
        return AsyncEventBus(
            worker_count=kwargs.pop("worker_count", 2),
            queue_maxsize=kwargs.pop("queue_maxsize", 0),
            max_retries=kwargs.pop("max_retries", 3),
            retry_backoff=kwargs.pop("retry_backoff", 1.0),
            journal_path=kwargs.pop("journal_path", None),
        )

    if backend == "rabbitmq":
        try:
            import aio_pika  # noqa: F401
            return RabbitMQEventBus(**kwargs)
        except ImportError:
            warning(
                "aio_pika is not installed. "
                "Install it with: pip install aio-pika"
            )
        except Exception as exc:
            warning(f"Failed to initialize RabbitMQEventBus: {exc}")

        info("Falling back to in-memory AsyncEventBus")
        return AsyncEventBus(
            worker_count=kwargs.pop("worker_count", 2),
            queue_maxsize=kwargs.pop("queue_maxsize", 0),
            max_retries=kwargs.pop("max_retries", 3),
            retry_backoff=kwargs.pop("retry_backoff", 1.0),
            journal_path=kwargs.pop("journal_path", None),
        )

    warning(f"Unknown backend '{backend}', falling back to in-memory AsyncEventBus")
    return AsyncEventBus(
        worker_count=kwargs.pop("worker_count", 2),
        queue_maxsize=kwargs.pop("queue_maxsize", 0),
        max_retries=kwargs.pop("max_retries", 3),
        retry_backoff=kwargs.pop("retry_backoff", 1.0),
        journal_path=kwargs.pop("journal_path", None),
    )
