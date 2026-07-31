#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
METRICS_FILE="$REPORTS_DIR/laura_metrics.jsonl"
WINDOW_HOURS="${LAURA_METRICS_DIGEST_WINDOW_HOURS:-24}"
ENABLED="${LAURA_METRICS_DIGEST_ENABLED:-1}"
TREND_STABLE_DELTA="${LAURA_METRICS_DIGEST_TREND_STABLE_DELTA:-2}"
AUTO_REMEDIATE_ENABLED="${LAURA_METRICS_AUTO_REMEDIATE_ENABLED:-0}"
AUTO_REMEDIATE_COOLDOWN_HOURS="${LAURA_METRICS_AUTO_REMEDIATE_COOLDOWN_HOURS:-6}"
AUTO_REMEDIATE_DRY_RUN="${LAURA_METRICS_AUTO_REMEDIATE_DRY_RUN:-0}"
AUTO_REMEDIATE_STATE_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_state.json"
AUTO_REMEDIATE_AUDIT_FILE="$REPORTS_DIR/laura_metrics_auto_remediate_audit.jsonl"

if ! [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
  WINDOW_HOURS=24
fi
if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi
if ! [[ "$TREND_STABLE_DELTA" =~ ^[0-9]+$ ]]; then
  TREND_STABLE_DELTA=2
fi
if ! [[ "$AUTO_REMEDIATE_ENABLED" =~ ^[01]$ ]]; then
  AUTO_REMEDIATE_ENABLED=0
fi
if ! [[ "$AUTO_REMEDIATE_COOLDOWN_HOURS" =~ ^[0-9]+$ ]]; then
  AUTO_REMEDIATE_COOLDOWN_HOURS=6
fi
if ! [[ "$AUTO_REMEDIATE_DRY_RUN" =~ ^[01]$ ]]; then
  AUTO_REMEDIATE_DRY_RUN=0
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics digest disabled by LAURA_METRICS_DIGEST_ENABLED=0"
  exit 0
fi

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

if [[ ! -f "$METRICS_FILE" ]]; then
  echo "Metrics file not found: $METRICS_FILE"
  exit 0
fi

summary_json="$(python3 - <<PY
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

metrics_file = Path("$METRICS_FILE")
window_hours = int("$WINDOW_HOURS")
stable_delta = int("$TREND_STABLE_DELTA")
now = datetime.now(timezone.utc)
current_cutoff = now - timedelta(hours=window_hours)
previous_cutoff = now - timedelta(hours=window_hours * 2)

current_rows = []
previous_rows = []
for line in metrics_file.read_text(encoding="utf-8").splitlines():
  line = line.strip()
  if not line:
    continue
  try:
    row = json.loads(line)
    ts = row.get("timestamp")
    if not ts:
      continue
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt >= current_cutoff:
      current_rows.append(row)
    elif previous_cutoff <= dt < current_cutoff:
      previous_rows.append(row)
  except Exception:
    continue

def parse_weight(value, default):
  try:
    w = int(value)
    if 0 <= w <= 100:
      return w
  except Exception:
    pass
  return default

weights = {
  "api": parse_weight("${LAURA_METRICS_SCORE_WEIGHT_API:-25}", 25),
  "cron": parse_weight("${LAURA_METRICS_SCORE_WEIGHT_CRON:-25}", 25),
  "backup": parse_weight("${LAURA_METRICS_SCORE_WEIGHT_BACKUP:-25}", 25),
  "full": parse_weight("${LAURA_METRICS_SCORE_WEIGHT_FULL:-25}", 25),
}

weight_sum = sum(weights.values())
if weight_sum <= 0:
  weights = {"api": 25, "cron": 25, "backup": 25, "full": 25}
  weight_sum = 100

def score_band(score):
  if score >= 95:
    return "EXCELLENT"
  if score >= 85:
    return "GOOD"
  if score >= 70:
    return "AT_RISK"
  return "CRITICAL"

def summarize(rows):
  total = len(rows)
  if total == 0:
    return {
      "total": 0,
      "api_ok": 0,
      "cron_ok": 0,
      "backup_ok": 0,
      "full_ok": 0,
      "health_score": 0,
      "health_band": "CRITICAL",
      "api_fail": 0,
      "cron_fail": 0,
      "backup_fail": 0,
      "top_cause": "NO_DATA",
      "top_cause_loss_points": 0.0,
      "latest_shop": "unknown",
      "latest_status": "unknown",
    }

  api_ok = sum(1 for r in rows if r.get("api_ok") is True)
  cron_ok = sum(1 for r in rows if r.get("cron_ok") is True)
  backup_ok = sum(1 for r in rows if r.get("backup_verify_ok") is True)
  full_ok = sum(1 for r in rows if r.get("api_ok") and r.get("cron_ok") and r.get("backup_verify_ok"))

  api_rate = api_ok / total
  cron_rate = cron_ok / total
  backup_rate = backup_ok / total
  full_rate = full_ok / total

  api_fail = total - api_ok
  cron_fail = total - cron_ok
  backup_fail = total - backup_ok

  # Impact estimate in score points per component to highlight the main driver.
  losses = {
    "API": (1.0 - api_rate) * weights["api"],
    "CRON": (1.0 - cron_rate) * weights["cron"],
    "BACKUP": (1.0 - backup_rate) * weights["backup"],
  }
  top_cause = max(losses, key=losses.get)
  top_cause_loss_points = round(losses[top_cause], 1)

  score = round(
    100.0
    * (
      api_rate * weights["api"]
      + cron_rate * weights["cron"]
      + backup_rate * weights["backup"]
      + full_rate * weights["full"]
    )
    / weight_sum
  )

  latest = rows[-1]
  return {
    "total": total,
    "api_ok": api_ok,
    "cron_ok": cron_ok,
    "backup_ok": backup_ok,
    "full_ok": full_ok,
    "health_score": score,
    "health_band": score_band(score),
    "api_fail": api_fail,
    "cron_fail": cron_fail,
    "backup_fail": backup_fail,
    "top_cause": top_cause,
    "top_cause_loss_points": top_cause_loss_points,
    "latest_shop": latest.get("shop_name", "unknown"),
    "latest_status": latest.get("shop_status", "unknown"),
  }

current = summarize(current_rows)
previous = summarize(previous_rows)

if previous["total"] == 0:
  trend_label = "NO_BASELINE"
  trend_delta = 0
elif current["health_score"] > previous["health_score"] + stable_delta:
  trend_label = "IMPROVING"
  trend_delta = current["health_score"] - previous["health_score"]
elif current["health_score"] < previous["health_score"] - stable_delta:
  trend_label = "DECLINING"
  trend_delta = current["health_score"] - previous["health_score"]
else:
  trend_label = "STABLE"
  trend_delta = current["health_score"] - previous["health_score"]

out = {
  **current,
  "prev_total": previous["total"],
  "prev_health_score": previous["health_score"],
  "trend_label": trend_label,
  "trend_delta": trend_delta,
}
print(json.dumps(out, ensure_ascii=True))
PY
)"

if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Telegram not configured; digest computed: $summary_json"
  exit 0
fi

message="$(python3 - <<PY
import json

s = json.loads('''$summary_json''')
total = s.get("total", 0)
api_ok = s.get("api_ok", 0)
cron_ok = s.get("cron_ok", 0)
backup_ok = s.get("backup_ok", 0)
full_ok = s.get("full_ok", 0)
health_score = s.get("health_score", 0)
health_band = s.get("health_band", "UNKNOWN")
api_fail = s.get("api_fail", 0)
cron_fail = s.get("cron_fail", 0)
backup_fail = s.get("backup_fail", 0)
top_cause = s.get("top_cause", "NO_DATA")
top_cause_loss_points = s.get("top_cause_loss_points", 0.0)
prev_total = s.get("prev_total", 0)
prev_health_score = s.get("prev_health_score", 0)
trend_label = s.get("trend_label", "NO_BASELINE")
trend_delta = s.get("trend_delta", 0)
latest_shop = s.get("latest_shop", "unknown")
latest_status = s.get("latest_status", "unknown")

if trend_label == "IMPROVING":
  trend_line = f"Trend: IMPROVING (+{trend_delta})"
elif trend_label == "DECLINING":
  trend_line = f"Trend: DECLINING ({trend_delta})"
elif trend_label == "STABLE":
  sign = "+" if trend_delta > 0 else ""
  trend_line = f"Trend: STABLE ({sign}{trend_delta})"
else:
  trend_line = "Trend: NO_BASELINE"

if top_cause == "NO_DATA":
  top_cause_line = "Top Cause: NO_DATA"
elif top_cause == "API":
  top_cause_line = f"Top Cause: API (fails={api_fail}/{total}, impact={top_cause_loss_points} pts)"
elif top_cause == "CRON":
  top_cause_line = f"Top Cause: CRON (fails={cron_fail}/{total}, impact={top_cause_loss_points} pts)"
else:
  top_cause_line = f"Top Cause: BACKUP (fails={backup_fail}/{total}, impact={top_cause_loss_points} pts)"

if top_cause == "API":
  action_line = "Recommended Action: run /home/shopee/agente/scripts/run_laura_healthcheck.sh and review logs/laura_healthcheck.log"
elif top_cause == "CRON":
  action_line = "Recommended Action: run /home/shopee/agente/scripts/laura_reconcile_cron.sh --check and /home/shopee/agente/scripts/laura_cron_guard.sh"
elif top_cause == "BACKUP":
  action_line = "Recommended Action: run /home/shopee/agente/scripts/laura_verify_backup.sh and inspect backups/ freshness"
else:
  action_line = "Recommended Action: ensure /home/shopee/agente/scripts/laura_metrics_snapshot.sh is scheduled and running"

print(
    "Laura Metrics Digest (${WINDOW_HOURS}h)\\n"
    f"Host: $(hostname)\\n"
    f"Health Score: {health_score}/100 ({health_band})\\n"
  f"Previous Score: {prev_health_score}/100 (samples={prev_total})\n"
  f"{trend_line}\n"
  f"{top_cause_line}\\n"
  f"{action_line}\\n"
    f"Samples: {total}\\n"
    f"API OK: {api_ok}/{total}\\n"
    f"Cron OK: {cron_ok}/{total}\\n"
    f"Backup Verify OK: {backup_ok}/{total}\\n"
    f"Full Success: {full_ok}/{total}\\n"
    f"Latest Shop: {latest_shop}\\n"
    f"Latest Status: {latest_status}"
)
PY
)"

auto_line="Auto-Remediation: disabled (set LAURA_METRICS_AUTO_REMEDIATE_ENABLED=1 to enable)"
if [[ "$AUTO_REMEDIATE_ENABLED" == "0" ]]; then
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

audit = Path("$AUTO_REMEDIATE_AUDIT_FILE")
audit.parent.mkdir(parents=True, exist_ok=True)
entry = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "script": "laura_metrics_digest.sh",
  "mode": "decision",
  "status": "auto_disabled",
  "cause": "N/A",
  "health_band": "N/A",
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(entry, ensure_ascii=True) + "\\n")
PY
fi
if [[ "$AUTO_REMEDIATE_ENABLED" == "1" ]]; then
  read -r health_band top_cause < <(
    python3 - <<PY
import json
s = json.loads('''$summary_json''')
print(s.get("health_band", "UNKNOWN"), s.get("top_cause", "NO_DATA"))
PY
  )

  if [[ "$health_band" != "CRITICAL" ]]; then
    auto_line="Auto-Remediation: skipped (health band ${health_band})"
    python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

audit = Path("$AUTO_REMEDIATE_AUDIT_FILE")
audit.parent.mkdir(parents=True, exist_ok=True)
entry = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "script": "laura_metrics_digest.sh",
  "mode": "decision",
  "status": "skipped_health_band",
  "cause": "$top_cause",
  "health_band": "$health_band",
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(entry, ensure_ascii=True) + "\\n")
PY
  elif [[ "$top_cause" == "NO_DATA" ]]; then
    auto_line="Auto-Remediation: skipped (no data baseline)"
    python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

audit = Path("$AUTO_REMEDIATE_AUDIT_FILE")
audit.parent.mkdir(parents=True, exist_ok=True)
entry = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "script": "laura_metrics_digest.sh",
  "mode": "decision",
  "status": "skipped_no_data",
  "cause": "$top_cause",
  "health_band": "$health_band",
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(entry, ensure_ascii=True) + "\\n")
PY
  else
    remediation_cmd=""
    case "$top_cause" in
      API)
        remediation_cmd="/home/shopee/agente/scripts/run_laura_healthcheck.sh"
        ;;
      CRON)
        remediation_cmd="/home/shopee/agente/scripts/laura_reconcile_cron.sh --check && /home/shopee/agente/scripts/laura_cron_guard.sh"
        ;;
      BACKUP)
        remediation_cmd="/home/shopee/agente/scripts/laura_verify_backup.sh"
        ;;
    esac

    if [[ -n "$remediation_cmd" ]]; then
      now_epoch="$(date +%s)"
      cooldown_secs="$((AUTO_REMEDIATE_COOLDOWN_HOURS * 3600))"
      last_epoch="$(python3 - <<PY
import json
from pathlib import Path

path = Path("$AUTO_REMEDIATE_STATE_FILE")
cause = "$top_cause"
if not path.exists():
  print(0)
else:
  try:
    data = json.loads(path.read_text(encoding="utf-8"))
    print(int(data.get(cause, 0)))
  except Exception:
    print(0)
PY
)"
      if ! [[ "$last_epoch" =~ ^[0-9]+$ ]]; then
        last_epoch=0
      fi

      if (( now_epoch - last_epoch < cooldown_secs )); then
        remaining="$((cooldown_secs - (now_epoch - last_epoch)))"
        auto_line="Auto-Remediation: cooldown active for ${top_cause} (${remaining}s remaining)"
        python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

audit = Path("$AUTO_REMEDIATE_AUDIT_FILE")
audit.parent.mkdir(parents=True, exist_ok=True)
entry = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "script": "laura_metrics_digest.sh",
  "mode": "decision",
  "status": "cooldown",
  "cause": "$top_cause",
  "health_band": "$health_band",
  "command": "$remediation_cmd",
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(entry, ensure_ascii=True) + "\\n")
PY
      else
        if [[ "$AUTO_REMEDIATE_DRY_RUN" == "1" ]]; then
          auto_line="Auto-Remediation: DRY-RUN for ${top_cause} (planned: ${remediation_cmd})"
          python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

audit = Path("$AUTO_REMEDIATE_AUDIT_FILE")
audit.parent.mkdir(parents=True, exist_ok=True)
entry = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "script": "laura_metrics_digest.sh",
  "mode": "dry-run",
  "cause": "$top_cause",
  "health_band": "$health_band",
  "command": "$remediation_cmd",
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(entry, ensure_ascii=True) + "\\n")
PY
        else
          if bash -lc "$remediation_cmd" >/tmp/laura_auto_remediate_digest.out 2>/tmp/laura_auto_remediate_digest.err; then
            auto_line="Auto-Remediation: executed for ${top_cause} (success)"
            run_status="success"
          else
            auto_line="Auto-Remediation: executed for ${top_cause} (failed, check /tmp/laura_auto_remediate_digest.err)"
            run_status="failed"
          fi

          python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

audit = Path("$AUTO_REMEDIATE_AUDIT_FILE")
audit.parent.mkdir(parents=True, exist_ok=True)
entry = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "script": "laura_metrics_digest.sh",
  "mode": "execute",
  "status": "$run_status",
  "cause": "$top_cause",
  "health_band": "$health_band",
  "command": "$remediation_cmd",
}
with audit.open("a", encoding="utf-8") as f:
  f.write(json.dumps(entry, ensure_ascii=True) + "\\n")
PY

          python3 - <<PY
import json
from pathlib import Path

path = Path("$AUTO_REMEDIATE_STATE_FILE")
try:
  data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
except Exception:
  data = {}
data["$top_cause"] = int("$now_epoch")
path.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
PY
        fi
      fi
    fi
  fi
fi

message="${message}"$'\n'"${auto_line}"

curl -sS -X POST \
  "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${message}" \
  >/dev/null

echo "Laura metrics digest sent."
