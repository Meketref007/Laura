import math
from typing import Any

from fastapi import FastAPI, Response

_DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)


class MetricsExporter:
    def __init__(self, buckets: tuple[float, ...] | None = None):
        self._buckets = buckets or _DEFAULT_BUCKETS
        self._metrics: dict[str, dict[str, Any]] = {}
        self._init_default_metrics()

    def _init_default_metrics(self) -> None:
        counters = [
            ("laura_events_queued_total", "Total events queued"),
            ("laura_events_processed_total", "Total events processed"),
            ("laura_events_failed_total", "Total events failed"),
            ("laura_events_dlq_total", "Total events sent to dead letter queue"),
            ("laura_skills_executed_total", "Total skills executed, by name and status"),
            ("laura_plans_created_total", "Total plans created"),
            ("laura_plans_succeeded_total", "Total plans succeeded"),
            ("laura_plans_failed_total", "Total plans failed"),
            ("laura_agent_cycles_total", "Total agent cycles"),
            ("laura_goal_suggestions_total", "Total goal suggestions"),
        ]
        for name, help_ in counters:
            self._add_metric(name, "counter", help_)

        self._add_metric(
            "laura_circuit_breaker_state",
            "gauge",
            "Circuit breaker state (0=closed, 1=half-open, 2=open)",
        )

        self._add_metric(
            "laura_skills_duration_seconds",
            "histogram",
            "Skill execution duration in seconds",
        )

    def _add_metric(self, name: str, type_: str, help_: str) -> None:
        self._metrics[name] = {
            "type": type_,
            "help": help_,
            "values": {},
        }

    @staticmethod
    def _labels_key(labels: dict[str, str] | None = None) -> tuple[tuple[str, str], ...]:
        if labels:
            return tuple(sorted(labels.items()))
        return ()

    @staticmethod
    def _label_str(
        labels: tuple[tuple[str, str], ...],
        extra: dict[str, str] | None = None,
    ) -> str:
        parts = [f'{k}="{v}"' for k, v in labels]
        if extra:
            parts.extend(f'{k}="{v}"' for k, v in extra.items())
        if not parts:
            return ""
        return "{" + ",".join(parts) + "}"

    def inc(self, name: str, labels: dict[str, str] | None = None, value: int | float = 1) -> None:
        metric = self._metrics.get(name)
        if metric is None:
            raise KeyError(f"Unknown metric: {name}")
        if metric["type"] == "histogram":
            raise TypeError(f"Cannot increment histogram metric: {name}")
        key = self._labels_key(labels)
        if key not in metric["values"]:
            metric["values"][key] = 0
        metric["values"][key] += value

    def set(self, name: str, value: int | float, labels: dict[str, str] | None = None) -> None:
        metric = self._metrics.get(name)
        if metric is None:
            raise KeyError(f"Unknown metric: {name}")
        if metric["type"] != "gauge":
            raise TypeError(f"Can only set gauge metrics: {name}")
        metric["values"][()] = value

    def observe(self, name: str, value: int | float, labels: dict[str, str] | None = None) -> None:
        metric = self._metrics.get(name)
        if metric is None:
            raise KeyError(f"Unknown metric: {name}")
        if metric["type"] != "histogram":
            raise TypeError(f"Can only observe histogram metrics: {name}")
        key = self._labels_key(labels)
        if key not in metric["values"]:
            data: dict[str, Any] = {"count": 0, "sum": 0.0, "buckets": {}}
            for b in self._buckets:
                data["buckets"][b] = 0
            data["buckets"][math.inf] = 0
            metric["values"][key] = data
        data = metric["values"][key]
        data["count"] += 1
        data["sum"] += value
        for b in data["buckets"]:
            if value <= b:
                data["buckets"][b] += 1

    def render(self) -> str:
        lines: list[str] = []
        for name, metric in self._metrics.items():
            lines.append(f"# HELP {name} {metric['help']}")
            lines.append(f"# TYPE {name} {metric['type']}")

            if metric["type"] == "histogram":
                for labels_key, data in metric["values"].items():
                    base = self._label_str(labels_key)
                    for bucket, count in sorted(
                        data["buckets"].items(),
                        key=lambda x: (x[0] == math.inf, x[0]),
                    ):
                        le = "+Inf" if bucket == math.inf else bucket
                        bucket_labels = base[:-1] + f",le=\"{le}\"" + "}" if base else f"{{le=\"{le}\"}}"
                        lines.append(f"{name}_bucket{bucket_labels} {count}")
                    lines.append(f"{name}_sum{base} {data['sum']}")
                    lines.append(f"{name}_count{base} {data['count']}")
            else:
                for labels_key, value in metric["values"].items():
                    lines.append(f"{name}{self._label_str(labels_key)} {value}")
        return "\n".join(lines) + "\n"

    def register(self, app: FastAPI) -> None:
        exporter = self

        @app.get("/metrics")
        async def metrics():
            return Response(
                content=exporter.render(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )
