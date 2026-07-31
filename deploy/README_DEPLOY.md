Deployment instructions: scheduling `laura` reports
===============================================

This folder contains example `systemd` unit and timer files to schedule daily sales reports.

Files
- `laura_reports.service`: systemd service unit that runs `scripts/laura_reports_cron.sh`.
- `laura_reports.timer`: systemd timer that triggers the service daily with a randomized delay.

Quick `systemd` install (example):

1. Copy files to `/etc/systemd/system/` (requires root):

```bash
sudo cp deploy/laura_reports.service /etc/systemd/system/
sudo cp deploy/laura_reports.timer /etc/systemd/system/
```

2. Edit `/etc/systemd/system/laura_reports.service` and set `User=`/`Group=` if you do not want it to run as root.

3. Reload systemd and enable timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now laura_reports.timer
sudo systemctl status laura_reports.timer
```

Crontab alternative
-------------------
If you prefer `cron`, add a line for the desired schedule (example: daily at 03:00):

```cron
# Run daily report at 03:00; adjust PATH and environment as needed
0 3 * * * cd /home/shopee/agente && DRY_RUN=0 ./scripts/laura_reports_cron.sh >> /home/shopee/agente/logs/laura_reports.log 2>&1
```

For the autonomous loop introduced in phase 31, add a 15-minute schedule and keep shipping gated by Telegram approval:

```cron
*/15 * * * * cd /home/shopee/agente && source .venv/bin/activate && python3 -m shopee_agent.cli autonomous-loop >> /home/shopee/agente/logs/laura_autonomous.log 2>&1
```

If you need to force shipping manually, use the CLI directly or the Telegram command `/enviar_<order_sn>` after verifying the order.

Security and environment
------------------------
- Ensure `.env` exists in the repo root with required Shopee tokens and that file permissions are restricted (owner-only). Example:

```bash
chmod 600 .env
```

- For production, prefer running the service under a dedicated low-privilege user (set `User=` in the service file).

Retention and logs
------------------
- The script prunes old `reports/sales_report_*.json` files older than `RETENTION_DAYS` (default 90). Adjust that environment variable in your deployment if needed.
- Logs are written to `reports/` and the cron wrapper can be redirected to a log file as shown above.

Testing
-------
- Test without making API calls using dry-run:

```bash
python3 -m shopee_agent.cli report-sales --days 7 --dry-run
```

```bash
DRY_RUN=1 bash scripts/laura_reports_cron.sh
```

Support
-------
If you want, I can also generate a `systemd` user unit variant, a Kubernetes CronJob manifest, or a GitHub Actions workflow to run reports.
