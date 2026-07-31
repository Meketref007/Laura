# Laura Store Management - Production Deployment Checklist

## Phase 1: Core Setup ✅

- [x] Product listing & detail queries
- [x] Order listing & detail queries  
- [x] Single-item stock/price updates
- [x] Batch CSV-driven updates
- [x] Chat message automation
- [x] Sales reporting

## Phase 2: Automation ✅

- [x] Report scheduling (cron + systemd)
- [x] Dry-run mode for safety
- [x] JSONL audit logging
- [x] Performance benchmarking
- [x] Store health monitoring

## Phase 3: Intelligence ✅

- [x] LLM prompts (4 types)
- [x] Real LLM integration
- [x] Fallback mode (graceful degradation)
- [x] Robust JSON parsing
- [x] Timeout handling (60s)

## Phase 4: Alerts ✅

- [x] Alert rules engine (6 rules)
- [x] Webhook integration (Slack, Discord, HTTP)
- [x] Alert history tracking
- [x] Cooldown mechanism
- [x] CLI management

---

## Pre-Deployment Checklist

### Configuration
- [ ] `.env` created with Shopee credentials
- [ ] Webhook URLs configured (Slack, Discord, etc)
- [ ] Ollama running and accessible
- [ ] LLM models downloaded (tinyllama, mistral, llama2)

### Testing
- [ ] All CLI commands tested with `--help`
- [ ] Dry-run tests executed successfully
- [ ] Alert generation verified with `alerts test`
- [ ] Webhook delivery tested
- [ ] Alert history accessible

### Security
- [ ] `.env` permissions set to 600
- [ ] No credentials in git
- [ ] HTTPS enforced for webhooks
- [ ] API tokens rotated

### Monitoring
- [ ] Systemd units created and enabled
- [ ] Journalctl access configured
- [ ] Log rotation setup
- [ ] Alert notification channels ready

---

## Deployment Steps

### 1. Environment Setup
```bash
cd /home/shopee/agente

# Create .env
cat > .env << 'DOTENV'
SHOPEE_PARTNER_ID=your_partner_id
SHOPEE_PARTNER_KEY=your_partner_key
SHOPEE_DEFAULT_ACCESS_TOKEN=your_token
SHOPEE_DEFAULT_SHOP_ID=your_shop_id
LAURA_LLM_MODEL=mistral
WEBHOOK_SLACK=https://hooks.slack.com/services/...
WEBHOOK_DISCORD=https://discordapp.com/api/webhooks/...
DOTENV

chmod 600 .env
```

### 2. Verify Ollama
```bash
# Check if running
curl http://127.0.0.1:11434/api/tags

# Pull models if needed
ollama pull tinyllama
ollama pull mistral
ollama pull llama2
```

### 3. Test CLI Commands
```bash
# Product operations
python3 -m shopee_agent.cli product-list --dry-run
python3 -m shopee_agent.cli product-set-stock --item-id 12345 --stock 100 --dry-run

# Analysis
python3 -m shopee_agent.cli store-analysis --prompt-type general_agent --dry-run

# Alerts
python3 -m shopee_agent.cli alerts config
python3 -m shopee_agent.cli alerts test
```

### 4. Deploy Systemd Services
```bash
# Copy service files
sudo cp deploy/laura_analysis.{service,timer} /etc/systemd/system/
sudo cp deploy/laura_reports.{service,timer} /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable laura_analysis.timer laura_reports.timer
sudo systemctl start laura_analysis.timer laura_reports.timer

# Verify
systemctl status laura_analysis.timer
systemctl list-timers
```

### 5. Monitor First Run
```bash
# Watch logs
sudo journalctl -u laura_analysis -f
sudo journalctl -u laura_reports -f

# Check results
ls -la reports/
jq . reports/store_analysis_*.json | head -20
jq . reports/laura_health_latest.json | head -20
```

### 6. Verify Alerts
```bash
# View alert history
python3 -m shopee_agent.cli alerts history

# Check alert log
tail -f reports/laura_alerts_history.jsonl
```

---

## Post-Deployment

### Daily Operations
```bash
# Check system health
python3 -m shopee_agent.cli store-health-report --dry-run

# View latest analysis
ls -lrt reports/store_analysis_*.json | tail -1

# Monitor alerts
python3 -m shopee_agent.cli alerts history --limit 50
```

### Troubleshooting
```bash
# Check Ollama
systemctl status ollama
ps aux | grep ollama

# Check system resources
free -h && nproc && df -h

# View detailed logs
sudo journalctl -u laura_analysis -n 100 --no-pager

# Test webhook manually
curl -X POST $WEBHOOK_SLACK -d '{"test": "alert"}'
```

### Maintenance
```bash
# Backup reports
tar -czf reports_backup_$(date +%Y%m%d).tar.gz reports/

# Cleanup old reports (kept by laura_reports_cron.sh)
find reports -name "*.json" -mtime +30 -delete

# Restart services
sudo systemctl restart laura_analysis.service
```

---

## Success Criteria

✅ All systems passing:
- [ ] CLI commands respond correctly
- [ ] Store analysis generates JSON
- [ ] Alerts fire on test rules
- [ ] Webhooks receive messages
- [ ] Systemd timers schedule correctly
- [ ] Logs accumulate without error
- [ ] Alert history grows
- [ ] No high CPU/memory usage

---

## Rollback Plan

If deployment has issues:

```bash
# Disable timers
sudo systemctl stop laura_analysis.timer
sudo systemctl stop laura_reports.timer
sudo systemctl disable laura_analysis.timer
sudo systemctl disable laura_reports.timer

# Remove service files
sudo rm /etc/systemd/system/laura_*.service
sudo rm /etc/systemd/system/laura_*.timer
sudo systemctl daemon-reload

# Check status
systemctl status laura_analysis.timer
```

---

**Status: READY FOR PRODUCTION DEPLOYMENT ✅**

Date: 2026-05-01
Version: 1.0 (14 phases complete)
