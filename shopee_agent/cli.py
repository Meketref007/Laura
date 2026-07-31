from __future__ import annotations

import time as _time

# Earliest possible anchor: measures end-to-end CLI startup (python boot +
# cli module import + parser build + dispatch). Stored on the package so it
# stays stable when the module is re-executed as `__main__` (python -m) or
# re-imported under its real name from handler code.
import shopee_agent as _pkg

if not hasattr(_pkg, "_CLI_START"):
    _pkg._CLI_START = _time.perf_counter()
_CLI_START = _pkg._CLI_START

import argparse
import csv
import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .circuit_breaker import initialize_default_circuit_breakers
from .cli_completion import build_parser as build_completion_parser
from .client import ShopeeClient
from .config import ConfigError, load_config
from .logger import debug, info
from .logger import error as log_error
from .prompts import list_available_prompts


def __getattr__(name: str) -> Any:
    """Lazily provide `uvicorn` for the `api-serve` command.

    uvicorn drags in anyio/watchfiles/websockets (~200ms); it is only needed
    when actually serving the API, so it is no longer imported at module load.
    """
    if name == "uvicorn":
        try:
            import uvicorn
        except Exception:  # pragma: no cover - optional runtime dependency
            return None
        return uvicorn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _LazyModelChoices:
    """Deferred iterable for `--model` argument choices.

    Materializing ``LauraOllamaAnalyzer.MODELS`` at parser-build time forces
    the full llm_local import on every CLI invocation (~200ms). This proxy
    defers the import until a value is validated or help text needs the list.
    """

    def __iter__(self):
        from .llm_local import LauraOllamaAnalyzer

        return iter(LauraOllamaAnalyzer.MODELS.keys())

    def __contains__(self, value: Any) -> bool:
        from .llm_local import LauraOllamaAnalyzer

        return value in LauraOllamaAnalyzer.MODELS


_MODEL_CHOICES = _LazyModelChoices()


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True))


def _text_to_simple_vector(text: str, dim: int = 128) -> list[float]:
    """Create a deterministic pseudo-embedding for a text string.

    This is a lightweight fallback embedder for CLI semantic search when a
    proper embedder isn't configured. It maps the SHA256 digest into `dim`
    float components in [-1,1]. Not suitable for production semantic search,
    but fine for local experimentation and smoke tests.
    """

    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand bytes to floats by repeating digest as needed
    bys = (h * ((dim // len(h)) + 1))[:dim]
    vec = [((b / 255.0) * 2.0 - 1.0) for b in bys]
    return vec


def _serve_api(host: str, port: int, reload: bool, log_level: str) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("uvicorn is not installed; cannot serve API. Install uvicorn to run the server.") from exc
    uvicorn.run(
        "shopee_agent.api_app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


# Product costs helpers
_PRODUCT_COSTS_PATH = Path("reports/product_costs.json")


def _load_product_costs() -> dict[str, float]:
    try:
        if not _PRODUCT_COSTS_PATH.exists():
            return {}
        data = json.loads(_PRODUCT_COSTS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        normalized: dict[str, float] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                raw_cost = v.get("cost")
            else:
                raw_cost = v
            try:
                normalized[str(k)] = float(raw_cost)
            except Exception:
                continue
        return normalized
    except Exception:
        return {}


def _save_product_cost(item_id: str, cost: float) -> None:
    data = _load_product_costs()
    data[str(item_id)] = float(cost)
    _PRODUCT_COSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PRODUCT_COSTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get_cost_for_item(item_id: str) -> float | None:
    data = _load_product_costs()
    return float(data.get(str(item_id))) if str(item_id) in data else None


def _normalize_lookup_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _first_present_text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _load_cost_source_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        rows: list[dict[str, Any]] = []
        for key, value in raw.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("item_id", key)
            else:
                row = {"item_id": key, "cost": value}
            rows.append(row)
        return rows

    raise ValueError(f"Formato de custo nao suportado: {path.suffix or 'unknown'}")


def _build_shop_cost_lookup(client: ShopeeClient, *, access_token: str, shop_id: int, max_items: int = 500, page_size: int = 100) -> dict[str, str]:
    lookup: dict[str, str] = {}
    seen_items = 0
    offset = 0

    while seen_items < max_items:
        resp = client.get_item_list(
            access_token=access_token,
            shop_id=shop_id,
            offset=offset,
            page_size=page_size,
        )
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", []) if isinstance(body, dict) else []
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            seen_items += 1
            if seen_items > max_items:
                break

            parent_item_id = _first_present_text(item, "item_id", "id")
            if not parent_item_id:
                continue

            item_name = _first_present_text(item, "item_name", "name")
            item_sku = _first_present_text(item, "item_sku", "sku")
            lookup[f"item_id:{parent_item_id}"] = parent_item_id
            if item_name:
                lookup[f"name:{_normalize_lookup_text(item_name)}"] = parent_item_id
            if item_sku:
                lookup[f"sku:{_normalize_lookup_text(item_sku)}"] = parent_item_id

            try:
                detail_resp = client.get_item_detail(
                    access_token=access_token,
                    shop_id=shop_id,
                    item_id=int(parent_item_id),
                )
                detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
                if not isinstance(detail_body, dict):
                    continue

                variations = detail_body.get("variation_list") or detail_body.get("model_list") or detail_body.get("variations") or []
                if not isinstance(variations, list):
                    continue

                for variation in variations:
                    if not isinstance(variation, dict):
                        continue

                    variation_id = _first_present_text(variation, "variation_id", "model_id", "variationid", "modelid")
                    variation_name = _first_present_text(variation, "variation_name", "name", "model_name")
                    variation_sku = _first_present_text(variation, "variation_sku", "sku", "model_sku")

                    if variation_id:
                        lookup[f"variation_id:{variation_id}"] = parent_item_id
                    if variation_name:
                        lookup[f"name:{_normalize_lookup_text(variation_name)}"] = parent_item_id
                    if variation_sku:
                        lookup[f"sku:{_normalize_lookup_text(variation_sku)}"] = parent_item_id
            except Exception:
                continue

        cursor = str(body.get("next_cursor", "") or "") if isinstance(body, dict) else ""
        if not cursor:
            break
        offset += page_size

    return lookup


def _resolve_cost_target(row: dict[str, Any], lookup: dict[str, str] | None = None) -> str | None:
    item_id = _first_present_text(row, "item_id", "itemid", "itemId")
    if item_id:
        return item_id

    variation_id = _first_present_text(row, "variation_id", "variationid", "variationId")
    if variation_id:
        if lookup:
            target = lookup.get(f"variation_id:{variation_id}")
            if target:
                return target
        return variation_id

    if not lookup:
        return None

    sku = _first_present_text(row, "sku", "item_sku", "variation_sku", "model_sku")
    if sku:
        target = lookup.get(f"sku:{_normalize_lookup_text(sku)}")
        if target:
            return target

    item_name = _first_present_text(row, "item_name", "name", "title", "product_name")
    if item_name:
        target = lookup.get(f"name:{_normalize_lookup_text(item_name)}")
        if target:
            return target

    return None


def _sync_product_cost_rows(
    rows: list[dict[str, Any]],
    *,
    lookup: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "rows": len(rows),
        "saved": 0,
        "skipped": 0,
        "unmatched": 0,
        "errors": [],
        "items": [],
    }

    for row in rows:
        if not isinstance(row, dict):
            summary["skipped"] += 1
            continue

        raw_cost = _first_present_text(row, "cost", "cogs", "unit_cost", "purchase_price")
        if not raw_cost:
            summary["skipped"] += 1
            summary["errors"].append({"error": "missing cost", "row": row})
            continue

        try:
            cost_val = float(raw_cost)
        except Exception as exc:
            summary["skipped"] += 1
            summary["errors"].append({"error": f"invalid cost: {exc}", "row": row})
            continue

        target_item_id = _resolve_cost_target(row, lookup)
        if not target_item_id:
            summary["unmatched"] += 1
            summary["errors"].append({"error": "unmatched product", "row": row})
            continue

        if not dry_run:
            _save_product_cost(target_item_id, cost_val)

        summary["saved"] += 1
        summary["items"].append({
            "item_id": target_item_id,
            "cost": cost_val,
            "source_row": row,
        })

    return summary


def _append_audit_line(path: Path, obj: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass  # audit must not crash the CLI


def _mode_to_octal(mode: int) -> str:
    return oct(stat.S_IMODE(mode))


def _is_secure_env_mode(mode: int) -> bool:
    # Accept only owner read/write/execute bits. Group/other must be 0.
    return (stat.S_IMODE(mode) & 0o077) == 0


def _env_file_report(env_path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(env_path),
        "exists": env_path.exists(),
        "mode": None,
        "secure_mode": None,
    }
    if not env_path.exists():
        return report

    st = env_path.stat()
    mode = stat.S_IMODE(st.st_mode)
    report["mode"] = _mode_to_octal(st.st_mode)
    report["secure_mode"] = _is_secure_env_mode(mode)
    return report


def _json_file_report(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "read_ok": False,
        "error": None,
    }
    if not path.exists():
        return report

    try:
        report["data"] = json.loads(path.read_text(encoding="utf-8"))
        report["read_ok"] = True
    except Exception as exc:
        report["error"] = str(exc)
    return report


def _load_json_file(path_value: str | None, label: str) -> dict[str, Any] | None:
    if not path_value:
        return None

    path = Path(path_value)
    if not path.exists():
        raise FileNotFoundError(f"{label} nao encontrado: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{label} JSON invalido em {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{label} deve conter um objeto JSON em {path}")
    return data


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _doctor_report(env_file: str) -> dict[str, Any]:
    from .llm_local import LauraOllamaAnalyzer, check_ollama_running

    llm_latest_path = Path("reports/laura_profitability_llm_latest.json")
    llm_baseline_latest_path = Path("reports/laura_profitability_llm_baseline_latest.json")
    llm_latest: dict[str, Any] = {
        "path": str(llm_latest_path),
        "exists": llm_latest_path.exists(),
        "read_ok": False,
        "fallback_detected": None,
        "model": None,
        "age_min": None,
        "error": None,
    }

    if llm_latest_path.exists():
        try:
            row = json.loads(llm_latest_path.read_text(encoding="utf-8"))
            model = str(row.get("model", "")).strip()
            llm_latest["read_ok"] = True
            llm_latest["model"] = model or None
            llm_latest["fallback_detected"] = "(fallback)" in model

            ts = str(row.get("timestamp", "")).strip()
            if ts:
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    llm_latest["age_min"] = int((datetime.now(UTC) - dt).total_seconds() // 60)
                except Exception:
                    llm_latest["age_min"] = None
        except Exception as exc:
            llm_latest["error"] = str(exc)

    llm_baseline: dict[str, Any] = _json_file_report(llm_baseline_latest_path)
    if llm_baseline.get("read_ok"):
        data = llm_baseline.get("data", {}) if isinstance(llm_baseline.get("data"), dict) else {}
        llm_baseline["posture"] = data.get("posture")
        llm_baseline["fallback_rate_pct"] = data.get("fallback_rate_pct")
        counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
        llm_baseline["total_runs"] = counts.get("total_runs")
        llm_baseline["native_runs"] = counts.get("native_runs")
        llm_baseline["fallback_runs"] = counts.get("fallback_runs")
        latency_all = data.get("latency_ms", {}).get("all", {}) if isinstance(data.get("latency_ms"), dict) else {}
        llm_baseline["p95_ms"] = latency_all.get("p95_ms")

    report: dict[str, Any] = {
        "python": {
            "version": sys.version.split()[0],
            "ok": sys.version_info >= (3, 10),
        },
        "env_file": _env_file_report(Path(env_file)),
        "shopee_config": {
            "ok": False,
            "error": None,
            "partner_id_present": False,
            "partner_key_present": False,
            "redirect_url_present": False,
            "default_shop_id_present": False,
            "default_access_token_present": False,
            "default_refresh_token_present": False,
        },
        "llm_local": {
            "ollama_reachable": check_ollama_running(),
            "models_supported": list(LauraOllamaAnalyzer.MODELS.keys()),
            "latest_result": llm_latest,
            "baseline_latest": llm_baseline,
        },
    }

    try:
        cfg = load_config()
        report["shopee_config"]["ok"] = True
        report["shopee_config"]["partner_id_present"] = bool(cfg.partner_id)
        report["shopee_config"]["partner_key_present"] = bool(cfg.partner_key)
        report["shopee_config"]["redirect_url_present"] = bool(cfg.redirect_url)
        report["shopee_config"]["default_shop_id_present"] = cfg.default_shop_id is not None
        report["shopee_config"]["default_access_token_present"] = bool(cfg.default_access_token)
        report["shopee_config"]["default_refresh_token_present"] = bool(cfg.default_refresh_token)
    except ConfigError as exc:
        # Keep command non-fatal for diagnostics.
        report["shopee_config"]["error"] = str(exc)

    overall_ok = (
        report["python"]["ok"]
        and bool(report["env_file"]["exists"])
        and bool(report["env_file"].get("secure_mode"))
        and bool(report["shopee_config"]["ok"])
        and bool(report["llm_local"]["ollama_reachable"])
    )
    report["overall_ok"] = overall_ok
    return report


def _load_recent_jsonl(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    for raw_line in lines[-limit:]:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            item = json.loads(raw_line)
        except Exception:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _load_recent_log_events(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    events: list[dict[str, Any]] = []
    for raw_line in lines[-limit:]:
        raw_line = raw_line.strip()
        if not raw_line.startswith("{"):
            continue
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _activity_report(limit: int = 10) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "recent_actions": [],
        "latest_chat": None,
        "latest_price_change": None,
        "latest_stock_change": None,
        "recent_log_commands": [],
    }

    chat_events = _load_recent_jsonl(Path("reports/chat_outbound.jsonl"), limit=limit)
    if chat_events:
        latest_chat = chat_events[-1]
        report["latest_chat"] = {
            "timestamp": latest_chat.get("timestamp"),
            "buyer_id": latest_chat.get("buyer_id"),
            "action": latest_chat.get("action"),
            "message": latest_chat.get("message"),
        }
        report["recent_actions"].append({
            "type": "chat",
            "timestamp": latest_chat.get("timestamp"),
            "summary": f"Respondeu chat para buyer_id={latest_chat.get('buyer_id')}",
        })

    product_events = _load_recent_jsonl(Path("reports/stock_price_changes.jsonl"), limit=limit)
    if product_events:
        latest_change = product_events[-1]
        action = latest_change.get("action")
        item_id = latest_change.get("item_id")
        if action == "set_price":
            report["latest_price_change"] = {
                "timestamp": latest_change.get("timestamp"),
                "item_id": item_id,
                "variation_id": latest_change.get("variation_id"),
                "price": latest_change.get("price"),
            }
            report["recent_actions"].append({
                "type": "price",
                "timestamp": latest_change.get("timestamp"),
                "summary": f"Alterou preço do item {item_id} para {latest_change.get('price')}",
            })
        elif action == "set_stock":
            report["latest_stock_change"] = {
                "timestamp": latest_change.get("timestamp"),
                "item_id": item_id,
                "variation_id": latest_change.get("variation_id"),
                "stock": latest_change.get("stock"),
            }
            report["recent_actions"].append({
                "type": "stock",
                "timestamp": latest_change.get("timestamp"),
                "summary": f"Alterou estoque do item {item_id} para {latest_change.get('stock')}",
            })

    ops_events = _load_recent_log_events(Path("logs/laura_operations.log"), limit=200)
    for event in reversed(ops_events[-limit:]):
        message = str(event.get("message", ""))
        command = str(event.get("command", ""))
        if command:
            report["recent_log_commands"].append({
                "timestamp": event.get("timestamp"),
                "command": command,
                "message": message,
            })

    report["recent_actions"] = report["recent_actions"][:limit]
    report["recent_log_commands"] = report["recent_log_commands"][:limit]
    return report


def _print_activity_report(report: dict[str, Any]) -> None:
    print("Laura activity feed")
    print(f"Generated at: {report.get('generated_at')}")
    print("=" * 60)

    latest_chat = report.get("latest_chat")
    if latest_chat:
        print(f"Latest chat: {latest_chat.get('timestamp')} buyer_id={latest_chat.get('buyer_id')} message={latest_chat.get('message')}")
    else:
        print("Latest chat: none found")

    latest_price_change = report.get("latest_price_change")
    if latest_price_change:
        print(f"Latest price change: {latest_price_change.get('timestamp')} item_id={latest_price_change.get('item_id')} price={latest_price_change.get('price')}")
    else:
        print("Latest price change: none found")

    latest_stock_change = report.get("latest_stock_change")
    if latest_stock_change:
        print(f"Latest stock change: {latest_stock_change.get('timestamp')} item_id={latest_stock_change.get('item_id')} stock={latest_stock_change.get('stock')}")
    else:
        print("Latest stock change: none found")

    print()
    print("Recent actions:")
    if report.get("recent_actions"):
        for action in report["recent_actions"]:
            print(f"- {action.get('timestamp')}: {action.get('summary')}")
    else:
        print("- no recent chat/price/stock actions found")

    print()
    print("Recent command activity:")
    if report.get("recent_log_commands"):
        for entry in report["recent_log_commands"]:
            print(f"- {entry.get('timestamp')}: {entry.get('command')} :: {entry.get('message')}")
    else:
        print("- no recent commands found in logs")


def _coerce_positive_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("R$", "").replace(" ", "")
        cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.count(",") == 1 and cleaned.count(".") >= 1 else cleaned
        try:
            parsed = float(cleaned)
            return parsed if parsed >= 0 else None
        except Exception:
            return None
    return None


def _coerce_positive_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            number = int(value)
            return number if number >= 0 else None
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            if not cleaned:
                return None
            number = int(float(cleaned))
            return number if number >= 0 else None
    except Exception:
        return None
    return None


def _find_revenue_candidate(payload: Any) -> float | None:
    preferred_keys = (
        "buyer_total_amount",  # Shopee escrow detail: buyer payment total
        "total_amount",
        "paid_amount",
        "payment_amount",
        "order_total",
        "order_amount",
        "total_price",
        "total_item_amount",
        "grand_total",
        "amount",
    )
    blocked_keys = ("shipping", "refund", "discount", "voucher", "coupon", "fee", "tax")

    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload:
                candidate = _coerce_positive_float(payload.get(key))
                if candidate is not None:
                    return candidate

        for key, value in payload.items():
            key_lower = str(key).lower()
            if any(block in key_lower for block in blocked_keys):
                continue
            candidate = _find_revenue_candidate(value)
            if candidate is not None:
                return candidate

    elif isinstance(payload, list):
        for item in payload:
            candidate = _find_revenue_candidate(item)
            if candidate is not None:
                return candidate

    return None


def _order_sn_from_payload(payload: dict[str, Any]) -> str:
    for key in ("order_sn", "ordersn", "orderSn", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _find_stock_candidate(payload: Any) -> int | None:
    preferred_keys = (
        "stock",
        "current_stock",
        "stock_on_hand",
        "stock_available",
        "available_stock",
        "normal_stock",
        "quantity",
        "available_quantity",
    )

    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload:
                candidate = _coerce_positive_int(payload.get(key))
                if candidate is not None:
                    return candidate

        for value in payload.values():
            candidate = _find_stock_candidate(value)
            if candidate is not None:
                return candidate

    elif isinstance(payload, list):
        for item in payload:
            candidate = _find_stock_candidate(item)
            if candidate is not None:
                return candidate

    return None


def _find_price_candidate(payload: Any) -> float | None:
    preferred_keys = (
        "current_price",
        "sale_price",
        "price",
        "shop_price",
        "model_price",
        "original_price",
        "item_price",
        "display_price",
    )

    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload:
                candidate = _coerce_positive_float(payload.get(key))
                if candidate is not None:
                    return candidate

        for value in payload.values():
            candidate = _find_price_candidate(value)
            if candidate is not None:
                return candidate

    elif isinstance(payload, list):
        for item in payload:
            candidate = _find_price_candidate(item)
            if candidate is not None:
                return candidate

    return None


def _extract_order_items(payload: Any) -> list[dict[str, Any]]:
    """Try to extract order items (item_id/variation_id/quantity) from a Shopee order payload."""
    candidates: list[dict[str, Any]] = []

    def visit(obj: Any):
        if isinstance(obj, dict):
            # common list keys
            for k in ("order_items", "items", "item_list", "order_item_list"):
                if k in obj and isinstance(obj[k], list):
                    for it in obj[k]:
                        if isinstance(it, dict):
                            iid = it.get("item_id") or it.get("itemid") or it.get("itemId") or it.get("sku")
                            vid = it.get("variation_id") or it.get("variationid") or it.get("variationId")
                            qty = it.get("quantity") or it.get("qty") or it.get("item_quantity") or it.get("normal_stock")
                            try:
                                q = int(qty) if qty is not None else 1
                            except Exception:
                                q = 1
                            candidates.append({"item_id": str(iid) if iid is not None else "", "variation_id": vid, "quantity": q})
            for v in obj.values():
                visit(v)
        elif isinstance(obj, list):
            for it in obj:
                visit(it)

    visit(payload)
    return candidates


def _build_stock_monitor_report(
    client: ShopeeClient,
    *,
    access_token: str,
    shop_id: int,
    low_stock_threshold: int,
    max_items: int = 50,
    page_size: int = 50,
) -> dict[str, Any]:
    items_seen = 0
    low_stock_items: list[dict[str, Any]] = []
    sample_items: list[dict[str, Any]] = []
    cursor = 0

    while items_seen < max_items:
        resp = client.get_item_list(
            access_token=access_token,
            shop_id=shop_id,
            offset=cursor,
            page_size=page_size,
        )
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", []) if isinstance(body, dict) else []
        if not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue

            items_seen += 1
            if items_seen > max_items:
                break

            item_id = item.get("item_id") or item.get("id")
            item_name = item.get("item_name") or item.get("name") or f"item-{item_id}"
            stock_value = None
            source = "list"

            try:
                if item_id is not None:
                    resp_detail = client.get_item_detail(
                        access_token=access_token,
                        shop_id=shop_id,
                        item_id=int(item_id),
                    )
                    detail_body = resp_detail.data.get("response", {}) if isinstance(resp_detail.data, dict) else {}
                    if isinstance(detail_body, dict):
                        # Prefer variation-level stock if present; otherwise item-level stock.
                        variations = detail_body.get("variation_list") or detail_body.get("model_list") or detail_body.get("variations") or []
                        variation_stocks: list[int] = []
                        if isinstance(variations, list):
                            for variation in variations:
                                stock_candidate = _find_stock_candidate(variation)
                                if stock_candidate is not None:
                                    variation_stocks.append(stock_candidate)
                        if variation_stocks:
                            stock_value = sum(variation_stocks)
                            source = "variations"
                        else:
                            stock_value = _find_stock_candidate(detail_body)
                            source = "detail"
            except Exception:
                stock_value = _find_stock_candidate(item)
                source = "list"

            if stock_value is None:
                continue

            record = {
                "item_id": item_id,
                "item_name": item_name,
                "stock": stock_value,
                "threshold": low_stock_threshold,
                "source": source,
            }
            if len(sample_items) < 10:
                sample_items.append(record)

            if stock_value <= low_stock_threshold:
                low_stock_items.append(record)

        cursor += page_size
        if not body.get("has_next_page"):
            break

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "shop_id": shop_id,
        "items_seen": items_seen,
        "low_stock_threshold": low_stock_threshold,
        "low_stock_items": low_stock_items,
        "low_stock_count": len(low_stock_items),
        "sample_items": sample_items,
        "inventory_ok": True,
    }


def _build_margin_review_report(
    client: ShopeeClient,
    *,
    access_token: str,
    shop_id: int,
    low_margin_threshold: float = 0.20,
    target_margin_floor: float = 0.25,
    max_items: int = 200,
    page_size: int = 50,
) -> dict[str, Any]:
    items_seen = 0
    reviewed_entries: list[dict[str, Any]] = []
    low_margin_entries: list[dict[str, Any]] = []
    missing_cost_entries: list[dict[str, Any]] = []
    missing_price_entries: list[dict[str, Any]] = []
    cursor = 0

    while items_seen < max_items:
        resp = client.get_item_list(
            access_token=access_token,
            shop_id=shop_id,
            offset=cursor,
            page_size=page_size,
        )
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", []) if isinstance(body, dict) else []
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue

            items_seen += 1
            if items_seen > max_items:
                break

            item_id = _first_present_text(item, "item_id", "id")
            if not item_id:
                continue

            item_name = _first_present_text(item, "item_name", "name") or f"item-{item_id}"
            try:
                detail_resp = client.get_item_detail(
                    access_token=access_token,
                    shop_id=shop_id,
                    item_id=int(item_id),
                )
                detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
            except Exception:
                detail_body = item

            variations = detail_body.get("variation_list") or detail_body.get("model_list") or detail_body.get("variations") or []
            if not isinstance(variations, list) or not variations:
                variations = [detail_body]

            for variation in variations:
                if not isinstance(variation, dict):
                    continue

                variation_id = _first_present_text(variation, "variation_id", "model_id", "variationid", "modelid")
                variation_name = _first_present_text(variation, "variation_name", "name", "model_name") or item_name
                variation_sku = _first_present_text(variation, "variation_sku", "sku", "model_sku")
                price = _find_price_candidate(variation)
                cost = _get_cost_for_item(item_id)

                entry: dict[str, Any] = {
                    "item_id": item_id,
                    "item_name": item_name,
                    "variation_id": variation_id or None,
                    "variation_name": variation_name,
                    "sku": variation_sku or None,
                    "price": round(price, 2) if price is not None else None,
                    "cost": round(cost, 2) if cost is not None else None,
                }

                if price is None:
                    entry["status"] = "missing_price"
                    missing_price_entries.append(entry)
                    reviewed_entries.append(entry)
                    continue

                if cost is None:
                    entry["status"] = "missing_cost"
                    missing_cost_entries.append(entry)
                    reviewed_entries.append(entry)
                    continue

                margin_ratio = (price - cost) / price if price > 0 else None
                entry["margin_pct"] = round((margin_ratio or 0.0) * 100, 2) if margin_ratio is not None else None
                recommended_price = cost / (1 - target_margin_floor) if 0 < target_margin_floor < 1 else None
                entry["recommended_price"] = round(recommended_price, 2) if recommended_price is not None else None

                if margin_ratio is not None and margin_ratio < low_margin_threshold:
                    entry["status"] = "negative_margin" if margin_ratio <= 0 else "low_margin"
                    low_margin_entries.append(entry)
                else:
                    entry["status"] = "ok"

                reviewed_entries.append(entry)

        cursor += page_size
        if not body.get("has_next_page"):
            break

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "shop_id": shop_id,
        "low_margin_threshold": low_margin_threshold,
        "target_margin_floor": target_margin_floor,
        "items_seen": items_seen,
        "reviewed_count": len(reviewed_entries),
        "ok_count": sum(1 for entry in reviewed_entries if entry.get("status") == "ok"),
        "low_margin_count": len(low_margin_entries),
        "missing_cost_count": len(missing_cost_entries),
        "missing_price_count": len(missing_price_entries),
        "top_risks": sorted(
            [entry for entry in low_margin_entries if entry.get("margin_pct") is not None],
            key=lambda entry: entry.get("margin_pct", 0.0),
        )[:20],
        "reviewed_entries": reviewed_entries,
        "low_margin_entries": low_margin_entries,
        "missing_cost_entries": missing_cost_entries,
        "missing_price_entries": missing_price_entries,
    }


def _create_margin_remediation_case(report: dict[str, Any], *, reports_dir: Path) -> dict[str, Any]:
    top_risks = report.get("top_risks", []) if isinstance(report.get("top_risks"), list) else []
    case_id = f"protect_margin-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    case = {
        "case_id": case_id,
        "action_key": "protect_margin",
        "title": "Protect Margin",
        "created_at": datetime.now(UTC).isoformat(),
        "executed": False,
        "execute_on_approve": True,
        "payload": top_risks,
        "report_path": str(reports_dir / "laura_product_margin_review_latest.json"),
        "report_summary": {
            "items_seen": report.get("items_seen"),
            "reviewed_count": report.get("reviewed_count"),
            "low_margin_count": report.get("low_margin_count"),
            "missing_cost_count": report.get("missing_cost_count"),
            "missing_price_count": report.get("missing_price_count"),
        },
    }

    cases_path = reports_dir / "laura_remediation_cases.jsonl"
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    with cases_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(case, ensure_ascii=False) + "\n")

    audit_path = reports_dir / "laura_remediation_audit.jsonl"
    _append_audit_line(audit_path, {
        "timestamp": datetime.now(UTC).isoformat(),
        "action": "create_margin_remediation_case",
        "case_id": case_id,
        "items": len(top_risks),
        "report_path": case["report_path"],
    })

    return case


def _send_telegram_remediation_case(case: dict[str, Any], *, reports_dir: Path) -> bool:
    token = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    top_risks = case.get("payload", []) if isinstance(case.get("payload"), list) else []
    lines = [
        "Laura Margin Review",
        f"Case: {case.get('case_id')}",
        f"Ação: {case.get('action_key')}",
        f"Itens críticos: {len(top_risks)}",
    ]
    for entry in top_risks[:5]:
        if not isinstance(entry, dict):
            continue
        label = entry.get("variation_name") or entry.get("item_name") or entry.get("item_id") or "item"
        lines.append(
            f"- {label}: preço={entry.get('price')} custo={entry.get('cost')} margem={entry.get('margin_pct')}% alvo={entry.get('recommended_price')}"
        )

    keyboard = {
        "inline_keyboard": [[
            {"text": "Aprovar", "callback_data": f"approve:{case['case_id']}"},
            {"text": "Cancelar", "callback_data": f"cancel:{case['case_id']}"},
        ]],
    }

    try:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        _append_audit_line(reports_dir / "laura_remediation_audit.jsonl", {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "notify_margin_remediation_case",
            "case_id": case.get("case_id"),
            "top_risks": len(top_risks),
        })
        return True
    except Exception:
        return False


def _build_erp_snapshot(
    client: ShopeeClient,
    *,
    access_token: str,
    shop_id: int,
    days: int,
    low_stock_threshold: int,
    low_margin_threshold: float,
    target_margin_floor: float,
    max_items: int,
    page_size: int,
) -> dict[str, Any]:
    profitability = _ingest_order_revenue_report(
        client,
        access_token=access_token,
        shop_id=shop_id,
        days=days,
        page_size=page_size,
        max_orders=200,
    )
    inventory = _build_stock_monitor_report(
        client,
        access_token=access_token,
        shop_id=shop_id,
        low_stock_threshold=low_stock_threshold,
        max_items=max_items,
        page_size=page_size,
    )
    margin_review = _build_margin_review_report(
        client,
        access_token=access_token,
        shop_id=shop_id,
        low_margin_threshold=low_margin_threshold,
        target_margin_floor=target_margin_floor,
        max_items=max_items,
        page_size=page_size,
    )
    health = _load_json_file("reports/laura_health_latest.json", "health report") or {}

    metrics = profitability if isinstance(profitability, dict) else {}
    profit_metrics = metrics.get("metrics", {}) if isinstance(metrics.get("metrics"), dict) else {}

    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(),
        "shop_id": shop_id,
        "financial": profitability,
        "inventory": inventory,
        "margin_review": margin_review,
        "health": health,
        "erp_summary": {
            "orders": profit_metrics.get("orders"),
            "revenue": profit_metrics.get("revenue"),
            "profit": profit_metrics.get("profit"),
            "margin_pct": profit_metrics.get("margin_pct"),
            "refund_rate_pct": profit_metrics.get("refund_rate_pct"),
            "low_stock_count": inventory.get("low_stock_count") if isinstance(inventory, dict) else None,
            "low_margin_count": margin_review.get("low_margin_count") if isinstance(margin_review, dict) else None,
            "health_status": health.get("overall_status") or health.get("status"),
        },
    }
    return snapshot


def _decide_commercial_strategy(snapshot: dict[str, Any]) -> dict[str, Any]:
    financial = snapshot.get("financial", {}) if isinstance(snapshot.get("financial"), dict) else {}
    metrics = financial.get("metrics", {}) if isinstance(financial.get("metrics"), dict) else {}
    inventory = snapshot.get("inventory", {}) if isinstance(snapshot.get("inventory"), dict) else {}
    margin_review = snapshot.get("margin_review", {}) if isinstance(snapshot.get("margin_review"), dict) else {}
    health = snapshot.get("health", {}) if isinstance(snapshot.get("health"), dict) else {}

    revenue = float(metrics.get("revenue", 0.0) or 0.0)
    profit = float(metrics.get("profit", 0.0) or 0.0)
    margin_pct = float(metrics.get("margin_pct", 0.0) or 0.0)
    refund_rate_pct = float(metrics.get("refund_rate_pct", 0.0) or 0.0)
    roas = metrics.get("roas")
    low_stock_count = int(inventory.get("low_stock_count", 0) or 0)
    low_margin_count = int(margin_review.get("low_margin_count", 0) or 0)
    health_status = str(health.get("overall_status") or health.get("status") or health.get("overallStatus") or "UNKNOWN").upper()

    objectives: list[str] = []
    secondary_actions: list[str] = []
    primary_action = "monitor_only"
    primary_reason = "No commercial breach detected; keep observing."
    commercial_mode = "stabilize"

    if health_status not in {"HEALTHY", "OK", "GOOD"}:
        commercial_mode = "stabilize"
        objectives.append("Restaurar saúde operacional antes de escalar")
        secondary_actions.append("Revisar alertas e latência da API antes de decisões agressivas")

    if low_margin_count > 0 or margin_pct < 20:
        primary_action = "protect_margin"
        commercial_mode = "optimize_margin"
        primary_reason = "Itens com margem baixa identificados; prioridade é proteger margem e elevar preço mínimo."
        objectives.append("Proteger margem")
        secondary_actions.append("Reprecificar SKUs abaixo do piso")
        secondary_actions.append("Revisar custos cadastrados em produtos com margem crítica")
    elif refund_rate_pct >= 5.0 or profit < 0:
        primary_action = "refund_guard"
        commercial_mode = "reduce_loss"
        primary_reason = "Sinais de perdas/reembolsos exigem contenção operacional imediata."
        objectives.append("Reduzir perdas e reembolsos")
        secondary_actions.append("Auditar itens com maior incidência de reembolso")
    elif low_stock_count > 0 and revenue > 0:
        primary_action = "scale_winners"
        commercial_mode = "grow_winners"
        primary_reason = "Há demanda e o estoque ainda permite escalar os produtos com melhor performance."
        objectives.append("Escalar vencedores")
        secondary_actions.append("Reforçar estoque dos itens vencedores")
    elif roas is not None:
        try:
            roas_value = float(roas)
        except Exception:
            roas_value = None
        if roas_value is not None and roas_value < 1.0:
            primary_action = "pause_low_roas_ads"
            commercial_mode = "trim_ads"
            primary_reason = "ROAS baixo detectado; a estratégia prioriza corte de desperdício publicitário."
            objectives.append("Cortar mídia ineficiente")
            secondary_actions.append("Pausar campanhas abaixo do piso de ROAS")
    elif revenue <= 0:
        commercial_mode = "observe"
        primary_reason = "Sem receita detectada; estratégia permanece em observação até o tráfego voltar."

    if not objectives:
        objectives.append("Manter operação estável")

    risks = []
    if low_margin_count > 0:
        risks.append(f"{low_margin_count} item(ns) abaixo do piso de margem")
    if low_stock_count > 0:
        risks.append(f"{low_stock_count} item(ns) com estoque baixo")
    if refund_rate_pct >= 5.0:
        risks.append(f"Refund rate alto: {refund_rate_pct:.2f}%")
    if health_status not in {"HEALTHY", "OK", "GOOD"}:
        risks.append(f"Saúde operacional: {health_status}")

    recommended_actions = [
        {
            "action_key": primary_action,
            "reason": primary_reason,
            "supported": primary_action in {"protect_margin", "scale_winners", "pause_low_roas_ads", "refund_guard"},
        }
    ]
    for secondary in secondary_actions:
        recommended_actions.append({"action_key": "recommendation", "reason": secondary, "supported": False})

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "commercial_mode": commercial_mode,
        "primary_action_key": primary_action,
        "primary_reason": primary_reason,
        "objectives": objectives,
        "risks": risks,
        "recommended_actions": recommended_actions,
        "guardrails": {
            "min_margin_pct": 20.0,
            "target_margin_floor": margin_review.get("target_margin_floor", 0.25),
            "low_stock_threshold": inventory.get("low_stock_threshold"),
            "max_inventory_items": inventory.get("items_seen"),
            "profit": profit,
            "revenue": revenue,
            "margin_pct": margin_pct,
            "refund_rate_pct": refund_rate_pct,
            "health_status": health_status,
        },
        "supported_for_approval": primary_action in {"protect_margin", "scale_winners", "pause_low_roas_ads", "refund_guard"},
    }


def _create_commercial_remediation_case(strategy: dict[str, Any], snapshot: dict[str, Any], *, reports_dir: Path) -> dict[str, Any] | None:
    action_key = str(strategy.get("primary_action_key") or "monitor_only")
    if action_key == "monitor_only":
        return None

    payload: list[dict[str, Any]] = []
    if action_key == "protect_margin":
        payload = snapshot.get("margin_review", {}).get("low_margin_entries", []) if isinstance(snapshot.get("margin_review"), dict) else []
    elif action_key == "scale_winners":
        payload = snapshot.get("inventory", {}).get("sample_items", []) if isinstance(snapshot.get("inventory"), dict) else []
    elif action_key == "refund_guard" or action_key == "pause_low_roas_ads":
        payload = snapshot.get("financial", {}).get("sample_orders", []) if isinstance(snapshot.get("financial"), dict) else []

    case = {
        "case_id": f"{action_key}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "action_key": action_key,
        "title": f"Commercial strategy: {action_key}",
        "created_at": datetime.now(UTC).isoformat(),
        "executed": False,
        "execute_on_approve": True,
        "payload": payload,
        "strategy": strategy,
        "snapshot": {
            "financial": snapshot.get("financial", {}).get("metrics", {}) if isinstance(snapshot.get("financial"), dict) else {},
            "inventory": {
                "low_stock_count": snapshot.get("inventory", {}).get("low_stock_count") if isinstance(snapshot.get("inventory"), dict) else None,
            },
            "margin_review": {
                "low_margin_count": snapshot.get("margin_review", {}).get("low_margin_count") if isinstance(snapshot.get("margin_review"), dict) else None,
            },
        },
    }

    cases_path = reports_dir / "laura_remediation_cases.jsonl"
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    with cases_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(case, ensure_ascii=False) + "\n")

    _append_audit_line(reports_dir / "laura_remediation_audit.jsonl", {
        "timestamp": datetime.now(UTC).isoformat(),
        "action": "create_commercial_remediation_case",
        "case_id": case["case_id"],
        "action_key": action_key,
        "payload_items": len(payload),
    })

    return case


def _send_telegram_commercial_case(case: dict[str, Any], strategy: dict[str, Any], *, reports_dir: Path) -> bool:
    token = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    action_key = str(case.get("action_key", "monitor_only"))
    lines = [
        "Laura Commercial Control Center",
        f"Case: {case.get('case_id')}",
        f"Modo: {strategy.get('commercial_mode')}",
        f"Ação principal: {action_key}",
        f"Razão: {strategy.get('primary_reason')}",
    ]

    for item in (case.get("payload", []) or [])[:5]:
        if not isinstance(item, dict):
            continue
        label = item.get("variation_name") or item.get("item_name") or item.get("order_sn") or item.get("item_id") or "item"
        lines.append(f"- {label}")

    keyboard = {
        "inline_keyboard": [[
            {"text": "Aprovar", "callback_data": f"approve:{case['case_id']}"},
            {"text": "Cancelar", "callback_data": f"cancel:{case['case_id']}"},
        ]],
    }

    try:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        _append_audit_line(reports_dir / "laura_remediation_audit.jsonl", {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "notify_commercial_remediation_case",
            "case_id": case.get("case_id"),
            "action_key": action_key,
        })
        return True
    except Exception:
        return False


def _build_erp_state(snapshot: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    financial = snapshot.get("financial", {}) if isinstance(snapshot.get("financial"), dict) else {}
    inventory = snapshot.get("inventory", {}) if isinstance(snapshot.get("inventory"), dict) else {}
    margin_review = snapshot.get("margin_review", {}) if isinstance(snapshot.get("margin_review"), dict) else {}
    health = snapshot.get("health", {}) if isinstance(snapshot.get("health"), dict) else {}
    financial_metrics = financial.get("metrics", {}) if isinstance(financial.get("metrics"), dict) else {}

    product_costs = _load_product_costs()
    low_stock_items = inventory.get("low_stock_items", []) if isinstance(inventory.get("low_stock_items"), list) else []
    low_margin_entries = margin_review.get("low_margin_entries", []) if isinstance(margin_review.get("low_margin_entries"), list) else []

    revenue = float(financial_metrics.get("revenue", 0.0) or 0.0)
    profit = float(financial_metrics.get("profit", 0.0) or 0.0)
    margin_pct = float(financial_metrics.get("margin_pct", 0.0) or 0.0)
    refund_rate_pct = float(financial_metrics.get("refund_rate_pct", 0.0) or 0.0)
    low_stock_count = int(inventory.get("low_stock_count", 0) or 0)
    low_margin_count = int(margin_review.get("low_margin_count", 0) or 0)
    health_status = str(health.get("overall_status") or health.get("status") or "UNKNOWN").upper()

    score = 100.0
    if revenue <= 0:
        score -= 35
    if profit <= 0:
        score -= 15
    if margin_pct <= 0:
        score -= 10
    elif margin_pct < 20:
        score -= min(20, (20 - margin_pct) * 1.5)
    if refund_rate_pct >= 5:
        score -= min(20, (refund_rate_pct - 4) * 2)
    score -= min(25, low_stock_count * 2.5)
    score -= min(30, low_margin_count * 4)
    if health_status not in {"HEALTHY", "OK", "GOOD"}:
        score -= 15
    score = max(0.0, min(100.0, score))

    if score >= 80:
        erp_status = "healthy"
    elif score >= 60:
        erp_status = "watch"
    elif score >= 40:
        erp_status = "at_risk"
    else:
        erp_status = "critical"

    modules = {
        "finance": {
            "revenue": revenue,
            "profit": profit,
            "margin_pct": margin_pct,
            "refund_rate_pct": refund_rate_pct,
            "orders": financial_metrics.get("orders", 0),
        },
        "inventory": {
            "low_stock_count": low_stock_count,
            "low_stock_threshold": inventory.get("low_stock_threshold"),
            "tracked_items": inventory.get("items_seen"),
        },
        "pricing": {
            "costs_loaded": len(product_costs),
            "low_margin_count": low_margin_count,
            "target_margin_floor": margin_review.get("target_margin_floor", 0.25),
        },
        "health": {
            "status": health_status,
            "alerts": len(health.get("alerts", [])) if isinstance(health.get("alerts"), list) else 0,
        },
        "automation": {
            "recommended_primary_action": strategy.get("primary_action_key"),
            "commercial_mode": strategy.get("commercial_mode"),
            "supported_for_approval": strategy.get("supported_for_approval"),
        },
    }

    next_actions: list[dict[str, Any]] = []
    primary_action = str(strategy.get("primary_action_key") or "monitor_only")
    if primary_action != "monitor_only":
        next_actions.append({
            "action_key": primary_action,
            "priority": 1,
            "reason": strategy.get("primary_reason"),
        })

    if low_stock_count > 0:
        next_actions.append({
            "action_key": "replenish_stock",
            "priority": 2,
            "reason": "Estoque baixo detectado no snapshot ERP",
            "targets": low_stock_items[:10],
        })

    if low_margin_count > 0:
        next_actions.append({
            "action_key": "protect_margin",
            "priority": 2,
            "reason": "Margem abaixo do piso em itens críticos",
            "targets": low_margin_entries[:10],
        })

    if refund_rate_pct >= 5.0:
        next_actions.append({
            "action_key": "refund_guard",
            "priority": 2,
            "reason": "Taxa de reembolso elevada no snapshot ERP",
        })

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "erp_status": erp_status,
        "erp_score": round(score, 2),
        "snapshot": snapshot,
        "strategy": strategy,
        "modules": modules,
        "next_actions": next_actions,
        "decision_summary": {
            "primary_action_key": primary_action,
            "commercial_mode": strategy.get("commercial_mode"),
            "objective_count": len(strategy.get("objectives", []) if isinstance(strategy.get("objectives"), list) else []),
            "risk_count": len(strategy.get("risks", []) if isinstance(strategy.get("risks"), list) else []),
        },
    }


def _persist_erp_state(state: dict[str, Any], *, reports_dir: Path) -> tuple[Path, Path]:
    latest_path = reports_dir / "laura_erp_state_latest.json"
    history_path = reports_dir / "laura_erp_state_history.jsonl"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(state, ensure_ascii=False) + "\n")
    return latest_path, history_path


def _ingest_order_revenue_report(
    client: ShopeeClient,
    *,
    access_token: str,
    shop_id: int,
    days: int,
    page_size: int = 50,
    max_orders: int = 200,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    time_to = int(now.timestamp())
    time_from = int((now - timedelta(days=days)).timestamp())
    max_window_seconds = 15 * 24 * 3600

    orders_seen = 0
    paid_orders = 0
    revenue_total = 0.0
    total_cogs = 0.0
    sample_orders: list[dict[str, Any]] = []
    window_start = time_from

    while window_start < time_to and orders_seen < max_orders:
        window_end = min(window_start + max_window_seconds, time_to)
        cursor = ""

        while orders_seen < max_orders:
            resp = client.get_order_list(
                access_token=access_token,
                shop_id=shop_id,
                time_from=window_start,
                time_to=window_end,
                time_range_field="update_time",
                order_status="COMPLETED",
                page_size=page_size,
                cursor=cursor,
            )
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            orders = body.get("order_list", []) if isinstance(body, dict) else []

            # Diagnostic logging: track how many orders the API returned
            info(
                f"[ingest_order_revenue] API returned {len(orders)} orders in window "
                f"{window_start}->{window_end} (total seen: {orders_seen})"
            )

            if not orders:
                break

            for order in orders:
                if not isinstance(order, dict):
                    continue
                orders_seen += 1
                if orders_seen > max_orders:
                    break

                order_sn = _order_sn_from_payload(order)
                detail_payload: dict[str, Any] | None = None
                amount = _find_revenue_candidate(order)

                if amount is None and order_sn:
                    try:
                        detail_resp = client.get_order_detail(access_token=access_token, shop_id=shop_id, order_sn=order_sn)
                        detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
                        if isinstance(detail_body, dict):
                            detail_payload = detail_body
                            amount = _find_revenue_candidate(detail_body)
                    except Exception:
                        detail_payload = None

                # Prefer authoritative escrow detail when available
                escrow_amount = None
                if order_sn:
                    try:
                        escrow_resp = client.get_escrow_detail(access_token=access_token, shop_id=shop_id, order_sn=order_sn)
                        escrow_body = escrow_resp.data.get("response", {}) if isinstance(escrow_resp.data, dict) else {}
                        if isinstance(escrow_body, dict):
                            # try common fields in escrow detail
                            escrow_amount = _find_revenue_candidate(escrow_body)
                    except Exception:
                        escrow_amount = None

                if escrow_amount is not None:
                    amount = escrow_amount

                if amount is None:
                    continue

                # compute COGS for the order when possible using product_costs
                order_cogs = 0.0
                items = []
                if isinstance(detail_payload, dict):
                    items = _extract_order_items(detail_payload)
                if not items:
                    # try to extract from list payload as fallback
                    items = _extract_order_items(order)
                if not items and order_sn:
                    try:
                        detail_resp = client.get_order_detail(access_token=access_token, shop_id=shop_id, order_sn=order_sn)
                        detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
                        if isinstance(detail_body, dict):
                            detail_payload = detail_body
                            items = _extract_order_items(detail_body)
                    except Exception:
                        detail_payload = detail_payload if isinstance(detail_payload, dict) else None

                for it in items:
                    iid = it.get("item_id") or ""
                    qty = int(it.get("quantity") or 1)
                    cost = None
                    if iid:
                        cost = _get_cost_for_item(str(iid))
                    if cost is None:
                        # unknown cost treated as 0.0
                        continue
                    order_cogs += float(cost) * qty

                paid_orders += 1
                revenue_total += amount
                total_cogs += order_cogs
                if len(sample_orders) < 10:
                    sample_orders.append({
                        "order_sn": order_sn,
                        "amount": round(amount, 2),
                        "source": "detail" if detail_payload else "list",
                    })

            cursor = str(body.get("next_cursor", "") or "") if isinstance(body, dict) else ""
            if not cursor:
                break

        window_start = window_end

    event = {
        "timestamp": now.isoformat(),
        "source": "ingest_order_revenue",
        "window_days": days,
        "shop_id": shop_id,
        "orders_seen": orders_seen,
        "paid_orders": paid_orders,
        "revenue": round(revenue_total, 2),
        "cogs": round(total_cogs, 2),
        "ad_spend": 0.0,
        "shipping_subsidy": 0.0,
        "refunds": 0.0,
        "orders": paid_orders,
        "sample_orders": sample_orders,
    }

    # Log final statistics
    info(f"[ingest_order_revenue] Final: {paid_orders} paid orders, revenue={revenue_total:.2f} BRL, sample_count={len(sample_orders)}")

    return event


def _print_doctor_text(report: dict[str, Any]) -> None:
    status = "OK" if report["overall_ok"] else "ATTENTION"
    print(f"Laura doctor status: {status}")
    print("=" * 60)

    py = report["python"]
    print(f"Python >=3.10: {'OK' if py['ok'] else 'FAIL'} (version={py['version']})")

    envf = report["env_file"]
    if envf["exists"]:
        secure_txt = "OK" if envf.get("secure_mode") else "WARN"
        print(
            "Env file: OK "
            f"(path={envf['path']}, mode={envf.get('mode')}, secure={secure_txt})"
        )
    else:
        print(f"Env file: FAIL (missing {envf['path']})")

    sc = report["shopee_config"]
    if sc["ok"]:
        print("Shopee config: OK")
    else:
        print(f"Shopee config: FAIL ({sc.get('error')})")

    print(
        "Default tokens: "
        f"shop_id={'yes' if sc['default_shop_id_present'] else 'no'}, "
        f"access={'yes' if sc['default_access_token_present'] else 'no'}, "
        f"refresh={'yes' if sc['default_refresh_token_present'] else 'no'}"
    )

    llm = report["llm_local"]
    print(
        "Ollama reachable: "
        f"{'OK' if llm['ollama_reachable'] else 'FAIL'}"
    )
    print(f"LLM models supported: {', '.join(llm['models_supported'])}")

    latest = llm.get("latest_result", {})
    if latest.get("exists") and latest.get("read_ok"):
        fallback_txt = (
            "YES" if latest.get("fallback_detected") else "NO"
        )
        age_txt = latest.get("age_min")
        age_txt = age_txt if age_txt is not None else "unknown"
        print(
            "LLM latest: "
            f"model={latest.get('model') or 'unknown'}, "
            f"fallback={fallback_txt}, age_min={age_txt}"
        )
    elif latest.get("exists") and not latest.get("read_ok"):
        print(f"LLM latest: WARN (invalid JSON: {latest.get('error')})")
    else:
        print(f"LLM latest: WARN (missing {latest.get('path')})")

    baseline = llm.get("baseline_latest", {})
    if baseline.get("exists") and baseline.get("read_ok"):
        print(
            "LLM baseline: "
            f"posture={baseline.get('posture') or 'unknown'}, "
            f"fallback_rate_pct={baseline.get('fallback_rate_pct')}, "
            f"total_runs={baseline.get('total_runs')}, "
            f"p95_ms={baseline.get('p95_ms')}"
        )
    elif baseline.get("exists") and not baseline.get("read_ok"):
        print(f"LLM baseline: WARN (invalid JSON: {baseline.get('error')})")
    else:
        print(f"LLM baseline: WARN (missing {baseline.get('path')})")


def _ensure_no_api_error(parser: argparse.ArgumentParser, data: dict[str, Any], context: str) -> None:
    raw_error = data.get("error", "")
    error_code = "" if raw_error is None else str(raw_error).strip()
    if error_code.lower() == "none":
        error_code = ""
    if not error_code:
        return
    message = str(data.get("message", "")).strip()
    request_id = str(data.get("request_id", "")).strip()
    details = f"error={error_code}"
    if message:
        details += f", message={message}"
    if request_id:
        details += f", request_id={request_id}"
    parser.error(f"{context} failed: {details}")


def _is_auth_failure_response(resp: Any) -> bool:
    if resp is None:
        return False

    status_code = getattr(resp, "status_code", None)
    if status_code in {401, 403}:
        return True

    data = getattr(resp, "data", {})
    if not isinstance(data, dict):
        return False

    markers = (
        str(data.get("error", "")),
        str(data.get("message", "")),
        str(data.get("msg", "")),
    )
    blob = " ".join(markers).strip().lower()
    return any(
        marker in blob
        for marker in (
            "invalid_access_token",
            "invalid_acceess_token",
            "unauthorized",
            "expired",
            "access token",
            "please have a check",
        )
    )


def _refresh_default_access_token(client: ShopeeClient, cfg: Any, env_path: Path = Path(".env")) -> str | None:
    if not cfg.default_refresh_token or cfg.default_shop_id is None:
        return cfg.default_access_token

    refresh_resp = client.refresh_token(
        refresh_token=cfg.default_refresh_token,
        shop_id=cfg.default_shop_id,
    )
    refresh_data = refresh_resp.data if isinstance(refresh_resp.data, dict) else {}
    if _is_auth_failure_response(refresh_resp):
        return cfg.default_access_token

    new_access_token = str(refresh_data.get("access_token", "")).strip()
    new_refresh_token = str(refresh_data.get("refresh_token", "")).strip()
    if new_access_token and new_refresh_token:
        try:
            _upsert_env_values(
                env_path,
                {
                    "SHOPEE_DEFAULT_ACCESS_TOKEN": new_access_token,
                    "SHOPEE_DEFAULT_REFRESH_TOKEN": new_refresh_token,
                },
            )
        except Exception:
            pass
        return new_access_token

    return cfg.default_access_token


def _upsert_env_values(env_path: Path, updates: dict[str, str]) -> None:
    if not env_path.exists():
        raise FileNotFoundError(f"Arquivo de ambiente nao encontrado: {env_path}")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        replaced = False
        for key, value in updates.items():
            prefix = f"{key}="
            if line.startswith(prefix):
                new_lines.append(f"{key}={value}")
                seen.add(key)
                replaced = True
                break
        if not replaced:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    final_text = "\n".join(new_lines) + "\n"
    backup_path = env_path.with_suffix(env_path.suffix + ".bak")
    temp_path = env_path.with_suffix(env_path.suffix + ".tmp")

    # Keep a last-known-good backup before replacing the environment file.
    backup_path.write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
    temp_path.write_text(final_text, encoding="utf-8")
    temp_path.replace(env_path)


def _dispatch_db(args, client=None, cfg=None):
    from shopee_agent.schema_migrations import (
        handle_db_list,
        handle_db_migrate,
        handle_db_rollback,
        handle_db_version,
    )

    if args.db_action == "version":
        handle_db_version(args)
    elif args.db_action == "migrate":
        handle_db_migrate(args)
    elif args.db_action == "rollback":
        handle_db_rollback(args)
    elif args.db_action == "list":
        handle_db_list(args)
    return 0


def _dispatch_audit(args, client=None, cfg=None):
    from shopee_agent.security_audit import handle_audit as _handle_audit

    _handle_audit(args)
    return 0


def _dispatch_backup(args, client=None, cfg=None):
    from shopee_agent.backup import handle_backup as _handle_backup

    _handle_backup(args)
    return 0


def _dispatch_guardian(args, client=None, cfg=None):
    from shopee_agent.daemon_guardian import handle_guardian as _handle_guardian

    return _handle_guardian(args)


def _dispatch_api_usage(args, client=None, cfg=None):
    from shopee_agent.api_usage_tracker import check_usage as _check_api_usage
    from shopee_agent.api_usage_tracker import get_api_tracker as _get_api_tracker

    if getattr(args, "reset_alerts", False):
        _get_api_tracker().reset_alerts()
        print("Alertas de limite de API resetados")
        return 0
    if getattr(args, "check", False):
        _print_json(_check_api_usage())
        return 0
    tracker = _get_api_tracker()
    counts = tracker.today_counts()
    _print_json({
        "date": datetime.now().date().isoformat(),
        "total": counts["total"],
        "errors": counts["errors"],
        "daily_limit": tracker.daily_limit,
        "usage_pct": round(tracker.usage_pct(), 4),
        "by_endpoint": counts["by_endpoint"],
    })
    return 0


def _get_extracted_dispatch() -> dict[str, Any]:
    from shopee_agent.cli_commands.auth_shop_cmd import run as run_auth_shop
    from shopee_agent.cli_commands.cache_cmd import run as run_cache
    from shopee_agent.cli_commands.chat_cmd import run as run_chat
    from shopee_agent.cli_commands.email_cmd import run as run_email
    from shopee_agent.cli_commands.monitor_cmd import run as run_monitor
    from shopee_agent.cli_commands.order_cmd import run as run_order
    from shopee_agent.cli_commands.product_cmd import run as run_product
    from shopee_agent.cli_commands.report_cmd import run as run_report
    from shopee_agent.cli_commands.seller_cmd import run as run_seller
    from shopee_agent.cli_commands.watchdog_cmd import run as run_watchdog
    from shopee_agent.plugin_marketplace import handle_plugin_command
    from shopee_agent.setup_wizard import handle_setup

    return {
        "db": _dispatch_db,
        "audit": _dispatch_audit,
        "backup": _dispatch_backup,
        "guardian": _dispatch_guardian,
        "api-usage": _dispatch_api_usage,
        "plugin": handle_plugin_command,
        "alerts": run_monitor,
        "approve-remediation": run_order,
        "auth-url": run_auth_shop,
        "auto-login": run_auth_shop,
        "cache": run_cache,
        "chat-send": run_chat,
        "commercial-control-center": run_report,
        "email": run_email,
        "ingest-order-revenue": run_order,
        "inventory-monitor": run_monitor,
        "learning-summary": run_cache,
        "memory-reindex-vectors": run_cache,
        "memory-semantic-search": run_cache,
        "orders-notify-poll": run_monitor,
        "order-ship": run_order,
        "perf-benchmark": run_monitor,
        "product-batch-update": run_product,
        "product-cost-import": run_product,
        "product-cost-set": run_product,
        "product-item-base-info": run_product,
        "product-item-detail": run_product,
        "product-item-variations": run_product,
        "product-list": run_product,
        "product-margin-remediate": run_product,
        "product-margin-review": run_product,
        "product-set-price": run_product,
        "product-set-stock": run_product,
        "ratings-backfill": run_monitor,
        "report-generate": run_report,
        "report-sales": run_report,
        "seller-center-browser": run_seller,
        "seller-center-import": run_seller,
        "seller-center-status": run_seller,
        "self-healing-summary": run_cache,
        "shop-info": run_auth_shop,
        "shop-info-default": run_auth_shop,
        "store-analysis": run_monitor,
        "store-health-report": run_monitor,
        "strategy-summary": run_cache,
        "support-summary": run_chat,
        "support-triage": run_chat,
        "telegram-bot": run_chat,
        "telegram-setup": run_chat,
        "telegram-setup-token": run_chat,
        "token-get": run_auth_shop,
        "token-refresh": run_auth_shop,
        "token-refresh-save": run_auth_shop,
        "visual-analysis": run_monitor,
        "watchdog": run_watchdog,
        "setup": handle_setup,
    }


def _get_all_handlers() -> dict[str, Any]:
    from shopee_agent.cli_commands.all_handlers import HANDLER_DISPATCH

    return HANDLER_DISPATCH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laura",
        description="Laura: agente local para automacao da Shopee Open API",
    )
    sub = parser.add_subparsers(dest="command", required=True)













    autonomous = sub.add_parser(
        "autonomous-loop",
        help="Executa um ciclo do loop autonomo (coleta, analisa, notifica)",
    )
    autonomous.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    autonomous.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    autonomous.add_argument("--telegram-token", default=None, help="Telegram bot token opcional para notificacoes")
    autonomous.add_argument("--telegram-chat-id", default=None, help="Telegram chat id opcional para notificacoes")




















    dashboard_parser = sub.add_parser(
        "dashboard",
        help="Dashboard web FastAPI com status da loja",
    )
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="Host do servidor (default: 127.0.0.1)")
    dashboard_parser.add_argument("--port", type=int, default=8888, help="Porta (default: 8888)")
    dashboard_parser.add_argument("--build-frontend", action="store_true", help="Executa npm run build no frontend antes de iniciar")
    dashboard_parser.add_argument("--no-auto-build", action="store_true", help="Desativa auto-build do frontend (usar em producao)")

    skill_run_parser = sub.add_parser(
        "skill-run",
        help="Invoca uma skill registrada pelo nome",
    )
    skill_run_parser.add_argument("name", help="Nome da skill (ex: pricing_skill)")
    skill_run_parser.add_argument("--params", default="{}", help="JSON com parametros para a skill")
    skill_run_parser.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    skill_run_parser.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")

    sub.add_parser(
        "skill-list",
        help="Lista skills registradas no default_registry",
    )

    skill_register_parser = sub.add_parser(
        "skill-register",
        help="Registra manualmente uma skill por nome de classe",
    )
    skill_register_parser.add_argument("name", help="Nome da classe da skill (ex: LowStockAlertSkill)")
    skill_register_parser.add_argument("--module", default="", help="Modulo Python completo (ex: shopee_agent.skills.inventory_skill)")
    skill_register_parser.add_argument("--path", default="", help="Caminho de arquivo .py para carregar skill externa")

    trace_parser = sub.add_parser(
        "trace",
        help="Visualiza spans de tracing distribuido",
    )
    trace_parser.add_argument("--follow", action="store_true", help="Acompanha spans em tempo real (tail do event bus)")
    trace_parser.add_argument("--limit", type=int, default=20, help="Numero de spans a exibir (padrao 20)")

    skill_goap_plan_parser = sub.add_parser(
        "skill-goap-plan",
        help="Testa GOAP manualmente, exibindo o plano encontrado",
    )
    skill_goap_plan_parser.add_argument("--current-state", default='{}', help="JSON com estado atual")
    skill_goap_plan_parser.add_argument("--goal-state", default='{"stock_checked":true,"margin_protected":true}', help="JSON com estado desejado")
    skill_goap_plan_parser.add_argument("--max-depth", type=int, default=6, help="Profundidade maxima da busca A*")

    skill_history_parser = sub.add_parser(
        "skill-history",
        help="Exibe historico de execucao de skills e custos aprendidos pelo GOAP",
    )
    skill_history_parser.add_argument("--limit", type=int, default=20, help="Numero de entradas a exibir")
    skill_history_parser.add_argument("--learning", action="store_true", help="Mostrar apenas custos aprendidos")

    skill_test_parser = sub.add_parser(
        "skill-test",
        help="Testa uma skill em modo sandbox com asserts sobre effects",
    )
    skill_test_parser.add_argument("name", help="Nome da skill (ex: pricing_skill)")
    skill_test_parser.add_argument("--params", default='{}', help="JSON com parametros de entrada")
    skill_test_parser.add_argument("--assert-effects", default='{}', help="JSON com effects esperados apos execucao")
    skill_test_parser.add_argument("--dry-run", action="store_true", help="Simular sem executar de fato")

    goal_synthesize_parser = sub.add_parser(
        "goal-synthesize",
        help="Infere goal_state GOAP a partir de KPIs do negocio",
    )
    goal_synthesize_parser.add_argument("--margin-pct", type=float, default=25.0, help="Margem atual em percentual")
    goal_synthesize_parser.add_argument("--low-margin", type=int, default=0, help="Quantidade de itens com margem baixa")
    goal_synthesize_parser.add_argument("--low-stock", type=int, default=0, help="Quantidade de itens com estoque baixo")
    goal_synthesize_parser.add_argument("--refund-pct", type=float, default=0.0, help="Taxa de reembolso percentual")

    goal_nl_parser = sub.add_parser(
        "goal-nl",
        help="Traduz linguagem natural para goal_state GOAP",
    )
    goal_nl_parser.add_argument("text", help="Frase em portugues (ex: 'aumentar margem')")
    goal_nl_parser.add_argument("--llm", action="store_true", help="Usar LLM para interpretacao (padrao: keywords)")

    skill_approve_parser = sub.add_parser(
        "skill-approve",
        help="Aprova execucao de skill de alto risco pendente",
    )
    skill_approve_parser.add_argument("request_id", help="ID da requisicao de aprovacao")

    skill_reject_parser = sub.add_parser(
        "skill-reject",
        help="Rejeita execucao de skill de alto risco pendente",
    )
    skill_reject_parser.add_argument("request_id", help="ID da requisicao de aprovacao")

    skill_approval_list_parser = sub.add_parser(
        "skill-approval-list",
        help="Lista requisicoes de aprovacao pendentes",
    )
    skill_approval_list_parser.add_argument("--all", action="store_true", help="Mostrar todas (nao so pendentes)")

    sub.add_parser(
        "store-list",
        help="Lista lojas/tenants registradas",
    )

    store_init_parser = sub.add_parser(
        "store-init",
        help="Inicializa contexto isolado para uma loja",
    )
    store_init_parser.add_argument("store_id", help="ID da loja (ex: shop_123)")

    store_summary_parser = sub.add_parser(
        "store-summary",
        help="Exibe resumo de uma loja",
    )
    store_summary_parser.add_argument("store_id", help="ID da loja")

    # ── Multi-tenant management ───────────────────────────────────────────
    tenant_parser = sub.add_parser("tenant", help="Gerenciamento multi-tenant")
    tenant_sub = tenant_parser.add_subparsers(dest="tenant_action", required=True)
    tenant_sub.add_parser("list", help="Lista tenants registrados")
    tenant_register = tenant_sub.add_parser("register", help="Registra novo tenant")
    tenant_register.add_argument("store_id", help="ID da loja (ex: shop_123)")
    tenant_register.add_argument("--shop-id", type=int, required=True, help="Shop ID")
    tenant_register.add_argument("--access-token", default="", help="Access token")
    tenant_register.add_argument("--enabled", action="store_true", default=True, help="Habilitar na criacao")
    tenant_remove = tenant_sub.add_parser("remove", help="Remove tenant")
    tenant_remove.add_argument("store_id", help="ID da loja")
    tenant_enable = tenant_sub.add_parser("enable", help="Habilita tenant")
    tenant_enable.add_argument("store_id", help="ID da loja")
    tenant_disable = tenant_sub.add_parser("disable", help="Desabilita tenant")
    tenant_disable.add_argument("store_id", help="ID da loja")

    benchmark_parser = sub.add_parser(
        "benchmark",
        help="Executa benchmarks de performance (GOAP + skills)",
    )
    benchmark_parser.add_argument("--iterations", type=int, default=10, help="Numero de iteracoes do benchmark")
    benchmark_parser.add_argument("--skills", default="", help="Lista de skills para benchmark separada por virgula")

    skill_generate_parser = sub.add_parser(
        "skill-generate",
        help="Gera uma nova Skill a partir de descricao em linguagem natural",
    )
    skill_generate_parser.add_argument("description", help="Descricao da skill (ex: 'monitorar preco de concorrente')")
    skill_generate_parser.add_argument("--preconditions", default="{}", help="JSON com preconditions")
    skill_generate_parser.add_argument("--effects", default="{}", help="JSON com effects")
    skill_generate_parser.add_argument("--risk", default="LOW", choices=["LOW", "MEDIUM", "HIGH"], help="Nivel de risco")
    skill_generate_parser.add_argument("--cost", type=float, default=1.0, help="Custo GOAP")
    skill_generate_parser.add_argument("--priority", type=int, default=0, help="Prioridade GOAP")
    skill_generate_parser.add_argument("--schedule", default="", help="Agendamento HH:MM")
    skill_generate_parser.add_argument("--event-types", default="", help="Event types separados por virgula")

    skill_goap_explain_parser = sub.add_parser(
        "skill-goap-explain",
        help="Explica por que cada acao foi escolhida no plano GOAP",
    )
    skill_goap_explain_parser.add_argument("--current-state", default='{}', help="JSON com estado atual")
    skill_goap_explain_parser.add_argument("--goal-state", default='{"margin_protected":true}', help="JSON com estado desejado")
    skill_goap_explain_parser.add_argument("--max-depth", type=int, default=6, help="Profundidade maxima")

    skill_rollback_learning_parser = sub.add_parser(
        "skill-rollback-learning",
        help="Rollback do aprendizado de custo de uma skill",
    )
    skill_rollback_learning_parser.add_argument("skill_name", help="Nome da skill")
    skill_rollback_learning_parser.add_argument("--steps", type=int, default=1, help="Quantos passos rollback")

    learning_stats_parser = sub.add_parser(
        "learning-stats",
        help="Estatisticas detalhadas de aprendizado de uma skill (SQLite)",
    )
    learning_stats_parser.add_argument("skill_name", help="Nome da skill")

    ab_test_parser = sub.add_parser(
        "ab-test-start",
        help="Inicia um teste A/B entre duas versoes de skill",
    )
    ab_test_parser.add_argument("skill_name", help="Nome base da skill")
    ab_test_parser.add_argument("control_module", help="Modulo Python da versao controle (ex: shopee_agent.skills.pricing_skill)")
    ab_test_parser.add_argument("control_class", help="Nome da classe controle")
    ab_test_parser.add_argument("variant_module", help="Modulo Python da versao variante")
    ab_test_parser.add_argument("variant_class", help="Nome da classe variante")
    ab_test_parser.add_argument("--split", type=float, default=0.5, help="Fracao de trafego para variante (0-1)")

    sub.add_parser(
        "ab-test-status",
        help="Status dos testes A/B ativos",
    )

    canary_start_parser = sub.add_parser(
        "canary-start",
        help="Inicia canary deploy de uma nova versao de skill",
    )
    canary_start_parser.add_argument("skill_name", help="Nome base da skill")
    canary_start_parser.add_argument("new_module", help="Modulo Python da nova versao")
    canary_start_parser.add_argument("new_class", help="Nome da classe da nova versao")
    canary_start_parser.add_argument("--initial-pct", type=float, default=10.0, help="Percentual inicial de trafego (0-100)")
    canary_start_parser.add_argument("--max-error", type=float, default=5.0, help="Taxa de erro maxima percentual")

    sub.add_parser(
        "canary-status",
        help="Status dos canary deploys ativos",
    )

    canary_promote_parser = sub.add_parser(
        "canary-promote",
        help="Promove manualmente um canary para 100%%",
    )
    canary_promote_parser.add_argument("canary_id", help="ID do canary")

    canary_rollback_parser = sub.add_parser(
        "canary-rollback",
        help="Rollback manual de um canary para 0%%",
    )
    canary_rollback_parser.add_argument("canary_id", help="ID do canary")

    sub.add_parser(
        "sandbox-test",
        help="Testa conectividade com sandbox Shopee",
    )

    # ── New feature commands ────────────────────────────────────────────────

    plan_viz_parser = sub.add_parser(
        "plan-viz",
        help="Exporta plano como diagrama Mermaid",
    )
    plan_viz_parser.add_argument("--plan-id", type=int, default=None, help="ID do plano no PlanStore")
    plan_viz_parser.add_argument("--current-state", default='{}', help="JSON estado atual")
    plan_viz_parser.add_argument("--goal-state", default='{"margin_protected":true}', help="JSON estado desejado")
    plan_viz_parser.add_argument("--max-depth", type=int, default=6, help="Profundidade")
    plan_viz_parser.add_argument("--format", choices=["flowchart", "gantt"], default="flowchart", help="Formato do diagrama")
    plan_viz_parser.add_argument("--output", default="", help="Salvar em arquivo (opcional)")

    plan_diff_parser = sub.add_parser(
        "plan-diff",
        help="Compara dois planos lado a lado",
    )
    plan_diff_parser.add_argument("plan_a_id", type=int, help="ID do primeiro plano")
    plan_diff_parser.add_argument("plan_b_id", type=int, help="ID do segundo plano")

    plan_export_parser = sub.add_parser(
        "plan-export",
        help="Exporta um plano como JSON portavel",
    )
    plan_export_parser.add_argument("plan_id", type=int, help="ID do plano")
    plan_export_parser.add_argument("--output", default="", help="Arquivo de saida")

    plan_import_parser = sub.add_parser(
        "plan-import",
        help="Importa um plano de JSON portavel",
    )
    plan_import_parser.add_argument("input_file", help="Arquivo JSON")
    plan_import_parser.add_argument("--store-id", default="", help="Store ID (opcional)")

    plan_batch_parser = sub.add_parser(
        "plan-batch",
        help="Executa multiplos planos a partir de um arquivo JSON",
    )
    plan_batch_parser.add_argument("input_file", help="Arquivo JSON com array de planos")
    plan_batch_parser.add_argument("--dry-run", action="store_true", default=False, help="Apenas simular")

    goal_library_parser = sub.add_parser(
        "goal-library",
        help="Gerencia biblioteca de metas pre-construidas",
    )
    goal_library_parser.add_argument("action", choices=["list", "search", "get", "add"], help="Acao")
    goal_library_parser.add_argument("--query", default="", help="Busca por termo (para search)")
    goal_library_parser.add_argument("--goal-id", default="", help="ID da meta (para get)")
    goal_library_parser.add_argument("--tag", default="", help="Filtrar por tag (para list)")
    goal_library_parser.add_argument("--title", default="", help="Titulo (para add)")
    goal_library_parser.add_argument("--description", default="", help="Descricao (para add)")
    goal_library_parser.add_argument("--goal-state", default="{}", help="JSON goal state (para add)")
    goal_library_parser.add_argument("--priority", type=int, default=5, help="Prioridade (para add)")

    plan_schedule_parser = sub.add_parser(
        "plan-schedule",
        help="Gerencia execucao agendada de planos",
    )
    plan_schedule_parser.add_argument("action", choices=["list", "add", "remove"], help="Acao")
    plan_schedule_parser.add_argument("--plan-id", default="", help="ID do plano (para add/remove)")
    plan_schedule_parser.add_argument("--schedule", default="08:00", help="Horario HH:MM (para add)")
    plan_schedule_parser.add_argument("--goal-state", default="{}", help="JSON goal state (para add)")
    plan_schedule_parser.add_argument("--description", default="", help="Descricao (para add)")

    plan_optimize_parser = sub.add_parser(
        "plan-optimize",
        help="Analisa dados de aprendizado e sugere otimizacoes",
    )
    plan_optimize_parser.add_argument("--compare", action="store_true", default=False, help="Comparar custos de planos alternativos")
    plan_optimize_parser.add_argument("--current-state", default="{}", help="JSON estado atual (para compare)")
    plan_optimize_parser.add_argument("--goal-state", default='{"margin_protected":true}', help="JSON goal (para compare)")

    skill_anomaly_parser = sub.add_parser(
        "skill-anomaly",
        help="Detecta anomalias na execucao de skills (tempo, taxa de sucesso)",
    )
    skill_anomaly_parser.add_argument("action", choices=["check", "summary"], help="Acao")

    skill_version_parser = sub.add_parser(
        "skill-version",
        help="Gerencia historico de versoes de skills",
    )
    skill_version_parser.add_argument("action", choices=["list", "history", "rollback"], help="Acao")
    skill_version_parser.add_argument("--skill-name", default="", help="Nome da skill")
    skill_version_parser.add_argument("--target-version", default="", help="Versao alvo para rollback")

    plan_template_parser = sub.add_parser(
        "plan-template",
        help="Gerencia templates reutilizaveis de planos",
    )
    plan_template_parser.add_argument("action", choices=["list", "get", "render"], help="Acao")
    plan_template_parser.add_argument("--template-id", default="", help="ID do template")
    plan_template_parser.add_argument("--params", default="{}", help="JSON com parametros para render")

    multi_approve_parser = sub.add_parser(
        "multi-approve",
        help="Workflow de aprovacao com multiplos aprovadores",
    )
    multi_approve_parser.add_argument("action", choices=["create", "approve", "reject", "status"], help="Acao")
    multi_approve_parser.add_argument("--skill-name", default="", help="Nome da skill")
    multi_approve_parser.add_argument("--steps", default="", help="Aprovadores separados por virgula")
    multi_approve_parser.add_argument("--approver", default="", help="Nome do aprovador")

    plan_heal_parser = sub.add_parser(
        "plan-heal",
        help="Executa plano com auto-repair em caso de falha",
    )
    plan_heal_parser.add_argument("--current-state", default='{}', help="JSON estado atual")
    plan_heal_parser.add_argument("--goal-state", default='{"margin_protected":true}', help="JSON goal")
    plan_heal_parser.add_argument("--max-repairs", type=int, default=3, help="Maximo de tentativas de reparo")
    plan_heal_parser.add_argument("--dry-run", action="store_true", default=False, help="Apenas simular")

    plan_explain_nl_parser = sub.add_parser(
        "plan-explain",
        help="Explica plano em linguagem natural (portugues)",
    )
    plan_explain_nl_parser.add_argument("--current-state", default='{}', help="JSON estado atual")
    plan_explain_nl_parser.add_argument("--goal-state", default='{"margin_protected":true}', help="JSON goal")
    plan_explain_nl_parser.add_argument("--llm", action="store_true", default=False, help="Usar LLM para explicacao")
    plan_explain_nl_parser.add_argument("--output", default="", help="Salvar em arquivo")

    proactive_goals_parser = sub.add_parser(
        "proactive-goals",
        help="Sugere metas proativamente baseado em metricas da loja",
    )
    proactive_goals_parser.add_argument("--metrics", default='{}', help="JSON com metricas da loja")

    cost_predict_parser = sub.add_parser(
        "cost-predict",
        help="Preve custo de um plano baseado em historico de aprendizado",
    )
    cost_predict_parser.add_argument("actions", nargs="+", help="Nomes das skills no plano")
    cost_predict_parser.add_argument("--current-state", default='{}', help="JSON estado atual (opcional)")
    cost_predict_parser.add_argument("--goal-state", default='{"margin_protected":true}', help="JSON goal (opcional)")

    skill_market_parser = sub.add_parser(
        "skill-market",
        help="Gerencia marketplace de skills (export/import)",
    )
    skill_market_parser.add_argument("action", choices=["export", "import", "list"], help="Acao")
    skill_market_parser.add_argument("--skill-name", default="", help="Nome da skill (para export)")
    skill_market_parser.add_argument("--input", default="", help="Arquivo de entrada (para import)")
    skill_market_parser.add_argument("--output", default="", help="Arquivo de saida (para export)")

    federated_parser = sub.add_parser(
        "federated",
        help="Gerencia aprendizado federado entre lojas",
    )
    federated_parser.add_argument("action", choices=["report", "aggregate", "stores"], help="Acao")
    federated_parser.add_argument("--store-id", default="", help="ID da loja (para report)")
    federated_parser.add_argument("--data", default="{}", help="JSON com learning summary (para report)")

    plan_conform_parser = sub.add_parser(
        "plan-conform",
        help="Verifica conformidade entre plano executado e resultados reais",
    )
    plan_conform_parser.add_argument("--expected-actions", default="[]", help="JSON com lista de actions esperadas")
    plan_conform_parser.add_argument("--expected-effects", default='{"margin_protected":true}', help="JSON com effects esperados")
    plan_conform_parser.add_argument("--actual-state", default='{}', help="JSON com estado real apos execucao")

    skill_create_parser = sub.add_parser(
        "skill-create",
        help="Cria scaffolding de uma nova skill interativamente",
    )
    skill_create_parser.add_argument("name", help="Nome da skill (ex: monitor_preco)")
    skill_create_parser.add_argument("--risk", choices=["LOW", "MEDIUM", "HIGH"], default="LOW")
    skill_create_parser.add_argument("--cost", type=float, default=1.0)
    skill_create_parser.add_argument("--priority", type=int, default=0)
    skill_create_parser.add_argument("--preconditions", default="{}", help='JSON (ex: {"preco_verificado":false})')
    skill_create_parser.add_argument("--effects", default='{"concorrente_verificado":true}', help="JSON effects")
    skill_create_parser.add_argument("--output-dir", default="shopee_agent/skills", help="Diretorio de saida")
    skill_create_parser.add_argument("--register", action="store_true", default=True, help="Registrar automaticamente")

    skill_simulate_parser = sub.add_parser(
        "skill-simulate",
        help="What-if simulation: mostra qual plano seria executado sem rodar",
    )
    skill_simulate_parser.add_argument("--current-state", default='{}', help="JSON com estado atual")
    skill_simulate_parser.add_argument("--goal-state", default='{"margin_protected":true}', help="JSON com estado desejado")
    skill_simulate_parser.add_argument("--max-depth", type=int, default=6, help="Profundidade maxima")
    skill_simulate_parser.add_argument("--max-budget", type=float, default=None, help="Orcamento maximo")

    skill_reload_parser = sub.add_parser(
        "skill-reload",
        help="Hot-reload de skills (reimporta modulo e atualiza classe)",
    )
    skill_reload_parser.add_argument("skill_name", nargs="?", default=None, help="Nome da skill (vazio = todas)")

    sub.add_parser(
        "skill-profile",
        help="Exibe profile de recursos por skill (tempo, execucoes)",
    )

    plan_store_parser = sub.add_parser(
        "plan-store",
        help="Gerencia planos persistidos: list, get, stats",
    )
    plan_store_parser.add_argument("action", choices=["list", "get", "stats"], help="Acao")
    plan_store_parser.add_argument("--plan-id", type=int, default=None, help="ID do plano (para get)")
    plan_store_parser.add_argument("--limit", type=int, default=20, help="Limite de planos (para list)")

    planner_alerts_parser = sub.add_parser(
        "planner-alerts",
        help="Gerencia alertas do planner: check, history",
    )
    planner_alerts_parser.add_argument("action", choices=["check", "history"], help="Acao")

    sub.add_parser(
        "start",
        help="Inicia a Laura — carrega skills, GOAP planner e daemon",
    )

    sub.add_parser(
        "daemon",
        help="Inicia o daemon principal da Laura em loop contínuo",
    )

    shell_parser = sub.add_parser(
        "shell",
        help="CLI shell interativa com auto-complete para explorar acoes",
    )
    shell_parser.add_argument(
        "command", nargs="?", default=None,
        help="Comando opcional para executar sem entrar no shell interativo",
    )






    # Seller Center commands












    # Competitor Commands
    competitors_cmd = sub.add_parser("competitors", help="Monitor and analyze competitor products")
    competitors_sub = competitors_cmd.add_subparsers(dest="competitors_action", required=True)
    comp_search = competitors_sub.add_parser("search", help="Search competitors by keyword")
    comp_search.add_argument("keyword", help="Search keyword")
    comp_track = competitors_sub.add_parser("track", help="Start tracking a competitor product")
    comp_track.add_argument("item_id", help="Competitor item ID")
    comp_track.add_argument("--name", default="", help="Product name")
    comp_track.add_argument("--price", type=float, default=0.0, help="Current price")
    competitors_sub.add_parser("list", help="List tracked competitors")
    comp_compare = competitors_sub.add_parser("compare", help="Compare your product with a competitor")
    comp_compare.add_argument("item_id", help="Your product item ID")
    comp_compare.add_argument("--competitor-id", default="", help="Competitor item ID (optional)")
    competitors_sub.add_parser("report", help="Generate competitive analysis report")

    # Pricing Commands
    pricing_cmd = sub.add_parser("pricing", help="Dynamic pricing: analyze and apply price suggestions")
    pricing_sub = pricing_cmd.add_subparsers(dest="pricing_action", required=True)
    pricing_sub.add_parser("analyze", help="Analyze all items for pricing opportunities")
    pricing_apply = pricing_sub.add_parser("apply", help="Apply price suggestions (use --no-dry-run to actually apply)")
    pricing_apply.add_argument("--dry-run", action="store_true", default=True, help="Simulate without applying (default: true)")
    pricing_apply.add_argument("--no-dry-run", action="store_false", dest="dry_run", help="Actually apply prices")

    # Refund Management Commands
    refunds_cmd = sub.add_parser(
        "refunds",
        help="Manage refunds: view pending, approve/reject, view stats",
    )
    refunds_subcommand = refunds_cmd.add_subparsers(dest="refunds_action", required=False)

    refunds_list = refunds_subcommand.add_parser("list", help="List pending refunds")
    refunds_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    refunds_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    refunds_list.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    refunds_list.add_argument("--status", choices=["pending", "approved", "rejected", "completed"], help="Filter by status")

    refunds_stats = refunds_subcommand.add_parser("stats", help="Show refund statistics")
    refunds_stats.add_argument("--days", type=int, default=30, help="Days window (default: 30)")

    refunds_approve = refunds_subcommand.add_parser("approve", help="Approve a refund")
    refunds_approve.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    refunds_approve.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    refunds_approve.add_argument("--return-sn", required=True, help="Return SN to approve")
    refunds_approve.add_argument("--dry-run", action="store_true", help="Show action without executing")

    refunds_reject = refunds_subcommand.add_parser("reject", help="Reject a refund")
    refunds_reject.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    refunds_reject.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    refunds_reject.add_argument("--return-sn", required=True, help="Return SN to reject")
    refunds_reject.add_argument("--dry-run", action="store_true", help="Show action without executing")

    refunds_auto = refunds_subcommand.add_parser("auto-evaluate", help="Auto-evaluate all pending refunds")
    refunds_auto.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    refunds_auto.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    refunds_auto.add_argument("--days", type=int, default=7, help="Days window for pending refunds")
    refunds_auto.add_argument("--dry-run", action="store_true", help="Show recommendations without executing")

    order_list = sub.add_parser(
        "order-list",
        help="Lista pedidos da loja (wrapper para /api/v2/order/get_order_list)",
    )
    order_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    order_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    order_list.add_argument(
        "--time-range-field",
        default="create_time",
        choices=["create_time", "update_time"],
        help="Campo de tempo usado para filtro",
    )
    order_list.add_argument(
        "--time-from",
        type=int,
        default=None,
        help="Inicio da janela em epoch seconds (default: agora-24h)",
    )
    order_list.add_argument(
        "--time-to",
        type=int,
        default=None,
        help="Fim da janela em epoch seconds (default: agora)",
    )
    order_list.add_argument("--page-size", type=int, default=20, help="Tamanho da pagina")
    order_list.add_argument("--cursor", default="", help="Cursor de paginacao")
    order_list.add_argument(
        "--order-status",
        default="",
        help="Filtro opcional de status do pedido",
    )

    order_detail = sub.add_parser(
        "order-detail",
        help="Detalhe de um pedido (wrapper para /api/v2/order/get_order_detail)",
    )
    order_detail.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    order_detail.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    order_detail.add_argument("--order-sn", required=True, help="Order SN do pedido")

    logistics_channel_list = sub.add_parser(
        "logistics-channel-list",
        help="Lista canais logísticos (wrapper para /api/v2/logistics/get_channel_list)",
    )
    logistics_channel_list.add_argument(
        "--access-token",
        default=None,
        help="Access token; default do .env se omitido",
    )
    logistics_channel_list.add_argument(
        "--shop-id",
        type=int,
        default=None,
        help="Shop ID; default do .env se omitido",
    )

    logistics_info = sub.add_parser(
        "logistics-info",
        help="Informacoes logisticas de um pedido (wrapper para /api/v2/logistics/get_logistics_info)",
    )
    logistics_info.add_argument(
        "--access-token",
        default=None,
        help="Access token; default do .env se omitido",
    )
    logistics_info.add_argument(
        "--shop-id",
        type=int,
        default=None,
        help="Shop ID; default do .env se omitido",
    )
    logistics_info.add_argument(
        "--order-sn",
        required=True,
        help="Order SN do pedido",
    )
    logistics_info.add_argument(
        "--package-number",
        default="",
        help="Package number opcional para pedidos com multi-pacote",
    )

    logistics_tracking_number = sub.add_parser(
        "logistics-tracking-number",
        help="Consulta tracking number (wrapper para /api/v2/logistics/get_tracking_number)",
    )
    logistics_tracking_number.add_argument(
        "--access-token",
        default=None,
        help="Access token; default do .env se omitido",
    )
    logistics_tracking_number.add_argument(
        "--shop-id",
        type=int,
        default=None,
        help="Shop ID; default do .env se omitido",
    )
    logistics_tracking_number.add_argument(
        "--order-sn",
        required=True,
        help="Order SN do pedido",
    )
    logistics_tracking_number.add_argument(
        "--package-number",
        default="",
        help="Package number opcional para pedidos com multi-pacote",
    )

    returns_list = sub.add_parser(
        "returns-list",
        help="Lista devoluções (wrapper para /api/v2/returns/get_return_list)",
    )
    returns_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    returns_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    returns_list.add_argument("--page-no", type=int, default=1, help="Pagina de devoluções")
    returns_list.add_argument("--page-size", type=int, default=20, help="Tamanho da pagina")
    returns_list.add_argument(
        "--create-time-from",
        type=int,
        default=None,
        help="Inicio da janela em epoch seconds (default: agora-7d)",
    )
    returns_list.add_argument(
        "--create-time-to",
        type=int,
        default=None,
        help="Fim da janela em epoch seconds (default: agora)",
    )

    returns_detail = sub.add_parser(
        "returns-detail",
        help="Detalhe de devolução (wrapper para /api/v2/returns/get_return_detail)",
    )
    returns_detail.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    returns_detail.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    returns_detail.add_argument("--return-sn", required=True, help="Identificador da devolução")

    payment_escrow_detail = sub.add_parser(
        "payment-escrow-detail",
        help="Detalhe financeiro por pedido (wrapper para /api/v2/payment/get_escrow_detail)",
    )
    payment_escrow_detail.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    payment_escrow_detail.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    payment_escrow_detail.add_argument("--order-sn", required=True, help="Order SN do pedido")

    discount_list = sub.add_parser(
        "discount-list",
        help="Lista campanhas de desconto (wrapper para /api/v2/discount/get_discount_list)",
    )
    discount_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    discount_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    discount_list.add_argument(
        "--discount-status",
        default="all",
        choices=["ongoing", "upcoming", "expired", "all"],
        help="Filtro de status de desconto",
    )

    voucher_list = sub.add_parser(
        "voucher-list",
        help="Lista vouchers (wrapper para /api/v2/voucher/get_voucher_list)",
    )
    voucher_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    voucher_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    voucher_list.add_argument(
        "--status",
        default="all",
        choices=["ongoing", "upcoming", "expired", "all"],
        help="Filtro de status de voucher",
    )

    bundle_deal_list = sub.add_parser(
        "bundle-deal-list",
        help="Lista bundle deals (wrapper para /api/v2/bundle_deal/get_bundle_deal_list)",
    )
    bundle_deal_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    bundle_deal_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")

    add_on_deal_list = sub.add_parser(
        "add-on-deal-list",
        help="Lista add-on deals (wrapper para /api/v2/add_on_deal/get_add_on_deal_list)",
    )
    add_on_deal_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    add_on_deal_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")

    media_video_init_upload = sub.add_parser(
        "media-video-init-upload",
        help="Inicia upload de vídeo (wrapper para /api/v2/media_space/init_video_upload)",
    )
    media_video_init_upload.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    media_video_init_upload.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    media_video_init_upload.add_argument("--file-size", type=int, required=True, help="Tamanho do arquivo em bytes")
    media_video_init_upload.add_argument("--file-md5", required=True, help="MD5 do arquivo em hexadecimal")

    media_video_upload_result = sub.add_parser(
        "media-video-upload-result",
        help="Consulta resultado de upload de vídeo (wrapper para /api/v2/media_space/get_video_upload_result)",
    )
    media_video_upload_result.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    media_video_upload_result.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    media_video_upload_result.add_argument("--video-upload-id", required=True, help="ID retornado por media-video-init-upload")

    media_video_wait_completion = sub.add_parser(
        "media-video-wait-completion",
        help="Aguarda conclusão do upload de vídeo (pooling até status != TRANSCODING)",
    )
    media_video_wait_completion.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    media_video_wait_completion.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    media_video_wait_completion.add_argument("--video-upload-id", required=True, help="ID retornado por media-video-init-upload")
    media_video_wait_completion.add_argument("--max-wait-seconds", type=int, default=300, help="Timeout maximo de espera (default 300s)")
    media_video_wait_completion.add_argument("--poll-interval-seconds", type=int, default=5, help="Intervalo entre tentativas (default 5s)")

    media_video_upload_part = sub.add_parser(
        "media-video-upload-part",
        help="Envia uma parte do vídeo (wrapper para /api/v2/media_space/upload_video_part)",
    )
    media_video_upload_part.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    media_video_upload_part.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    media_video_upload_part.add_argument("--video-upload-id", required=True, help="ID retornado por media-video-init-upload")
    media_video_upload_part.add_argument("--part-seq", type=int, required=True, help="Sequência da parte (>=0)")
    media_video_upload_part.add_argument("--part-file", required=True, help="Arquivo binário da parte a enviar")
    media_video_upload_part.add_argument("--content-md5", default=None, help="MD5 hexadecimal da parte (opcional; auto se omitido)")

    media_video_complete_upload = sub.add_parser(
        "media-video-complete-upload",
        help="Finaliza upload de vídeo (wrapper para /api/v2/media_space/complete_video_upload)",
    )
    media_video_complete_upload.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    media_video_complete_upload.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    media_video_complete_upload.add_argument("--video-upload-id", required=True, help="ID retornado por media-video-init-upload")
    media_video_complete_upload.add_argument(
        "--part-seq-list",
        required=True,
        help="Lista de partes separadas por vírgula, ex: 1,2,3",
    )

    api_call = sub.add_parser(
        "api-call",
        help="Chama qualquer endpoint da Shopee Open API com assinatura correta",
    )
    api_call.add_argument("--path", required=True, help="Caminho do endpoint, ex: /api/v2/shop/get_shop_info")
    api_call.add_argument(
        "--method",
        default="GET",
        choices=["GET", "POST", "PUT", "DELETE"],
        help="Metodo HTTP do endpoint",
    )
    api_call.add_argument(
        "--access-token",
        default=None,
        help="Access token; se omitido, usa SHOPEE_DEFAULT_ACCESS_TOKEN quando disponivel",
    )
    api_call.add_argument(
        "--shop-id",
        type=int,
        default=None,
        help="Shop ID; se omitido, usa SHOPEE_DEFAULT_SHOP_ID quando disponivel",
    )
    api_call.add_argument(
        "--payload-file",
        default=None,
        help="Arquivo JSON com payload do request",
    )
    api_call.add_argument(
        "--query-file",
        default=None,
        help="Arquivo JSON com query params extras",
    )
    api_call.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Timeout de requisicao para esta chamada",
    )
    api_call.add_argument(
        "--output-file",
        default=None,
        help="Arquivo opcional para salvar a resposta JSON",
    )

    api_endpoints = sub.add_parser(
        "api-endpoints",
        help="Lista os endpoints Shopee catalogados pela Laura",
    )
    api_endpoints.add_argument(
        "--json",
        action="store_true",
        help="Saida em JSON",
    )

    api_families = sub.add_parser(
        "api-families",
        help="Lista as familias oficiais de APIs Shopee reconhecidas pela Laura",
    )
    api_families.add_argument(
        "--json",
        action="store_true",
        help="Saida em JSON",
    )

    health_check = sub.add_parser(
        "health-check",
        help="Faz refresh do token padrao, salva no .env e valida acesso da loja",
    )
    health_check.add_argument(
        "--local",
        action="store_true",
        help="Apenas checa serviços locais (Ollama, webhook), sem chamar API Shopee",
    )
    health_check.add_argument(
        "--env-file",
        default=".env",
        help="Caminho do arquivo .env para atualizar tokens",
    )

    webhook_start = sub.add_parser(
        "webhook-start",
        help="Inicia servidor de webhook para Set Push da Shopee",
    )
    webhook_start.add_argument(
        "--host",
        default=os.getenv("LAURA_WEBHOOK_HOST", "127.0.0.1"),
        help="Host de bind local do webhook (default: 127.0.0.1)",
    )
    webhook_start.add_argument(
        "--port",
        type=int,
        default=_int_from_env("LAURA_WEBHOOK_PORT", 8765),
        help="Porta de bind local do webhook (default: 8765)",
    )
    webhook_start.add_argument(
        "--secret-key",
        default=os.getenv("LAURA_WEBHOOK_SECRET", ""),
        help="Segredo HMAC (Live Push Partner Key) para validar assinatura",
    )
    webhook_start.add_argument(
        "--public-base-url",
        default=os.getenv("LAURA_WEBHOOK_PUBLIC_BASE_URL", ""),
        help="Base URL publica HTTPS para imprimir callback recomendado",
    )
    webhook_start.add_argument(
        "--callback-path",
        default=os.getenv("LAURA_WEBHOOK_PATH", "/webhook/shopee"),
        help="Path da callback para Set Push (default: /webhook/shopee)",
    )
    webhook_start.add_argument(
        "--allow-unverified-ack",
        action="store_true",
        default=os.getenv("LAURA_WEBHOOK_ALLOW_UNVERIFIED_ACK", "0").strip() in {"1", "true", "TRUE", "yes", "YES"},
        help="Responde 2xx para testes de verify sem assinatura/payload valido (nao processa evento)",
    )

    webhook_drain = sub.add_parser(
        "webhook-drain",
        help="Drena fila atual do webhook server e processa eventos pendentes",
    )
    webhook_drain.add_argument(
        "--host",
        default=os.getenv("LAURA_WEBHOOK_HOST", "127.0.0.1"),
        help="Host do webhook server (default: 127.0.0.1)",
    )
    webhook_drain.add_argument(
        "--port",
        type=int,
        default=_int_from_env("LAURA_WEBHOOK_PORT", 8765),
        help="Porta do webhook server (default: 8765)",
    )

    api_serve = sub.add_parser(
        "api-serve",
        help="Sobe a API FastAPI central da Laura",
    )
    api_serve.add_argument(
        "--host",
        default=os.getenv("LAURA_API_HOST", "127.0.0.1"),
        help="Host de bind da API (default: 127.0.0.1)",
    )
    api_serve.add_argument(
        "--port",
        type=int,
        default=_int_from_env("LAURA_API_PORT", 8000),
        help="Porta de bind da API (default: 8000)",
    )
    api_serve.add_argument(
        "--reload",
        action="store_true",
        help="Ativa reload automatico durante desenvolvimento",
    )
    api_serve.add_argument(
        "--log-level",
        default=os.getenv("LAURA_API_LOG_LEVEL", "info"),
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Nivel de log do servidor Uvicorn",
    )

    # ========== Comandos LLM ==========

    llm_analyze = sub.add_parser(
        "llm-analyze",
        help="Analisa profitabilidade usando Ollama (LLM local)",
    )
    llm_analyze.add_argument(
        "--metrics-file",
        default="reports/laura_profitability_inputs_latest.json",
        help="Arquivo JSON com métricas de profitabilidade",
    )
    llm_analyze.add_argument(
        "--prompt-type",
        default="profitability_analyzer",
        choices=list(list_available_prompts().keys()),
        help="Tipo de análise LLM",
    )
    llm_analyze.add_argument(
        "--output-file",
        default="reports/laura_profitability_llm_latest.json",
        help="Arquivo para salvar resultado",
    )
    llm_analyze.add_argument(
        "--model",
        default=os.getenv("LAURA_LLM_MODEL", "tinyllama"),
        choices=_MODEL_CHOICES,
        help="Modelo Ollama a usar",
    )
    llm_analyze.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help=(
            "Timeout de requisicao LLM em segundos para esta execucao "
            "(sobrescreve LAURA_LLM_REQUEST_TIMEOUT_SECONDS)"
        ),
    )

    ollama_status = sub.add_parser(
        "ollama-status",
        help="Mostra status do Ollama, modelos instalados e modelos carregados em RAM",
    )
    ollama_status.add_argument(
        "--model",
        default=os.getenv("LAURA_LLM_MODEL", "tinyllama"),
        choices=_MODEL_CHOICES,
        help="Modelo a verificar",
    )
    ollama_status.add_argument(
        "--json",
        action="store_true",
        help="Saida em JSON",
    )

    ollama_fix = sub.add_parser(
        "ollama-fix",
        help="Diagnostica e repara Ollama: inicia serviço, puxa modelo, carrega em RAM",
    )
    ollama_fix.add_argument(
        "--model",
        default=os.getenv("LAURA_LLM_MODEL", "tinyllama"),
        choices=_MODEL_CHOICES,
        help="Modelo a carregar (default: tinyllama)",
    )
    ollama_fix.add_argument(
        "--force-pull",
        action="store_true",
        help="Força repull do modelo (atualiza) mesmo se instalado",
    )

    sub.add_parser(
        "llm-prompts",
        help="Lista os system prompts disponíveis",
    )

    dashboard_cli = sub.add_parser(
        "dashboard-cli",
        help="Gera dashboard HTML/JSON estático com métricas da loja",
    )
    dashboard_cli.add_argument(
        "--format",
        choices=["html", "json"],
        default="html",
        help="Formato de saida (html=browser, json=console)",
    )
    dashboard_cli.add_argument(
        "--output",
        help="Arquivo de saida (opcional)",
    )

    analytics = sub.add_parser(
        "analytics-trends",
        help="Analisador avancado de tendencias e anomalias",
    )
    analytics.add_argument(
        "--period",
        choices=["7", "30", "90", "365"],
        default="30",
        help="Periodo para analise (dias)",
    )
    analytics.add_argument(
        "--output",
        help="Arquivo de saida em JSON",
    )
    analytics.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Formato de saida",
    )

    anomaly = sub.add_parser(
        "anomaly-detect",
        help="Detectar anomalias em alertas e devoluções",
    )
    anomaly.add_argument(
        "--threshold",
        type=float,
        default=2.0,
        help="Limiar de desvio padrão para anomalia",
    )
    anomaly.add_argument(
        "--output",
        help="Arquivo de saida em JSON",
    )

    predict = sub.add_parser(
        "predict-refunds",
        help="Prever taxa de devoluções para proximos dias",
    )
    predict.add_argument(
        "--days",
        type=int,
        default=7,
        help="Dias a prever",
    )
    predict.add_argument(
        "--output",
        help="Arquivo de saida em JSON",
    )

    charts = sub.add_parser(
        "charts",
        help="Gerar gráficos interativos com Charts.js",
    )
    charts.add_argument(
        "--type",
        choices=["alerts", "refunds", "health", "distribution", "comparison"],
        default="alerts",
        help="Tipo de gráfico a gerar",
    )
    charts.add_argument(
        "--days",
        type=int,
        default=30,
        help="Período para análise em dias",
    )
    charts.add_argument(
        "--output",
        help="Arquivo HTML de saida",
    )

    dashboard = sub.add_parser(
        "chart-dashboard",
        help="Dashboard visual completo com múltiplos gráficos",
    )
    dashboard.add_argument(
        "--output",
        default="dashboard_charts.html",
        help="Arquivo HTML de saida (default: dashboard_charts.html)",
    )

    report = sub.add_parser(
        "performance-report",
        help="Gerar relatório de performance em JSON",
    )
    report.add_argument(
        "--days",
        type=int,
        default=30,
        help="Período para relatório em dias",
    )
    report.add_argument(
        "--output",
        help="Arquivo JSON de saida",
    )

    export = sub.add_parser(
        "export-report",
        help="Exportar relatório em múltiplos formatos (JSON/CSV/PDF/Excel)",
    )
    export.add_argument(
        "--type",
        choices=["performance", "refunds", "alerts"],
        default="performance",
        help="Tipo de relatório",
    )
    export.add_argument(
        "--formats",
        nargs="+",
        default=["json"],
        choices=["json", "csv", "pdf", "excel"],
        help="Formatos de exportação",
    )
    export.add_argument(
        "--output-dir",
        default="reports",
        help="Diretório de saida",
    )

    schedule = sub.add_parser(
        "schedule-report",
        help="Agendar geração e entrega de relatórios",
    )
    schedule.add_argument(
        "--type",
        choices=["performance", "refunds", "alerts"],
        required=True,
        help="Tipo de relatório",
    )
    schedule.add_argument(
        "--frequency",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="Frequência de entrega",
    )
    schedule.add_argument(
        "--formats",
        nargs="+",
        default=["json"],
        choices=["json", "csv", "pdf", "excel"],
        help="Formatos de exportação",
    )
    schedule.add_argument(
        "--recipients",
        nargs="+",
        help="Destinatários (emails/webhooks)",
    )
    schedule.add_argument(
        "--report-id",
        help="ID único para o relatório agendado",
    )

    realtime = sub.add_parser(
        "realtime-config",
        help="Configurar atualizações em tempo real e WebSocket",
    )
    realtime.add_argument(
        "--chart-types",
        nargs="+",
        default=["alerts", "refunds", "health"],
        choices=["alerts", "refunds", "health"],
        help="Tipos de gráficos para atualizar",
    )
    realtime.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Intervalo de atualização em segundos",
    )
    realtime.add_argument(
        "--output",
        help="Arquivo de configuração JSON",
    )

    insights_trend = sub.add_parser(
        "insights-trend",
        help="Analisar tendência com explicação IA",
    )
    insights_trend.add_argument(
        "--metric",
        choices=["alerts", "refunds"],
        default="alerts",
        help="Métrica para analisar",
    )
    insights_trend.add_argument(
        "--days",
        type=int,
        default=30,
        help="Período de análise em dias",
    )
    insights_trend.add_argument(
        "--language",
        choices=["pt_BR", "en_US"],
        default="pt_BR",
        help="Idioma da análise",
    )
    insights_trend.add_argument(
        "--output",
        help="Arquivo JSON de saída",
    )

    insights_anomaly = sub.add_parser(
        "insights-anomaly",
        help="Explicar anomalias detectadas com IA",
    )
    insights_anomaly.add_argument(
        "--language",
        choices=["pt_BR", "en_US"],
        default="pt_BR",
        help="Idioma da análise",
    )
    insights_anomaly.add_argument(
        "--output",
        help="Arquivo JSON de saída",
    )

    insights_recommendations = sub.add_parser(
        "insights-recommendations",
        help="Gerar recomendações inteligentes com IA",
    )
    insights_recommendations.add_argument(
        "--context",
        default="general",
        help="Contexto para recomendações",
    )
    insights_recommendations.add_argument(
        "--language",
        choices=["pt_BR", "en_US"],
        default="pt_BR",
        help="Idioma das recomendações",
    )
    insights_recommendations.add_argument(
        "--output",
        help="Arquivo JSON de saída",
    )

    insights_summary = sub.add_parser(
        "insights-summary",
        help="Gerar resumo executivo com IA",
    )
    insights_summary.add_argument(
        "--days",
        type=int,
        default=7,
        help="Período para resumo em dias",
    )
    insights_summary.add_argument(
        "--language",
        choices=["pt_BR", "en_US"],
        default="pt_BR",
        help="Idioma do resumo",
    )
    insights_summary.add_argument(
        "--output",
        help="Arquivo JSON de saída",
    )

    flash_sale = sub.add_parser(
        "flash-sale-recommend",
        help="Analisa estoque e vendas para sugerir flash sales automáticas",
    )
    flash_sale.add_argument(
        "--access-token",
        default=None,
        help="Access token; default do .env se omitido",
    )
    flash_sale.add_argument(
        "--shop-id",
        type=int,
        default=None,
        help="Shop ID; default do .env se omitido",
    )
    flash_sale.add_argument(
        "--min-stock",
        type=int,
        default=20,
        help="Estoque mínimo para considerar um item",
    )
    flash_sale.add_argument(
        "--discount-pct",
        type=int,
        default=15,
        help="Percentual de desconto sugerido",
    )
    flash_sale.add_argument(
        "--create",
        action="store_true",
        help="Criar a flash sale automaticamente se houver candidatos",
    )
    flash_sale.add_argument(
        "--output",
        help="Arquivo JSON de saída opcional",
    )

    activity = sub.add_parser(
        "activity",
        help="Mostra o que a Laura fez recentemente (chat, preço, estoque, comandos)",
    )
    activity.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Quantidade máxima de eventos recentes para exibir",
    )
    activity.add_argument(
        "--json",
        action="store_true",
        help="Saída em JSON",
    )
    doctor = sub.add_parser(
        "doctor",
        help="Diagnostico rapido de setup seguro (env, Shopee, Ollama)",
    )
    doctor.add_argument(
        "--env-file",
        default=".env",
        help="Caminho do arquivo .env a validar",
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Saida em JSON",
    )
    doctor.add_argument(
        "--startup-time",
        action="store_true",
        help="Mostra o tempo de startup do CLI (desde a carga do dispatch ate agora)",
    )

    # Decision Engine Commands (Phase 34)
    decision_status = sub.add_parser(
        "decision-status",
        help="Mostra decisoes pendentes do Decision Engine",
    )
    decision_status.add_argument(
        "--priority",
        choices=["critical", "high", "all"],
        default="all",
        help="Filtrar por prioridade",
    )
    decision_status.add_argument(
        "--store-id",
        default="default",
        help="Store ID para Decision Engine",
    )

    decision_history = sub.add_parser(
        "decision-history",
        help="Mostra historico de decisoes (audit log)",
    )
    decision_history.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Numero de decisoes recentes a exibir",
    )
    decision_history.add_argument(
        "--type",
        choices=["pricing", "ads", "inventory", "all"],
        default="all",
        help="Filtrar por tipo de decisao",
    )
    decision_history.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_detail = sub.add_parser(
        "decision-detail",
        help="Mostra detalhes completos de uma decisao",
    )
    decision_detail.add_argument(
        "decision_id",
        help="ID da decisao (prefixo)",
    )
    decision_detail.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_cycle = sub.add_parser(
        "decision-cycle",
        help="Executa um ciclo completo de avaliacao de decisoes",
    )
    decision_cycle.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_metrics = sub.add_parser(
        "decision-metrics",
        help="Mostra metricas de qualidade de decisoes",
    )
    decision_metrics.add_argument(
        "--days",
        type=int,
        default=7,
        help="Numero de dias para analisar",
    )
    decision_metrics.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    goal_summary = sub.add_parser(
        "goal-summary",
        help="Mostra o resumo e ranking atual de metas",
    )
    goal_summary.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    goal_list = sub.add_parser(
        "goal-list",
        help="Lista metas registradas",
    )
    goal_list.add_argument(
        "--status",
        choices=["active", "completed", "all"],
        default="active",
        help="Filtrar por status",
    )
    goal_list.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    goal_add = sub.add_parser(
        "goal-add",
        help="Registra uma nova meta",
    )
    goal_add.add_argument("name", help="Nome da meta")
    goal_add.add_argument("objective", help="Objetivo da meta")
    goal_add.add_argument(
        "--metric",
        dest="metrics",
        action="append",
        default=[],
        help="Metrica alvo no formato chave=valor",
    )
    goal_add.add_argument(
        "--budget",
        type=float,
        default=0.0,
        help="Orcamento alocado",
    )
    goal_add.add_argument(
        "--days",
        type=int,
        default=30,
        help="Horizonte em dias",
    )
    goal_add.add_argument(
        "--priority",
        type=int,
        default=3,
        help="Prioridade da meta",
    )
    goal_add.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Tag opcional da meta",
    )
    goal_add.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    goal_top = sub.add_parser(
        "goal-top",
        help="Mostra a meta com maior prioridade",
    )
    goal_top.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    goal_complete = sub.add_parser(
        "goal-complete",
        help="Marca uma meta como concluida",
    )
    goal_complete.add_argument("goal_id", help="ID da meta")
    goal_complete.add_argument(
        "--note",
        default=None,
        help="Observacao opcional",
    )
    goal_complete.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_outcomes = sub.add_parser(
        "decision-outcomes",
        help="Mostra outcomes registrados com filtros",
    )
    decision_outcomes.add_argument(
        "--days",
        type=int,
        default=7,
        help="Numero de dias para filtrar",
    )
    decision_outcomes.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_learn = sub.add_parser(
        "decision-learn",
        help="Aprende com outcomes passados e ajusta regras",
    )
    decision_learn.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_effectiveness = sub.add_parser(
        "decision-effectiveness",
        help="Mostra effectiveness scores das regras",
    )
    decision_effectiveness.add_argument(
        "--rule",
        default=None,
        help="Filter by rule ID",
    )
    decision_effectiveness.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_similar = sub.add_parser(
        "decision-similar",
        help="Busca decisoes similares por ID",
    )
    decision_similar.add_argument(
        "decision_id",
        help="ID da decisao de referencia",
    )
    decision_similar.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Numero de decisoes similares",
    )
    decision_similar.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    decision_reindex_backend = sub.add_parser(
        "decision-reindex-backend",
        help="Reindexa o backend de memoria vetorial",
    )
    decision_reindex_backend.add_argument(
        "--store-id",
        default="default",
        help="Store ID",
    )

    metrics_dashboard = sub.add_parser(
        "metrics-dashboard",
        help="Mostra dashboard de metricas do sistema via event bus",
    )
    metrics_dashboard.add_argument(
        "--live",
        action="store_true",
        help="Monitora metricas a cada 5s (Ctrl+C para parar)",
    )

    agent_orchestration = sub.add_parser(
        "agent-orchestration",
        help="Coordena agentes multi-objetivo (list, status, negotiate)",
    )
    agent_orchestration_sub = agent_orchestration.add_subparsers(dest="agent_action", required=True)
    agent_orchestration_sub.add_parser("list", help="Lista agentes registrados")
    agent_orchestration_sub.add_parser("status", help="Status atual da orquestracao")
    agent_negotiate = agent_orchestration_sub.add_parser("negotiate", help="Executa ciclo de negociacao entre agentes")
    agent_negotiate.add_argument("--context", default="{}", help="JSON com EconomicContext")

    strategic_plan = sub.add_parser(
        "strategic-plan",
        help="Executa o StrategicPlanner (Phase 38) e mostra o plano",
    )
    strategic_plan.add_argument(
        "--context-file",
        default=None,
        help="Arquivo JSON com EconomicContext",
    )

    competitive_intel_summary = sub.add_parser(
        "competitive-intel-summary",
        help="Mostra o resumo da inteligencia competitiva",
    )
    competitive_intel_summary.add_argument(
        "--offers-file",
        default="reports/competitive_offers.jsonl",
        help="Arquivo JSONL com ofertas concorrentes",
    )
    competitive_intel_summary.add_argument(
        "--our-prices-file",
        default="reports/product_prices.json",
        help="Arquivo JSON com nossos precos",
    )

    branding_growth_summary = sub.add_parser(
        "branding-growth-summary",
        help="Mostra o resumo de branding e growth",
    )
    branding_growth_summary.add_argument(
        "--catalog-file",
        default="reports/product_catalog.jsonl",
        help="Arquivo JSON/JSONL com catalogo de produtos",
    )

    economic_brain_summary = sub.add_parser(
        "economic-brain-summary",
        help="Mostra o resumo financeiro, forecast e cenarios",
    )
    economic_brain_summary.add_argument(
        "--latest-file",
        default="reports/laura_profitability_latest.json",
        help="Arquivo JSON com a profitabilidade atual",
    )
    economic_brain_summary.add_argument(
        "--history-file",
        default="reports/laura_profitability_history.jsonl",
        help="Arquivo JSONL com o historico de profitabilidade",
    )

    # Comandos plugaveis - cli_commands
    from shopee_agent.cli_commands.auth_shop_cmd import register_subparsers as register_auth_shop
    from shopee_agent.cli_commands.cache_cmd import register_subparsers as register_cache
    from shopee_agent.cli_commands.chat_cmd import register_subparsers as register_chat
    from shopee_agent.cli_commands.cleanup_cmd import register_cleanup_parser
    from shopee_agent.cli_commands.email_cmd import register_subparsers as register_email
    from shopee_agent.cli_commands.export_cmd import register_export_parser
    from shopee_agent.cli_commands.health_cmd import register_health_parser
    from shopee_agent.cli_commands.monitor_cmd import register_subparsers as register_monitor
    from shopee_agent.cli_commands.order_cmd import register_subparsers as register_order
    from shopee_agent.cli_commands.product_cmd import register_subparsers as register_product
    from shopee_agent.cli_commands.report_cmd import register_subparsers as register_report
    from shopee_agent.cli_commands.seller_cmd import register_subparsers as register_seller
    from shopee_agent.cli_commands.watchdog_cmd import register_subparsers as register_watchdog
    register_export_parser(sub)
    register_cleanup_parser(sub)
    register_health_parser(sub)
    build_completion_parser(sub)
    register_auth_shop(sub)
    register_product(sub)
    register_order(sub)
    register_report(sub)
    register_chat(sub)
    register_seller(sub)
    register_email(sub)
    register_cache(sub)
    register_monitor(sub)
    register_watchdog(sub)

    # ── Daemon guardian ─────────────────────────────────────────────────────────
    from shopee_agent.daemon_guardian import build_parser as build_guardian_parser
    build_guardian_parser(sub)

    # ── API usage monitor ───────────────────────────────────────────────────────
    api_usage_parser = sub.add_parser(
        "api-usage",
        help="Monitora uso da API Shopee contra limite diario",
    )
    api_usage_parser.add_argument("--reset-alerts", action="store_true", help="Reseta alertas emitidos hoje")
    api_usage_parser.add_argument("--check", action="store_true", help="Verifica uso e envia alerta Telegram se necessario")

    # ── Queue management ────────────────────────────────────────────────────────
    queue_parser = sub.add_parser("queue", help="Gerenciamento do event bus (status, DLQ, retry)")
    queue_sub = queue_parser.add_subparsers(dest="queue_action", required=True)
    queue_sub.add_parser("status", help="Status da fila de eventos")
    q_dlq = queue_sub.add_parser("dlq", help="Lista eventos na dead-letter queue")
    q_dlq.add_argument("--max", type=int, default=10, help="Maximo de eventos a exibir")
    q_retry = queue_sub.add_parser("retry", help="Reenfileira eventos da DLQ")
    q_retry.add_argument("--max", type=int, default=0, help="Maximo a reenfileirar (0=todos)")

    # ── Metrics export ───────────────────────────────────────────────────────────
    metrics_export_parser = sub.add_parser("metrics-export", help="Exporta metricas no formato Prometheus")
    metrics_export_parser.add_argument("--output", default="", help="Arquivo de saida (stdout se vazio)")

    # ── Flash sale exec ─────────────────────────────────────────────────━━───
    flash_sale_exec = sub.add_parser("flash-sale-exec", help="Executa flash sales automaticamente")
    flash_sale_exec.add_argument("action", choices=["create", "list", "cancel"], help="Acao")
    flash_sale_exec.add_argument("--item-id", type=int, default=0, help="Item ID para cancel")
    flash_sale_exec.add_argument("--discount", type=int, default=15, help="Desconto percentual")
    flash_sale_exec.add_argument("--auto-approve", action="store_true", help="Aprovar sem confirmacao")

    # ── A/B auto-promote ─────────────────────────────────────────────────────────
    ab_auto = sub.add_parser("ab-auto-promote", help="Auto-promocao de testes A/B com significancia estatistica")
    ab_auto.add_argument("--test-id", default="", help="ID do teste especifico (vazio=todos)")
    ab_auto.add_argument("--min-confidence", type=float, default=0.95, help="Confianca minima (0-1)")
    ab_auto.add_argument("--min-samples", type=int, default=30, help="Amostras minimas")

    # ── Browser run ──────────────────────────────────────────────────────────────
    browser_parser = sub.add_parser("browser-run", help="Executa automacao via browser (CDP/Playwright)")
    browser_parser.add_argument("action", choices=["navigate", "click", "type", "screenshot", "extract", "evaluate"])
    browser_parser.add_argument("--url", default="", help="URL alvo")
    browser_parser.add_argument("--selector", default="", help="Seletor CSS")
    browser_parser.add_argument("--value", default="", help="Valor para type")
    browser_parser.add_argument("--js", default="", help="Codigo JS para evaluate")
    browser_parser.add_argument("--screenshot", action="store_true", help="Tirar screenshot")

    # ── Supply chain ─────────────────────────────────────────────────────────────
    sc_parser = sub.add_parser("supply-chain", help="Analise e otimizacao da cadeia de suprimentos v2")
    sc_sub = sc_parser.add_subparsers(dest="sc_action", required=True)
    sc_score = sc_sub.add_parser("score-supplier", help="Pontua fornecedor")
    sc_score.add_argument("--supplier-id", default="sup_001", help="ID do fornecedor")
    sc_po = sc_sub.add_parser("generate-po", help="Gera ordem de compra")
    sc_po.add_argument("--supplier-id", default="sup_001", help="ID do fornecedor")
    sc_po.add_argument("--items", default='[{"name":"Item A","qty":100}]', help="JSON com itens")
    sc_sub.add_parser("balance", help="Sugere balanceamento de estoque entre warehouses")

    # ── Federated learning v2 ─────────────────────────────────────────────────────
    fed_v2 = sub.add_parser("federated-v2", help="Federated learning avancado com privacidade diferencial")
    fed_v2_sub = fed_v2.add_subparsers(dest="fed_v2_action", required=True)
    fed_v2_secure = fed_v2_sub.add_parser("secure-round", help="Rodada de agregacao segura")
    fed_v2_secure.add_argument("--reports", default='[{"store":"a","data":{"cost":1.5}},{"store":"b","data":{"cost":2.5}}]', help="JSON com reports")
    fed_v2_cross = fed_v2_sub.add_parser("cross-train", help="Treinamento cross-store")
    fed_v2_cross.add_argument("--store-id", default="store_a", help="Store ID")
    fed_v2_cross.add_argument("--rounds", type=int, default=3, help="Numero de rounds")
    fed_v2_sub.add_parser("privacy", help="Relatorio de privacidade")

    # ── Campaign management ────────────────────────────────────────────────────
    campaign_parser = sub.add_parser("campaign", help="Gerenciamento de campanhas promocionais")
    campaign_sub = campaign_parser.add_subparsers(dest="campaign_action", required=True)
    campaign_sub.add_parser("list", help="Lista campanhas ativas")
    camp_bundle = campaign_sub.add_parser("bundle", help="Cria bundle deal")
    camp_bundle.add_argument("--name", default="Bundle Promocional", help="Nome do bundle")
    camp_bundle.add_argument("--items", default='[{"item_id":123}]', help="JSON com items")
    camp_bundle.add_argument("--discount", type=int, default=10, help="Desconto percentual")
    camp_voucher = campaign_sub.add_parser("voucher", help="Cria voucher")
    camp_voucher.add_argument("--name", default="Voucher Laura", help="Nome do voucher")
    camp_voucher.add_argument("--value", type=float, default=10.0, help="Valor do voucher")
    camp_voucher.add_argument("--min-spend", type=float, default=50.0, help="Gasto minimo")
    camp_voucher.add_argument("--quantity", type=int, default=100, help="Quantidade")
    camp_auto = campaign_sub.add_parser("auto", help="Sugere campanhas baseado em metricas")
    camp_auto.add_argument("--metrics", default='{}', help="JSON com metricas")

    # ── Workers management ─────────────────────────────────────────────────────
    workers_parser = sub.add_parser("workers", help="Gerenciamento de workers")
    workers_sub = workers_parser.add_subparsers(dest="workers_action", required=True)
    workers_sub.add_parser("list", help="Lista workers")
    workers_status = workers_sub.add_parser("status", help="Status detalhado de um worker")
    workers_status.add_argument("worker_name", help="Nome do worker")
    workers_pause = workers_sub.add_parser("pause", help="Pausa worker")
    workers_pause.add_argument("worker_name", help="Nome do worker")
    workers_resume = workers_sub.add_parser("resume", help="Retoma worker")
    workers_resume.add_argument("worker_name", help="Nome do worker")
    workers_sub.add_parser("stats", help="Estatisticas da fila")

    # ── Cross-selling ──────────────────────────────────────────────────────────
    xsell_parser = sub.add_parser("cross-sell", help="Recomendacao de produtos complementares")
    xsell_sub = xsell_parser.add_subparsers(dest="xsell_action", required=True)
    xsell_rec = xsell_sub.add_parser("recommend", help="Recomenda para um produto")
    xsell_rec.add_argument("product_id", help="ID do produto")
    xsell_rec.add_argument("--top-n", type=int, default=5, help="Numero de recomendacoes")
    xsell_pairs = xsell_sub.add_parser("top-pairs", help="Pares mais vendidos juntos")
    xsell_pairs.add_argument("--top-n", type=int, default=10, help="Numero de pares")
    xsell_bundle = xsell_sub.add_parser("bundle", help="Recomenda para um carrinho")
    xsell_bundle.add_argument("--items", default='["123","456"]', help="JSON com items no carrinho")

    # ── Seller Center Full Automation ─────────────────────────────────────────
    sc_parser = sub.add_parser("sc", help="Automacao completa do Seller Center")
    sc_sub = sc_parser.add_subparsers(dest="sc_action", required=True)

    sc_products = sc_sub.add_parser("products", help="Lista produtos")
    sc_products.add_argument("--page", type=int, default=1)
    sc_products.add_argument("--page-size", type=int, default=100)

    sc_product_detail = sc_sub.add_parser("product", help="Detalhe do produto")
    sc_product_detail.add_argument("item_id", help="ID do item")

    sc_orders = sc_sub.add_parser("orders", help="Lista pedidos")
    sc_orders.add_argument("--status", default="all", help="all|READY_TO_SHIP|COMPLETED|CANCELLED")
    sc_orders.add_argument("--days", type=int, default=7)

    sc_ship = sc_sub.add_parser("ship", help="Envia pedido")
    sc_ship.add_argument("order_sn", help="Order SN")

    sc_sub.add_parser("pending", help="Envios pendentes")

    sc_sub.add_parser("balance", help="Saldo da conta")

    sc_sub.add_parser("campaigns", help="Lista campanhas")

    sc_sub.add_parser("perf", help="Performance da loja")

    sc_sub.add_parser("violations", help="Violacoes de listing")

    sc_bulk_price = sc_sub.add_parser("bulk-price", help="Atualiza precos em lote")
    sc_bulk_price.add_argument("--items", default='[]', help="JSON com [{\"item_id\":123,\"price\":49.90}]")

    sc_bulk_stock = sc_sub.add_parser("bulk-stock", help="Atualiza estoque em lote")
    sc_bulk_stock.add_argument("--items", default='[]', help="JSON com [{\"item_id\":123,\"stock\":100}]")

    sc_export = sc_sub.add_parser("export", help="Exporta produtos para CSV")
    sc_export.add_argument("--filepath", default="produtos_exportados.csv")

    # ── Vision ─────────────────────────────────────────────────────────────────
    from .vision import build_parser as build_vision_parser
    build_vision_parser(sub)

    # ── Chat automation ────────────────────────────────────────────────────────
    from .chat_auto import build_parser as build_chat_parser
    build_chat_parser(sub)

    # ── Telegram bot ───────────────────────────────────────────────────────────
    from .telegram_bot import build_parser as build_telegram_parser
    build_telegram_parser(sub)

    # ── Reports ────────────────────────────────────────────────────────────────
    from .reporting import build_parser as build_report_parser
    build_report_parser(sub)

    # ── Plugin marketplace ─────────────────────────────────────────────────────
    from .plugin_marketplace import build_parser as build_plugin_parser
    build_plugin_parser(sub)

    # ── Schema migrations ─────────────────────────────────────────────────────
    from .schema_migrations import build_parser as build_db_parser
    build_db_parser(sub)

    # ── Security audit ─────────────────────────────────────────────────────────
    from .security_audit import build_parser as build_audit_parser
    build_audit_parser(sub)

    # ── Backup management ──────────────────────────────────────────────────────
    from .backup import build_parser as build_backup_parser
    build_backup_parser(sub)

    # ── Setup wizard ───────────────────────────────────────────────────────────
    from .setup_wizard import build_parser as build_setup_parser
    build_setup_parser(sub)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    info("Laura command started", command=args.command, sys_argv=" ".join(sys.argv[1:]))

    # Initialize circuit breakers for all monitored endpoints
    initialize_default_circuit_breakers()
    debug("Circuit breakers initialized")

    # Comandos LLM locais nao dependem de credenciais Shopee.
    if args.command in {"db", "audit", "backup", "auto-login", "llm-prompts", "llm-analyze", "doctor", "dashboard", "webhook-start", "webhook-drain", "api-serve", "activity", "ollama-status", "ollama-fix", "goal-summary", "goal-list", "goal-add", "goal-top", "goal-complete", "competitive-intel-summary", "branding-growth-summary", "economic-brain-summary", "setup", "visual-analysis", "support-triage", "support-summary", "learning-summary", "strategy-summary", "self-healing-summary", "seller-center-import", "seller-center-status", "daemon", "guardian", "api-usage", "shell", "dashboard-cli", "export", "cleanup", "health", "skill-list", "skill-register", "skill-goap-plan", "skill-run", "skill-history", "trace", "skill-test", "goal-synthesize", "goal-nl", "skill-approve", "skill-reject", "skill-approval-list", "store-list", "store-init", "store-summary", "benchmark", "skill-generate", "skill-goap-explain", "skill-rollback-learning", "learning-stats", "ab-test-start", "ab-test-status", "canary-start", "canary-status", "canary-promote", "canary-rollback", "sandbox-test", "skill-simulate", "skill-reload", "skill-profile", "plan-store", "planner-alerts", "plan-viz", "plan-diff", "plan-export", "plan-import", "plan-batch", "skill-create", "goal-library", "plan-schedule", "plan-optimize", "skill-anomaly", "skill-version", "plan-template", "multi-approve", "plan-heal", "plan-explain", "proactive-goals", "cost-predict", "skill-market", "federated", "plan-conform", "queue", "plugin", "metrics-export", "flash-sale-exec", "ab-auto-promote", "browser-run", "supply-chain", "federated-v2", "tenant", "campaign", "workers", "cross-sell", "vision", "chat", "telegram", "report", "completion", "api-endpoints", "api-families", "anomaly-detect", "predict-refunds", "performance-report", "export-report", "schedule-report", "realtime-config", "decision-status", "decision-history", "decision-detail", "decision-cycle", "decision-metrics", "decision-outcomes", "decision-learn", "decision-effectiveness", "decision-similar", "decision-reindex-backend", "metrics-dashboard", "agent-orchestration", "health-check"}:  # fmt: skip
        cfg = None
        client = None
    else:
        try:
            cfg = load_config()
        except ConfigError as exc:
            log_error("Config load failed", error=str(exc))
            parser.error(str(exc))
        from .client import ShopeeClient

        client = ShopeeClient(cfg)
        debug("Shopee client initialized")


    # Dispatch extracted commands to their modules
    handler_fn = _get_extracted_dispatch().get(args.command) or _get_all_handlers().get(args.command)
    if handler_fn:
        return handler_fn(args, client=client, cfg=cfg)
    # All command handlers have been extracted to all_handlers.py
    # and are dispatched via HANDLER_DISPATCH above.

    parser.error("Comando invalido")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
