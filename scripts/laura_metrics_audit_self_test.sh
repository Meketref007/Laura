#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORTS_DIR="$ROOT_DIR/reports"
SELFTEST_LATEST_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_latest.json"
SELFTEST_HISTORY_FILE="$REPORTS_DIR/laura_metrics_audit_self_test_history.jsonl"
ENABLED="${LAURA_METRICS_AUDIT_SELF_TEST_ENABLED:-1}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura metrics audit self-test disabled by LAURA_METRICS_AUDIT_SELF_TEST_ENABLED=0"
  exit 0
fi

cd "$ROOT_DIR"
mkdir -p "$REPORTS_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

notify() {
  local message="$1"
  if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
    curl -sS -X POST \
      "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=${message}" \
      >/dev/null || true
  fi
}

run_check() {
  local label="$1"
  local cmd="$2"
  local out_file="$3"

  if bash -lc "$cmd" >"$out_file" 2>&1; then
    echo "OK|$label"
  else
    echo "FAIL|$label"
  fi
}

results=()
results_file="/tmp/laura_audit_selftest_results.tmp"
: > "$results_file"
results+=("$(run_check "audit_guard" "./scripts/laura_metrics_audit_guard.sh" "/tmp/laura_audit_selftest_guard.out")")
results+=("$(run_check "freshness_guard" "./scripts/laura_metrics_audit_freshness_guard.sh" "/tmp/laura_audit_selftest_freshness.out")")
results+=("$(run_check "volume_guard" "./scripts/laura_metrics_audit_volume_guard.sh" "/tmp/laura_audit_selftest_volume.out")")
results+=("$(run_check "schema_guard" "./scripts/laura_metrics_audit_schema_guard.sh" "/tmp/laura_audit_selftest_schema.out")")
results+=("$(run_check "early_warning" "./scripts/laura_metrics_audit_early_warning.sh" "/tmp/laura_audit_selftest_early.out")")
results+=("$(run_check "audit_digest" "./scripts/laura_metrics_audit_digest.sh" "/tmp/laura_audit_selftest_digest.out")")

for item in "${results[@]}"; do
  printf '%s\n' "$item" >> "$results_file"
done

fails=0
summary_lines=()
for item in "${results[@]}"; do
  status="${item%%|*}"
  label="${item##*|}"
  if [[ "$status" == "OK" ]]; then
    summary_lines+=("- ${label}: OK")
  else
    summary_lines+=("- ${label}: FAIL")
    fails=$((fails + 1))
  fi
done

python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

results_path = Path("$results_file")
latest_path = Path("$SELFTEST_LATEST_FILE")
history_path = Path("$SELFTEST_HISTORY_FILE")

checks = []
for line in results_path.read_text(encoding="utf-8").splitlines():
  s = line.strip()
  if not s or "|" not in s:
    continue
  status, label = s.split("|", 1)
  checks.append({"name": label, "status": status})

payload = {
  "timestamp": datetime.now(timezone.utc).isoformat(),
  "host": "$(hostname)",
  "failures": int("$fails"),
  "total": int("${#results[@]}"),
  "checks": checks,
}

latest_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
with history_path.open("a", encoding="utf-8") as f:
  f.write(json.dumps(payload, ensure_ascii=True) + "\n")
PY

rm -f "$results_file"

msg="Laura Metrics Audit Self-Test\nHost: $(hostname)\nFailures: ${fails}/${#results[@]}\n$(printf '%s\n' "${summary_lines[@]}")\nArtifacts: ${SELFTEST_LATEST_FILE} | ${SELFTEST_HISTORY_FILE}"
notify "$msg"

if (( fails > 0 )); then
  echo "$msg"
  echo "Logs: /tmp/laura_audit_selftest_*.out"
  exit 1
fi

echo "$msg"
exit 0
