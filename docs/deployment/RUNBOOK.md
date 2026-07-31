# RUNBOOK - Laura Production Emergency Procedures

**Last Updated:** 2026-04-20  
**Status:** Production Ready  
**Severity Levels:** Critical, High, Medium, Low

---

## 📋 Table of Contents

1. [Quick Reference](#quick-reference)
2. [Critical Issues](#critical-issues)
3. [Diagnostic Tools](#diagnostic-tools)
4. [Recovery Procedures](#recovery-procedures)
5. [Escalation](#escalation)

---

## Quick Reference

| Issue | Symptom | Recovery | Time |
|-------|---------|----------|------|
| Ollama Offline | LLM returns (fallback) | Restart Ollama | 2-5 min |
| API Auth Failed | `error: "auth_failed"` | Refresh token | 1 min |
| Rate Limited | Requests timing out | Check logs, wait | 5-60 sec |
| Shopee Down | All API calls 503/500 | Wait, check status.shopee.com | varies |
| Token Expired | `error: "invalid_access_token"` | Refresh token or OAuth flow | 2 min |
| Config Missing | `.env` not found | Restore from backup | 1 min |
| Disk Space | Log files truncated | Cleanup old logs | 5 min |

---

## Critical Issues

### 1. **Ollama Service Offline**

**Severity:** CRITICAL  
**Symptom:** All LLM analysis returns fallback, logging shows `[ERROR] LLM request error`  
**Time to Recover:** 2-5 minutes

**Diagnosis:**
```bash
laura doctor
# Look for: "Ollama reachable: FAIL"

# Or check directly:
curl -s http://127.0.0.1:11434/api/tags | head -1
# Should return JSON, not connection error
```

**Recovery Steps:**

1. **Check if Ollama is running:**
   ```bash
   ps aux | grep ollama
   ```

2. **Restart Ollama:**
   ```bash
   # Kill existing process
   pkill -f "ollama serve"
   sleep 2
   
   # Start in background
   ollama serve &
   
   # Wait for startup (check logs)
   for i in {1..30}; do 
     curl -s http://127.0.0.1:11434/api/tags && break
     sleep 1
   done
   ```

3. **Verify recovery:**
   ```bash
   laura doctor
   laura llm-analyze
   ```

**If issue persists:**
- Check system memory: `free -h` (Ollama needs 2-4GB free)
- Check disk space: `df -h` (need >1GB for models)
- Reinstall: `curl -fsSL https://ollama.ai/install.sh | sh`

---

### 2. **Shopee API Authentication Failed**

**Severity:** CRITICAL  
**Symptom:** API calls return `error: "auth_failed"` or `401 Unauthorized`  
**Time to Recover:** 1-5 minutes

**Diagnosis:**
```bash
# Check if tokens are configured:
grep -E "SHOPEE_DEFAULT_ACCESS_TOKEN|SHOPEE_DEFAULT_SHOP_ID" .env

# Check token validity:
laura shop-info 2>&1 | grep -i error
```

**Recovery Steps:**

1. **For expired access token (most common):**
   ```bash
   # Refresh using refresh token
   laura token-refresh-save
   
   # Verify:
   laura shop-info
   ```

2. **If refresh token also expired:**
   ```bash
   # Re-run OAuth flow
   laura auth-url
   # (Open URL in browser, authorize shop)
   
   # Get code from redirect
   laura token-get --code <CODE> --shop-id <SHOP_ID>
   
   # Save new tokens
   echo "SHOPEE_DEFAULT_ACCESS_TOKEN=<NEW_TOKEN>" >> .env
   echo "SHOPEE_DEFAULT_REFRESH_TOKEN=<NEW_REFRESH>" >> .env
   echo "SHOPEE_DEFAULT_SHOP_ID=<SHOP_ID>" >> .env
   
   # Verify
   laura shop-info
   ```

**Emergency credential restoration:**
```bash
# If .env is corrupted/lost:
ls -la .env.bak .env.example

# Restore from backup:
cp .env.bak .env
chmod 0600 .env

# Verify:
laura doctor
```

---

### 3. **Rate Limited by Shopee**

**Severity:** HIGH  
**Symptom:** Requests timeout with `[WARNING] Rate limit timeout`  
**Time to Recover:** 5-60 seconds (automatic)

**Diagnosis:**
```bash
# Check log file for rate limit warnings:
tail -20 logs/laura_operations.log | grep "rate_limit\|timeout"

# Check current rate limits:
python3 -c "
from shopee_agent.rate_limit import get_limiter
limiter = get_limiter()
status = limiter.get_status()
for ep in sorted(status.keys()):
    pct = status[ep]['fill_percentage']
    print(f'{ep}: {pct:.0f}% available')
"
```

**Recovery Steps:**

1. **Automatic recovery (built-in):**
   - Rate limiter waits up to 10 seconds per request
   - Jitter prevents synchronized thundering herd
   - Should resolve within 60 seconds

2. **Manual intervention if stuck:**
   ```bash
   # Check current rate limit status:
   python3 -c "from shopee_agent.rate_limit import get_limiter; print(get_limiter().get_status())"
   
   # Reset specific endpoint:
   python3 -c "
   from shopee_agent.rate_limit import get_limiter, RateLimitConfig
   limiter = get_limiter()
   # Re-initialize (resets buckets):
   limiter.set_limit('/api/v2/product/get_item_list', RateLimitConfig(100, 60))
   "
   
   # Or restart service (resets all limits)
   ```

**Prevention:**
- Avoid running multiple instances of Laura simultaneously
- Stagger bulk operations (don't run 10 requests in parallel)
- Check `logs/laura_operations.log` for patterns

---

### 4. **Shopee API Down (Shopee Incident)**

**Severity:** CRITICAL  
**Symptom:** All API calls return 500/503, `[ERROR] API request HTTP error`  
**Time to Recover:** Unknown (external service)

**Diagnosis:**
```bash
# Check Shopee status
curl -I https://partner.shopeemobile.com/api/v2/shop/get_shop_info

# Expected: HTTP 200 (even if auth fails)
# If 503: Shopee is down
# If timeout: Network issue or Shopee down

# Check your connection:
ping -c 3 8.8.8.8
nslookup partner.shopeemobile.com
```

**Recovery Steps:**

1. **If Shopee is down:**
   - Wait 5-30 minutes for recovery
   - Check Shopee status page: https://status.shopee.com
   - Check incident on Shopee Open API docs

2. **If network issue:**
   ```bash
   # Test connectivity:
   curl -v https://partner.shopeemobile.com 2>&1 | head -10
   
   # Check firewall:
   sudo iptables -L | grep 443
   
   # Check DNS:
   nslookup partner.shopeemobile.com
   ```

3. **Implement fallback:**
   - Laura already caches recent results in `reports/`
   - Read-only endpoints can use cached data
   - Check: `ls -la reports/laura_*.json`

**Note:** Manual intervention not recommended. This is an external issue.

---

### 5. **Configuration Missing or Corrupted**

**Severity:** CRITICAL  
**Symptom:** `[ERROR] Config load failed: Missing SHOPEE_PARTNER_ID`  
**Time to Recover:** 1-2 minutes

**Diagnosis:**
```bash
# Check .env file:
[ -f .env ] && echo ".env exists" || echo ".env missing"

# Check contents:
cat .env | head -5

# Validate:
laura doctor
```

**Recovery Steps:**

1. **Restore from backup:**
   ```bash
   # Backup exists?
   ls -la .env.bak .env.example
   
   # Restore:
   cp .env.example .env  # Use template
   # OR
   cp .env.bak .env      # Use last known-good
   
   # Edit to add actual credentials:
   nano .env
   ```

2. **Manual configuration:**
   ```bash
   # Create new .env:
   cat > .env << EOF
SHOPEE_PARTNER_ID=<your_partner_id>
SHOPEE_PARTNER_KEY=<your_partner_key>
SHOPEE_REDIRECT_URL=https://example.com/callback
SHOPEE_DEFAULT_SHOP_ID=<your_shop_id>
SHOPEE_DEFAULT_ACCESS_TOKEN=<your_token>
SHOPEE_DEFAULT_REFRESH_TOKEN=<your_refresh_token>
EOF
   
   # Secure permissions:
   chmod 0600 .env
   ```

3. **Verify:**
   ```bash
   laura doctor
   ```

**Important:** Never commit .env to git. Keep backups in secure location.

---

## Diagnostic Tools

### Quick Health Check
```bash
# Comprehensive diagnostics:
laura doctor

# Check all endpoints configured:
laura api-endpoints | grep -c "name"

# Test actual API call:
laura shop-info

# Check LLM:
laura llm-analyze
```

### Log Analysis
```bash
# View recent errors:
tail -100 logs/laura_operations.log | grep ERROR

# Count errors by type:
grep ERROR logs/laura_operations.log | jq -r '.message' | sort | uniq -c | sort -rn

# Monitor in real-time:
tail -f logs/laura_operations.log | grep -E "ERROR|WARNING|rate_limit"

# Parse JSON logs:
cat logs/laura_operations.log | python3 -m json.tool | less
```

### Performance Diagnostics
```bash
# Check request latencies:
cat logs/laura_operations.log | jq 'select(.elapsed_ms) | .elapsed_ms' | sort -n | tail -10

# Find slow endpoints:
grep "API request completed" logs/laura_operations.log | jq '{path, elapsed_ms}' | sort -k3 -rn | head -5

# Check retry patterns:
grep "Retry attempt" logs/laura_operations.log | wc -l
```

---

## Recovery Procedures

### Procedure 1: Full Service Restart
**Time:** 1-2 minutes

```bash
#!/bin/bash
set -e

echo "Stopping Laura..."
pkill -f "laura" || true
pkill -f "ollama" || true
sleep 2

echo "Restarting Ollama..."
ollama serve &
sleep 10

echo "Verifying services..."
laura doctor

echo "Service restarted"
```

### Procedure 2: Log Rotation & Cleanup
**Time:** 1-2 minutes  
**When:** Disk space low or logs growing too large

```bash
#!/bin/bash
set -e

# Backup current logs
tar -czf "logs/backup_$(date +%Y%m%d_%H%M%S).tar.gz" logs/*.log
ls -la logs/backup_*.tar.gz | tail -1

# Cleanup old logs (keep last 7 days)
find logs/ -name "*.log" -mtime +7 -delete
find logs/ -name "laura_*.json" -mtime +30 -delete

# Verify
du -sh logs/
```

### Procedure 3: Token Emergency Refresh
**Time:** 2-5 minutes  
**When:** Multiple "auth_failed" errors

```bash
#!/bin/bash
set -e

SHOP_ID=$(grep SHOPEE_DEFAULT_SHOP_ID .env | cut -d= -f2)
REFRESH=$(grep SHOPEE_DEFAULT_REFRESH_TOKEN .env | cut -d= -f2)

echo "Refreshing token for shop $SHOP_ID..."

# Call refresh endpoint
RESULT=$(laura token-refresh --refresh-token "$REFRESH" --shop-id "$SHOP_ID")

# Extract new tokens
NEW_TOKEN=$(echo "$RESULT" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
NEW_REFRESH=$(echo "$RESULT" | grep -o '"refresh_token":"[^"]*' | cut -d'"' -f4)

# Update .env
sed -i.bak "s/SHOPEE_DEFAULT_ACCESS_TOKEN=.*/SHOPEE_DEFAULT_ACCESS_TOKEN=$NEW_TOKEN/" .env
sed -i "s/SHOPEE_DEFAULT_REFRESH_TOKEN=.*/SHOPEE_DEFAULT_REFRESH_TOKEN=$NEW_REFRESH/" .env

echo "Tokens updated. Verifying..."
laura shop-info
echo "Success!"
```

---

## Escalation

### Internal Escalation Path

| Issue Level | Action | Owner | Contact |
|-------------|--------|-------|---------|
| **CRITICAL** (service down) | Page on-call engineer | Operations | +55 11 XXXX-XXXX |
| **HIGH** (degraded) | Notify team | Team Lead | team@company.com |
| **MEDIUM** (warnings) | Create ticket | Engineer | jira.company.com |
| **LOW** (info) | Log/monitor | Automation | N/A |

### External Escalation

**For Shopee API Issues:**
1. Check Shopee Open API documentation: https://open.shopee.com
2. Check status page: https://status.shopee.com
3. Contact Shopee support: support@shopee.com (include request_id from logs)

---

## Monitoring & Alerts

### Recommended Alerts

```bash
# Alert if Ollama offline for 5+ minutes
* * * * * laura doctor 2>&1 | grep -q "Ollama reachable: FAIL" && echo "ALERT: Ollama offline" | mail -s "Laura: Ollama Offline" ops@company.com

# Alert if error rate > 10% in last hour
0 * * * * grep ERROR logs/laura_operations.log | tail -360 | wc -l | awk '{if($1>36) print "ALERT: High error rate"}' | mail -s "Laura: High Errors" ops@company.com

# Alert if rate limit exceeded
* * * * * grep "rate_limit" logs/laura_operations.log | tail -5 | wc -l | awk '{if($1>3) print "ALERT: Rate limited"}' | mail -s "Laura: Rate Limited" ops@company.com
```

---

## FAQ

**Q: How do I check if Laura is healthy?**  
A: Run `laura doctor`. All fields should show "OK" or "YES".

**Q: My token expired. What do I do?**  
A: Run `laura token-refresh-save` to refresh automatically.

**Q: I see lots of (fallback) in the logs. Is this bad?**  
A: It means Ollama is slow/unavailable, but the system is still working with deterministic fallback. No action needed, but consider restarting Ollama if it's frequent.

**Q: How do I know if I'm being rate limited?**  
A: Check logs for `[WARNING] Rate limit timeout`. The system automatically waits, so you should not see failures.

**Q: Can I run multiple instances of Laura?**  
A: Not recommended. Use separate rate limit buckets per instance if you must.

---

## Related Documentation

- [README.md](README.md) - Setup and usage
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) - Architecture and features
- [OLLAMA_LOCAL_GUIDE.md](OLLAMA_LOCAL_GUIDE.md) - LLM details
- Shopee Open API: https://open.shopee.com/documents

---

**Last Updated:** 2026-04-20  
**Runbook Version:** 1.0  
**Status:** PRODUCTION READY
