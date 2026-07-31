#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
HISTORY_FILE="$REPORTS_DIR/laura_profitability_llm_history.jsonl"
LATEST_FILE="$REPORTS_DIR/laura_profitability_llm_baseline_latest.json"
BASELINE_HISTORY_FILE="$REPORTS_DIR/laura_profitability_llm_baseline_history.jsonl"
WINDOW_HOURS="${LAURA_LLM_BASELINE_WINDOW_HOURS:-24}"

usage() {
  cat <<'EOF'
Uso:
  ./scripts/laura_llm_baseline_audit.sh [--window-hours N] [--history-file PATH] [--output-file PATH]

Opcoes:
  --window-hours N   Janela em horas para baseline (default: 24)
  --history-file P   JSONL de entradas LLM (default: reports/laura_profitability_llm_history.jsonl)
  --output-file P    JSON de saida latest (default: reports/laura_profitability_llm_baseline_latest.json)
  -h, --help         Exibe esta ajuda
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --window-hours)
        WINDOW_HOURS="$2"
        shift 2
        ;;
      --history-file)
        HISTORY_FILE="$2"
        shift 2
        ;;
      --output-file)
        LATEST_FILE="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Argumento desconhecido: $1" >&2
        usage
        exit 1
        ;;
    esac
  done

  if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
    echo "--window-hours deve ser inteiro positivo" >&2
    exit 1
  fi
  if (( WINDOW_HOURS < 1 )); then
    echo "--window-hours deve ser >= 1" >&2
    exit 1
  fi
}

main() {
  parse_args "$@"

  mkdir -p "$REPORTS_DIR"

  if [[ ! -f "$HISTORY_FILE" ]]; then
    echo "Laura LLM baseline audit: history nao encontrado: $HISTORY_FILE" >&2
    exit 1
  fi

  summary_json="$({
    python3 - <<PY
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

history_path = Path("$HISTORY_FILE")
window_hours = int("$WINDOW_HOURS")
now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=window_hours)


def parse_ts(value: str):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def pct(values, q):
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    values = sorted(values)
    rank = (len(values) - 1) * q
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(values[lo])
    return float(values[lo] + (values[hi] - values[lo]) * (rank - lo))


def stats(values):
    if not values:
        return {
            "count": 0,
            "min_ms": None,
            "avg_ms": None,
            "max_ms": None,
            "p50_ms": None,
            "p90_ms": None,
            "p95_ms": None,
        }
    vals = [float(v) for v in values]
    return {
        "count": len(vals),
        "min_ms": int(min(vals)),
        "avg_ms": round(sum(vals) / len(vals), 2),
        "max_ms": int(max(vals)),
        "p50_ms": round(pct(vals, 0.50), 2),
        "p90_ms": round(pct(vals, 0.90), 2),
        "p95_ms": round(pct(vals, 0.95), 2),
    }

rows = []
invalid_lines = 0
for line in history_path.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s:
        continue
    try:
        row = json.loads(s)
    except Exception:
        invalid_lines += 1
        continue

    dt = parse_ts(str(row.get("timestamp", "")))
    if dt is None:
        invalid_lines += 1
        continue

    if dt >= cutoff:
        rows.append((dt, row))

rows.sort(key=lambda x: x[0])

all_lat = []
fallback_lat = []
native_lat = []
action_counts = {}
model_counts = {}
fallback_count = 0

for dt, r in rows:
    model = str(r.get("model", "")).strip()
    action = str(r.get("action", "")).strip() or "unknown"
    is_fallback = "(fallback)" in model

    action_counts[action] = action_counts.get(action, 0) + 1
    model_counts[model or "unknown"] = model_counts.get(model or "unknown", 0) + 1

    if is_fallback:
        fallback_count += 1

    inf = r.get("inference_time_ms")
    if isinstance(inf, (int, float)):
        all_lat.append(float(inf))
        if is_fallback:
            fallback_lat.append(float(inf))
        else:
            native_lat.append(float(inf))

count = len(rows)
native_count = count - fallback_count
fallback_rate = round((fallback_count * 100.0 / count), 2) if count else None

if count < 3:
    posture = "INSUFFICIENT_DATA"
elif fallback_rate is not None and fallback_rate >= 80:
    posture = "CRITICAL"
elif fallback_rate is not None and fallback_rate >= 50:
    posture = "ATTENTION"
else:
    posture = "STABLE"

latest_ts = rows[-1][0].isoformat() if rows else None
oldest_ts = rows[0][0].isoformat() if rows else None

def top_key(d):
    if not d:
        return None
    return max(d, key=d.get)

summary = {
    "timestamp": now.isoformat(),
    "window_hours": window_hours,
    "history_file": str(history_path),
    "counts": {
        "total_runs": count,
        "fallback_runs": fallback_count,
        "native_runs": native_count,
        "invalid_rows": invalid_lines,
    },
    "fallback_rate_pct": fallback_rate,
    "latency_ms": {
        "all": stats(all_lat),
        "fallback": stats(fallback_lat),
        "native": stats(native_lat),
    },
    "top_action": top_key(action_counts),
    "top_model": top_key(model_counts),
    "action_counts": action_counts,
    "model_counts": model_counts,
    "window_range": {
        "oldest_ts": oldest_ts,
        "latest_ts": latest_ts,
    },
    "posture": posture,
}

print(json.dumps(summary, ensure_ascii=True))
PY
  } )"

  printf '%s\n' "$summary_json" > "$LATEST_FILE"
  printf '%s\n' "$summary_json" >> "$BASELINE_HISTORY_FILE"

  python3 - <<PY
import json
s = json.loads('''$summary_json''')
print("Laura LLM baseline audit")
print("=" * 60)
print(f"window_hours={s['window_hours']} posture={s['posture']}")
print(
    f"runs total={s['counts']['total_runs']} "
    f"fallback={s['counts']['fallback_runs']} "
    f"native={s['counts']['native_runs']} "
    f"fallback_rate_pct={s.get('fallback_rate_pct')}"
)
all_lat = s['latency_ms']['all']
print(
    f"latency_all_ms avg={all_lat['avg_ms']} p90={all_lat['p90_ms']} "
    f"p95={all_lat['p95_ms']} max={all_lat['max_ms']}"
)
print(f"top_action={s.get('top_action')} top_model={s.get('top_model')}")
print(f"latest_file=$LATEST_FILE")
print(f"history_file=$BASELINE_HISTORY_FILE")
PY
}

main "$@"
