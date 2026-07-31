# Laura Store Analysis Service - Deployment Guide

## Overview

This document describes the setup, configuration, and deployment of Laura's LLM-driven store analysis service using Ollama.

## Components

### 1. System Prompts (`shopee_agent/prompts.py`)

Four specialized prompts for different analysis scenarios:

| Prompt Type | Purpose | Target Model | Max Tokens |
|---|---|---|---|
| `general_agent` | Store health + strategic decisions | mistral, llama2 | ~600 |
| `triage` | Quick prioritization | tinyllama | ~300 |
| `product_diagnosis` | Single SKU health check | mistral | ~400 |
| `daily_report` | Executive summary | llama2 | ~500 |

All prompts return JSON with structured fields for easy parsing.

### 2. CLI Command

```bash
python3 -m shopee_agent.cli store-analysis \
  --prompt-type {general_agent|triage|product_diagnosis|daily_report} \
  --model {tinyllama|mistral|llama2} \
  --days <number> \
  [--dry-run]
```

**Behavior:**
1. Fetches shop data from Shopee API (orders, products, inventory)
2. Passes data to selected LLM prompt
3. Parses JSON response
4. Stores result to `reports/store_analysis_<prompt_type>_<timestamp>.json`

**Dry-run mode:**
- Skips LLM call
- Shows raw input data
- Useful for debugging data collection

### 3. Automation Script (`scripts/laura_analysis_daily.sh`)

Wrapper script for scheduled execution:

```bash
# Basic usage
/home/shopee/agente/scripts/laura_analysis_daily.sh

# With environment overrides
PROMPT_TYPE=daily_report MODEL=llama2 DAYS=7 ./scripts/laura_analysis_daily.sh

# Dry-run mode
DRY_RUN=1 ./scripts/laura_analysis_daily.sh
```

**Features:**
- Loads `.env` configuration
- Logs to `logs/laura_analysis_*.log`
- Auto-cleanup of logs older than 30 days
- Exit code 0 on success, 1 on failure

### 4. Systemd Service & Timer

**Files:**
- `deploy/laura_analysis.service` - One-shot service definition
- `deploy/laura_analysis.timer` - Daily scheduler

**Installation:**

```bash
# Copy units to systemd directory
sudo cp deploy/laura_analysis.service /etc/systemd/system/
sudo cp deploy/laura_analysis.timer /etc/systemd/system/

# Reload systemd and enable
sudo systemctl daemon-reload
sudo systemctl enable laura_analysis.timer

# Start the timer
sudo systemctl start laura_analysis.timer

# Verify
systemctl status laura_analysis.timer
systemctl list-timers laura_analysis.timer
```

**Default Schedule:**
- **Time:** 04:30 UTC daily
- **Prompt Type:** `daily_report`
- **Model:** `mistral`
- **Days Window:** 1 day

**Customize via .env:**
```bash
# .env
PROMPT_TYPE=general_agent
LAURA_LLM_MODEL=llama2
DAYS=7
```

### 5. Configuration

**Environment Variables (.env):**
```bash
# Required (from .env or CLI --access-token / --shop-id)
SHOPEE_PARTNER_ID=xxx
SHOPEE_PARTNER_KEY=xxx
SHOPEE_DEFAULT_ACCESS_TOKEN=xxx
SHOPEE_DEFAULT_SHOP_ID=xxx

# Optional - LLM Configuration
LAURA_LLM_MODEL=mistral  # default model for analysis
OLLAMA_BASE_URL=http://127.0.0.1:11434  # Ollama endpoint

# Optional - Analysis Configuration
PROMPT_TYPE=general_agent  # used by scripts/laura_analysis_daily.sh
DAYS=1                     # analysis window
```

## Deployment Steps

### Step 1: Verify Ollama is Running

```bash
# Check if Ollama is listening
curl http://127.0.0.1:11434/api/tags

# Ensure your chosen model is installed
ollama list
ollama pull mistral  # if missing
```

### Step 2: Test CLI Command (Manual)

```bash
cd /home/shopee/agente

# Dry-run first
python3 -m shopee_agent.cli store-analysis \
  --prompt-type general_agent \
  --model mistral \
  --dry-run

# If dry-run succeeds and shows shop data, proceed to real execution
python3 -m shopee_agent.cli store-analysis \
  --prompt-type general_agent \
  --model mistral
```

### Step 3: Test Wrapper Script

```bash
# Test with dry-run
DRY_RUN=1 ./scripts/laura_analysis_daily.sh

# Full test with real LLM call
./scripts/laura_analysis_daily.sh

# Check output
cat logs/laura_analysis_*.log
cat reports/store_analysis_*.json
```

### Step 4: Deploy Systemd Service

```bash
# Copy files
sudo cp deploy/laura_analysis.{service,timer} /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable laura_analysis.timer

# Start
sudo systemctl start laura_analysis.timer

# Verify
systemctl status laura_analysis.timer
sudo journalctl -u laura_analysis -n 50
```

### Step 5: Monitor

```bash
# View next scheduled run
systemctl list-timers laura_analysis.timer

# Watch logs in real-time (after timer triggers)
sudo journalctl -u laura_analysis -f

# View analysis results
ls -la reports/store_analysis_*.json
jq . reports/store_analysis_*.json  # pretty-print latest
```

## Monitoring & Troubleshooting

### Common Issues

**Issue: "Failed to fetch data: HTTP error"**
- Likely cause: Invalid Shopee token or rate limiting
- Fix: Verify `.env` credentials and Shopee API rate limits

**Issue: "LLM analysis failed"**
- Check if Ollama is running: `curl http://127.0.0.1:11434/api/tags`
- Check if model is available: `ollama list`
- Pull model if missing: `ollama pull mistral`

**Issue: "Timeout waiting for LLM response"**
- Model might be overloaded or system CPU/RAM insufficient
- Try smaller model: tinyllama instead of mistral
- Check system resources: `free -h && nproc`

**Issue: "No such file or directory: .env"**
- Create `.env` file in project root with required credentials
- Ensure `SHOPEE_DEFAULT_SHOP_ID` and `SHOPEE_DEFAULT_ACCESS_TOKEN` are set

### Health Check

```bash
# Manual verification
python3 -m shopee_agent.cli store-analysis --prompt-type triage --days 1 --dry-run

# If outputs clean JSON-like structure with shop data, system is healthy

# Check recent analysis results
ls -lt reports/store_analysis_*.json | head -5
```

## Output Format

Each analysis result stored as JSON:

```json
{
  "input": {
    "shop_id": 1288767930,
    "generated_at": "2026-05-01T04:30:00+00:00",
    "orders_count": 150,
    "products_count": 45,
    "orders_sample": [...],
    "products_sample": [...]
  },
  "analysis": {
    "decision": "SCALE_WINNERS",
    "action": "scale_winners",
    "priority": "LOW",
    "mode": "dry_run",
    "metrics": {
      "margin_pct": 22.5,
      "roas": 4.2,
      "refund_rate_pct": 1.8,
      "order_volume": 150
    },
    "shop_status": "Healthy with strong margins",
    "alerts": [],
    "top_action": "Increase ad budget for top 5 products",
    "reasoning": "Store showing healthy margins and strong ROAS",
    "confidence": 0.85
  }
}
```

## Performance Characteristics

| Model | Latency | Memory | Accuracy |
|---|---|---|---|
| tinyllama | ~2-5s | ~400MB | Good for triage |
| mistral | ~5-10s | ~2GB | Good general purpose |
| llama2 | ~10-15s | ~3GB | Slower but detailed |

**Recommendation for daily jobs:**
- Use `mistral` for general_agent (good balance)
- Use `tinyllama` for triage on resource-constrained systems
- Use `llama2` when detailed analysis needed (schedule less frequently)

## Rollback

To disable daily analysis:

```bash
sudo systemctl stop laura_analysis.timer
sudo systemctl disable laura_analysis.timer
```

To revert code changes:
```bash
git checkout shopee_agent/prompts.py shopee_agent/cli.py
rm scripts/laura_analysis_daily.sh
rm deploy/laura_analysis.{service,timer}
```

## Next Steps

1. **Validate Results:** Check 1-2 analysis outputs to confirm JSON format
2. **Tune Prompts:** Adjust system prompts in `shopee_agent/prompts.py` based on response quality
3. **Add Alerts:** Integrate analysis results with notification system
4. **Scale:** Add additional prompt types for specific business needs (competitor monitoring, inventory optimization, etc.)
