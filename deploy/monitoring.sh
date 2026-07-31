#!/bin/bash
# Laura Monitoring Setup
# Installs periodic healthcheck and auto-repair

LAURA_HOME="/opt/laura"
MONITOR_INTERVAL=5  # minutes

# Install healthcheck cron
cat > /etc/cron.d/laura-healthcheck << 'CRON'
*/5 * * * * laura /opt/laura/.venv/bin/python -m shopee_agent.healthcheck_monitor --webhook https://hooks.example.com/laura-alerts 2>&1 | logger -t laura-healthcheck
CRON

# Install backup cron
cat > /etc/cron.d/laura-backup << 'CRON'
0 3 * * * laura /opt/laura/.venv/bin/python -m shopee_agent.backup --full --output /var/backups/laura --keep 7 2>&1 | logger -t laura-backup
CRON

echo "Monitoring installed: healthcheck every ${MONITOR_INTERVAL}min, backup daily at 3am"
