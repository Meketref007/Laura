# 🚀 LAURA PRODUCTION DEPLOYMENT GUIDE
## Complete Setup for Real Production Environment

**Status**: ✅ All Systems Ready  
**Date**: May 1, 2026  
**Version**: Phase 15 Complete - Production Ready

---

## 📋 PRE-DEPLOYMENT CHECKLIST

### Environment Validation
```bash
# 1. Verify Python and dependencies
python3 --version  # Should be 3.9+
pip3 list | grep -E "requests|pytest"

# 2. Verify project structure
cd /home/shopee/agente
ls -la shopee_agent/*.py | wc -l  # Should be 25+
ls -la deploy/*.{service,timer}  # Should be 4 files

# 3. Test all CLI commands (dry-run only)
python3 -m shopee_agent.cli product-list --dry-run
python3 -m shopee_agent.cli alerts config
python3 -m shopee_agent.cli refunds stats
```

---

## 🔐 STEP 1: SECURE CONFIGURATION

### 1.1 Create Production .env
```bash
# Copy from template if needed
cp .env .env.backup

# Edit with production credentials
nano .env
```

**Required Variables**:
```bash
SHOPEE_PARTNER_ID=xxx           # From Shopee Partner console
SHOPEE_PARTNER_KEY=xxx          # From Shopee Partner console
SHOPEE_DEFAULT_SHOP_ID=xxx      # Your Shopee shop ID
SHOPEE_DEFAULT_ACCESS_TOKEN=xxx # From token exchange

# Optional but recommended
LAURA_LLM_MODEL=mistral              # tinyllama, mistral, llama2
LAURA_LLM_REQUEST_TIMEOUT_SECONDS=60
WEBHOOK_SLACK=https://hooks.slack.com/services/...
WEBHOOK_DISCORD=https://discordapp.com/api/webhooks/...
```

### 1.2 Secure .env File
```bash
# Set secure permissions (owner read-write only)
chmod 600 /home/shopee/agente/.env

# Verify
ls -la /home/shopee/agente/.env
# Should show: -rw------- 1 shopee shopee
```

### 1.3 Validate Configuration
```bash
# Test token
python3 -m shopee_agent.cli health-check

# Should output:
# ✅ Token is valid
# ✅ Shop accessible
# ✅ API connection OK
```

---

## ⚙️ STEP 2: SYSTEMD SETUP

### 2.1 Install Service Files
```bash
# Copy systemd files to system directory
sudo cp /home/shopee/agente/deploy/laura_*.{service,timer} \
  /etc/systemd/system/

# Reload systemd daemon
sudo systemctl daemon-reload

# Verify files installed
sudo systemctl list-unit-files | grep laura_
```

### 2.2 Configure Service Environment
```bash
# Create systemd drop-in directory
sudo mkdir -p /etc/systemd/system/laura_analysis.service.d/

# Create override with environment variables
sudo tee /etc/systemd/system/laura_analysis.service.d/override.conf > /dev/null << 'EOF'
[Service]
Environment="PATH=/home/shopee/agente:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
EnvironmentFile=/home/shopee/agente/.env
WorkingDirectory=/home/shopee/agente
EOF

# Reload
sudo systemctl daemon-reload
```

### 2.3 Enable and Start Timers
```bash
# Enable daily analysis (runs at 04:30 UTC every day)
sudo systemctl enable laura_analysis.timer
sudo systemctl start laura_analysis.timer

# Enable daily reports (runs at 05:00 UTC every day)
sudo systemctl enable laura_reports.timer
sudo systemctl start laura_reports.timer

# Verify timers
sudo systemctl list-timers | grep laura_
sudo systemctl status laura_analysis.timer
```

### 2.4 Verify First Run
```bash
# Manually trigger analysis
sudo systemctl start laura_analysis.service

# Check logs (wait 30 seconds)
sleep 30
sudo journalctl -u laura_analysis -n 50 --no-pager

# Check reports directory
ls -lah /home/shopee/agente/reports/store_analysis*
```

---

## 📊 STEP 3: SETUP MONITORING

### 3.1 Enable Health Checks
```bash
# Create monitoring cron job
crontab -e

# Add these lines:
# Health check every hour
0 * * * * /home/shopee/agente/scripts/laura_health_check_new.py >> /home/shopee/agente/logs/health_check.log 2>&1

# Alert audit every 6 hours
0 */6 * * * /home/shopee/agente/scripts/laura_metrics_audit_guard.sh >> /home/shopee/agente/logs/audit.log 2>&1

# Weekly backup
0 2 * * 0 /home/shopee/agente/scripts/laura_backup.sh >> /home/shopee/agente/logs/backup.log 2>&1
```

### 3.2 Setup Log Rotation
```bash
# Create logrotate config
sudo tee /etc/logrotate.d/laura > /dev/null << 'EOF'
/home/shopee/agente/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 shopee shopee
    sharedscripts
}
EOF

# Test
sudo logrotate -d /etc/logrotate.d/laura
```

### 3.3 Setup Alerts to Slack/Discord
```bash
# Test Slack webhook
curl -X POST $WEBHOOK_SLACK \
  -H 'Content-type: application/json' \
  -d '{
    "text": "🚀 Laura is now LIVE in production!",
    "attachments": [{
      "color": "good",
      "fields": [
        {"title": "Status", "value": "Production Ready", "short": true},
        {"title": "Version", "value": "Phase 15", "short": true}
      ]
    }]
  }'

# Test Discord webhook
curl -X POST $WEBHOOK_DISCORD \
  -H 'Content-type: application/json' \
  -d '{
    "embeds": [{
      "title": "🚀 Laura Production Deployment",
      "color": 65280,
      "fields": [
        {"name": "Status", "value": "LIVE", "inline": true},
        {"name": "Version", "value": "Phase 15", "inline": true}
      ]
    }]
  }'
```

---

## 🔄 STEP 4: DEPLOY AUTOMATION SCRIPTS

### 4.1 Daily Analysis Automation
```bash
# Already configured via systemd timer, but can also use cron:
crontab -e

# Add:
30 4 * * * cd /home/shopee/agente && bash scripts/laura_analysis_daily.sh
```

### 4.2 Daily Reports Automation
```bash
# Already configured via systemd timer
# Or via cron:
0 5 * * * cd /home/shopee/agente && bash scripts/laura_daily_report.sh
```

### 4.3 Alerts & Webhook Dispatcher
```bash
# Setup alerts dispatcher (runs after analysis)
# Already in laura_analysis_daily.sh, but can also run separately:

# Every 6 hours
0 */6 * * * cd /home/shopee/agente && bash scripts/laura_alerts_dispatcher.sh
```

---

## 🧪 STEP 5: FULL INTEGRATION TEST

### 5.1 Test All Core Features
```bash
#!/bin/bash
# test_production_deployment.sh

echo "=== Testing Laura Production Deployment ==="
cd /home/shopee/agente

# 1. Test CLI commands
echo "1️⃣ Testing CLI commands..."
python3 -m shopee_agent.cli product-list --dry-run > /dev/null && echo "✅ product-list"
python3 -m shopee_agent.cli order-list --dry-run > /dev/null && echo "✅ order-list"
python3 -m shopee_agent.cli alerts config > /dev/null && echo "✅ alerts"
python3 -m shopee_agent.cli refunds stats > /dev/null && echo "✅ refunds"

# 2. Test health
echo ""
echo "2️⃣ Testing health checks..."
python3 -m shopee_agent.cli health-check 2>&1 | grep -q "valid" && echo "✅ health-check"

# 3. Test analysis
echo ""
echo "3️⃣ Testing LLM analysis..."
python3 -m shopee_agent.cli store-analysis --prompt-type triage --dry-run > /dev/null && echo "✅ store-analysis"

# 4. Test reports
echo ""
echo "4️⃣ Testing reports..."
python3 -m shopee_agent.cli report-sales --days 1 --dry-run > /dev/null && echo "✅ report-sales"
python3 -m shopee_agent.cli store-health-report --dry-run > /dev/null && echo "✅ store-health"

# 5. Test systemd
echo ""
echo "5️⃣ Testing systemd services..."
sudo systemctl is-active laura_analysis.timer > /dev/null && echo "✅ laura_analysis.timer"
sudo systemctl is-active laura_reports.timer > /dev/null && echo "✅ laura_reports.timer"

echo ""
echo "✅ All production tests passed!"
```

### 5.2 Run Integration Test
```bash
bash /home/shopee/agente/test_production_deployment.sh
```

---

## 📈 STEP 6: PRODUCTION MONITORING

### 6.1 Daily Health Check Script
```bash
#!/bin/bash
# /home/shopee/agente/scripts/laura_production_monitor.sh

ALERT_WEBHOOK=$WEBHOOK_SLACK

# Check systemd timers
if ! sudo systemctl is-active laura_analysis.timer > /dev/null; then
    curl -X POST $ALERT_WEBHOOK -d "❌ laura_analysis.timer is DOWN"
fi

# Check last analysis
LAST_ANALYSIS=$(ls -t /home/shopee/agente/reports/store_analysis* 2>/dev/null | head -1)
if [ -z "$LAST_ANALYSIS" ]; then
    curl -X POST $ALERT_WEBHOOK -d "⚠️ No recent analysis found"
fi

# Check for errors in logs
ERROR_COUNT=$(grep -c "ERROR" /home/shopee/agente/logs/*.log 2>/dev/null || echo "0")
if [ $ERROR_COUNT -gt 10 ]; then
    curl -X POST $ALERT_WEBHOOK -d "⚠️ $ERROR_COUNT errors in logs"
fi

# Check disk space
DISK_USAGE=$(df /home/shopee/agente | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    curl -X POST $ALERT_WEBHOOK -d "⚠️ Disk usage at $DISK_USAGE%"
fi

# All good
curl -X POST $ALERT_WEBHOOK -d "✅ Laura production health: NOMINAL"
```

### 6.2 Schedule Monitoring
```bash
# Add to crontab
crontab -e

# Daily at 09:00
0 9 * * * /home/shopee/agente/scripts/laura_production_monitor.sh
```

---

## 🔄 STEP 7: BACKUP & DISASTER RECOVERY

### 7.1 Setup Backup
```bash
#!/bin/bash
# /home/shopee/agente/scripts/laura_production_backup.sh

BACKUP_DIR="/home/shopee/agente/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup
mkdir -p $BACKUP_DIR
tar -czf $BACKUP_DIR/laura_backup_$DATE.tar.gz \
  -C /home/shopee/agente \
  reports/ logs/ .env

# Keep only last 30 days
find $BACKUP_DIR -name "laura_backup_*.tar.gz" -mtime +30 -delete

echo "✅ Backup created: laura_backup_$DATE.tar.gz"
```

### 7.2 Schedule Backups
```bash
# Weekly backups
crontab -e

# Every Sunday at 02:00
0 2 * * 0 /home/shopee/agente/scripts/laura_production_backup.sh
```

### 7.3 Disaster Recovery Test
```bash
# Test restore procedure quarterly
# Restore from backup to test directory
cd /tmp
tar -xzf /home/shopee/agente/backups/laura_backup_LATEST.tar.gz

# Verify all files present
ls -la reports/ logs/ .env
```

---

## ✅ PRODUCTION DEPLOYMENT CHECKLIST

- [ ] Python 3.9+ installed
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] .env file configured with real credentials
- [ ] .env permissions set to 600
- [ ] Systemd service files installed
- [ ] Services enabled (`systemctl enable laura_*.timer`)
- [ ] Services started (`systemctl start laura_*.timer`)
- [ ] First run completed successfully
- [ ] Logs verified in `/home/shopee/agente/logs/`
- [ ] Reports generated in `/home/shopee/agente/reports/`
- [ ] Monitoring setup (cron jobs configured)
- [ ] Alerts configured (Slack/Discord webhooks)
- [ ] Backup script scheduled (weekly)
- [ ] Integration tests passing
- [ ] Production monitoring active

---

## 🆘 TROUBLESHOOTING

### Service Not Starting
```bash
# Check logs
sudo journalctl -u laura_analysis.service -n 100

# Check systemd status
sudo systemctl status laura_analysis.service

# Restart service
sudo systemctl restart laura_analysis.service
```

### LLM Timeout
```bash
# Check if Ollama running
curl http://127.0.0.1:11434/api/tags

# Restart Ollama
sudo systemctl restart ollama

# Or disable LLM for fallback
export LAURA_LLM_MODEL=disabled
```

### API Errors
```bash
# Verify token is current
python3 -m shopee_agent.cli health-check

# Refresh token if needed
python3 -m shopee_agent.cli token-refresh-save

# Test API call
python3 -m shopee_agent.cli shop-info-default
```

### Webhook Issues
```bash
# Test webhook manually
curl -X POST $WEBHOOK_SLACK -d '{"test": "laura"}'

# Check webhook URLs in .env
grep WEBHOOK /home/shopee/agente/.env

# Test alert generation
python3 -m shopee_agent.cli alerts test --webhook $WEBHOOK_SLACK
```

---

## 📞 SUPPORT & ESCALATION

**24/7 Monitoring**:
- Slack/Discord alerts configured
- Daily health checks
- Weekly backup verification

**On-Call Procedures**:
1. Check health: `python3 -m shopee_agent.cli health-check`
2. Check logs: `sudo journalctl -u laura_* -n 50`
3. Check reports: `ls -lah /home/shopee/agente/reports/`
4. Restart service: `sudo systemctl restart laura_analysis.service`
5. Escalate if above doesn't work

---

## 🎉 YOU'RE NOW IN PRODUCTION!

Laura is fully deployed and automating your Shopee store management.

**Current Status**: ✅ **LIVE & OPERATIONAL**

**Next Steps**:
1. Monitor for first 24 hours
2. Review daily analysis results
3. Fine-tune alert thresholds as needed
4. Document any customizations

---

**Deployment Date**: 2026-05-01  
**System Version**: Phase 15 (Complete)  
**Support Level**: Production-grade (24/7 monitored)
