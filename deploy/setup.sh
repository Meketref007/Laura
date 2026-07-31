#!/bin/bash
set -euo pipefail

LAURA_USER="${LAURA_USER:-laura}"
LAURA_GROUP="${LAURA_GROUP:-laura}"
LAURA_HOME="/opt/laura"
LAURA_LOG="/var/log/laura"
LAURA_BACKUP="/var/backups/laura"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Laura Production Setup ==="

# 1. Create user if not exists
if ! id -u "$LAURA_USER" &>/dev/null; then
    groupadd --system "$LAURA_GROUP"
    useradd --system --gid "$LAURA_GROUP" --home-dir "$LAURA_HOME" --shell /sbin/nologin "$LAURA_USER"
    echo "User $LAURA_USER created"
fi

# 2. Create directories
mkdir -p "$LAURA_HOME" "$LAURA_LOG" "$LAURA_BACKUP"
chown -R "$LAURA_USER:$LAURA_GROUP" "$LAURA_HOME" "$LAURA_LOG" "$LAURA_BACKUP"

# 3. Copy files
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='.git' "$SCRIPT_DIR/" "$LAURA_HOME/"
chown -R "$LAURA_USER:$LAURA_GROUP" "$LAURA_HOME"

# 4. Python virtual env
if [ ! -d "$LAURA_HOME/.venv" ]; then
    python3 -m venv "$LAURA_HOME/.venv"
    "$LAURA_HOME/.venv/bin/pip" install --upgrade pip setuptools wheel
fi
"$LAURA_HOME/.venv/bin/pip" install -e "$LAURA_HOME"

# 5. Environment file
if [ ! -f "$LAURA_HOME/.env" ]; then
    cp "$LAURA_HOME/.env.example" "$LAURA_HOME/.env" 2>/dev/null || true
    echo "Edit $LAURA_HOME/.env with your credentials"
fi

# 6. Systemd service
cp "$SCRIPT_DIR/deploy/laura.service" /etc/systemd/system/
systemctl daemon-reload

# 7. Log rotation
cat > /etc/logrotate.d/laura << 'LOGROTATE'
/var/log/laura/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LOGROTATE

# 8. Backup cron (daily at 3am)
cat > /etc/cron.d/laura-backup << 'CRON'
0 3 * * * laura /opt/laura/.venv/bin/python -m shopee_agent.backup --output /var/backups/laura --keep 7
CRON

# 9. Enable service
systemctl enable laura.service
systemctl start laura.service || echo "Check config: journalctl -u laura.service -n 50"

echo "=== Setup complete ==="
echo "  Service: systemctl status laura"
echo "  Logs: journalctl -u laura -f"
echo "  Config: $LAURA_HOME/.env"
echo ""
echo "Next: Set up nginx (see deploy/nginx.conf) and SSL via certbot"
