#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
if [[ "$MODE" != "apply" && "$MODE" != "--check" ]]; then
  echo "Usage: $0 [apply|--check]" >&2
  exit 2
fi

# Managed Laura schedules.
laura_jobs=(
  "@reboot /home/shopee/agente/scripts/run_laura_healthcheck.sh"
  "@reboot /home/shopee/agente/scripts/laura_tunnel_permanent.sh ensure"
  "0 */3 * * * /home/shopee/agente/scripts/run_laura_healthcheck.sh"
  "*/5 * * * * /home/shopee/agente/scripts/laura_tunnel_permanent.sh ensure"
  "*/10 * * * * /home/shopee/agente/scripts/laura_webhook_ready_guard.sh"
  "50 8 * * * /home/shopee/agente/scripts/laura_webhook_ready_digest.sh"
  "15 * * * * /home/shopee/agente/scripts/laura_watchdog.sh"
  "0 8 * * * /home/shopee/agente/scripts/laura_daily_report.sh"
  "30 2 * * * /home/shopee/agente/scripts/laura_backup.sh"
  "45 3 * * * /home/shopee/agente/scripts/laura_verify_backup.sh"
  "15 4 * * 0 /home/shopee/agente/scripts/laura_restore_drill.sh"
  "20 * * * * /home/shopee/agente/scripts/laura_cron_guard.sh"
  "30 4 * * 0 /home/shopee/agente/scripts/laura_self_test.sh"
  "45 4 * * 0 /home/shopee/agente/scripts/laura_housekeeping.sh"
  "0 5 * * 0 /home/shopee/agente/scripts/laura_reports_housekeeping.sh"
  "40 5 * * 0 /home/shopee/agente/scripts/laura_metrics_audit_self_test.sh"
  "15 5 * * 0 /home/shopee/agente/scripts/laura_security_guard.sh"
  "0 6 1 * * /home/shopee/agente/scripts/laura_dr_monthly.sh"
  "35 * * * * /home/shopee/agente/scripts/laura_success_guard.sh"
  "10 9 1 * * /home/shopee/agente/scripts/laura_security_reminder.sh"
  "25 * * * * /home/shopee/agente/scripts/laura_metrics_snapshot.sh"
  "1 * * * * /home/shopee/agente/scripts/laura_profitability_csv_ingest.sh"
  "2 * * * * /home/shopee/agente/scripts/laura_profitability_input_builder.sh"
  "10 1 * * * /home/shopee/agente/scripts/laura_ingest_order_revenue.sh"
  "5 * * * * /home/shopee/agente/scripts/laura_profitability_autopilot.sh"
  "8 * * * * /home/shopee/agente/scripts/laura_profitability_input_freshness_guard.sh"
  "9 * * * * /home/shopee/agente/scripts/laura_llm_baseline_alert.sh"
  "30 8 * * * /home/shopee/agente/scripts/laura_metrics_digest.sh"
  "35 8 * * * /home/shopee/agente/scripts/laura_metrics_audit_digest.sh"
  "40 8 * * * /home/shopee/agente/scripts/laura_metrics_audit_self_test_digest.sh"
  "45 8 * * * /home/shopee/agente/scripts/laura_metrics_audit_self_test_guard.sh"
  "46 * * * * /home/shopee/agente/scripts/laura_metrics_audit_self_test_digest_freshness_guard.sh"
  "47 * * * * /home/shopee/agente/scripts/laura_metrics_audit_self_test_digest_volume_guard.sh"
  "48 * * * * /home/shopee/agente/scripts/laura_metrics_audit_self_test_digest_schema_guard.sh"
  "49 * * * * /home/shopee/agente/scripts/laura_metrics_audit_self_test_digest_early_warning.sh"
  "40 * * * * /home/shopee/agente/scripts/laura_metrics_guard.sh"
  "50 * * * * /home/shopee/agente/scripts/laura_metrics_audit_guard.sh"
  "52 * * * * /home/shopee/agente/scripts/laura_metrics_audit_freshness_guard.sh"
  "53 * * * * /home/shopee/agente/scripts/laura_metrics_audit_volume_guard.sh"
  "54 * * * * /home/shopee/agente/scripts/laura_metrics_audit_schema_guard.sh"
  "55 * * * * /home/shopee/agente/scripts/laura_metrics_audit_early_warning.sh"
  "45 8 * * 1 /home/shopee/agente/scripts/laura_metrics_weekly_report.sh"
)

venv_python="/home/shopee/agente/.venv/bin/python"

start_marker="# BEGIN LAURA MANAGED CRON"
end_marker="# END LAURA MANAGED CRON"

current_cron="$(crontab -l 2>/dev/null || true)"

# 1) Remove previous managed block.
without_managed_block="$(printf "%s\n" "$current_cron" | awk -v s="$start_marker" -v e="$end_marker" '
  $0==s {inblock=1; next}
  $0==e {inblock=0; next}
  !inblock {print}
')"

# 2) Remove Laura job lines outside managed block to avoid duplicates.
cleaned="$without_managed_block"
for job in "${laura_jobs[@]}"; do
  cleaned="$(printf "%s\n" "$cleaned" | awk -v j="$job" '$0!=j {print}')"
done

# Remove any Laura runtime entry outside the managed block. The managed block is
# the source of truth for all production jobs.
cleaned="$(printf "%s\n" "$cleaned" | grep -Ev '/home/shopee/agente/scripts/|shopee_agent\.(cli|decision_cli)|shopee_agent\.autonomous-loop' || true)"

# 3) Build managed block.
managed_block="$start_marker"
for job in "${laura_jobs[@]}"; do
  managed_block+=$'\n'"$job"
done
managed_block+=$'\n'"$end_marker"

# 4) Compose final cron (preserve non-Laura entries + managed block).
trimmed_cleaned="$(printf "%s\n" "$cleaned" | awk 'NF{print}')"
if [[ -n "$trimmed_cleaned" ]]; then
  final_cron="$trimmed_cleaned"$'\n\n'"$managed_block"
else
  final_cron="$managed_block"
fi

if [[ "$MODE" == "--check" ]]; then
  if [[ "$current_cron" == "$final_cron" ]]; then
    echo "Laura cron check OK: already reconciled."
    exit 0
  fi
  echo "Laura cron check FAIL: drift detected. Run with 'apply'."
  exit 1
fi

printf "%s\n" "$final_cron" | crontab -
echo "Laura cron reconciled successfully."
crontab -l
