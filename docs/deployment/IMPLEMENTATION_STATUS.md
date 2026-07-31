# Implementation Status - Local LLM (Ollama)

Date: 2026-04-20
Status: Operational with resilient fallback enabled + MediaSpace full upload pipeline

## Executive summary

This project is running with local-only LLM integration via Ollama.
No external API key is required for LLM analysis.

MediaSpace video upload now has a complete end-to-end pipeline with:
- Individual CLI commands for init/upload-part/complete/result/wait-completion
- Automatic multipart chunking orchestration script
- Polling utility with configurable timeout and interval

The profitability LLM pipeline is protected by timeout + deterministic fallback,
so automation can keep running even when Ollama is slow or unavailable.

## Current architecture

- LLM provider: Ollama local HTTP API (`127.0.0.1:11434`)
- Default model: `tinyllama`
- Supported models:
  - `tinyllama`
  - `llama2`
  - `mistral`
  - `neural-chat`
  - `llama2:13b`
- Prompt source: `shopee_agent/prompts.py`
- Analyzer module: `shopee_agent/llm_local.py`
- CLI entrypoint: `python3 -m shopee_agent.cli llm-analyze`
- Wrapper script: `scripts/laura_profitability_llm_analyzer.sh`
- Shopee API gateway: `python3 -m shopee_agent.cli api-call`

## Shopee endpoint coverage

Laura now has a generic signed API gateway for Shopee Open API calls.
This means any developer endpoint can be invoked through the CLI as long as the path, method, and schema are provided.

Current first-class wrappers:

- `/api/v2/auth/token/get`
- `/api/v2/auth/access_token/get`
- `/api/v2/shop/get_shop_info`
- `/api/v2/product/get_item_list`
- `/api/v2/product/get_item_detail`
- `/api/v2/product/get_item_base_info`
- `/api/v2/product/get_item_variations`
- `/api/v2/order/get_order_list`
- `/api/v2/order/get_order_detail`
- `/api/v2/logistics/get_channel_list`
- `/api/v2/logistics/get_logistics_info`
- `/api/v2/logistics/get_tracking_number`
- `/api/v2/returns/get_return_list`
- `/api/v2/returns/get_return_detail`
- `/api/v2/payment/get_escrow_detail`
- `/api/v2/discount/get_discount_list`
- `/api/v2/voucher/get_voucher_list`
- `/api/v2/bundle_deal/get_bundle_deal_list`
- `/api/v2/add_on_deal/get_add_on_deal_list`
- `/api/v2/media_space/init_video_upload`
- `/api/v2/media_space/upload_video_part`
- `/api/v2/media_space/complete_video_upload`
- `/api/v2/media_space/get_video_upload_result`
- `/api/v2/media_space/wait_video_completion` (polling utility)

Generic support:

- `GET`, `POST`, `PUT`, `DELETE`
- optional `access_token` and `shop_id`
- JSON payload file
- JSON query params file
- optional output file for response persistence
- Consultable endpoint catalog via `python3 -m shopee_agent.cli api-endpoints`
- Consultable API family catalog via `python3 -m shopee_agent.cli api-families`

## Official API families recognized

- Product
- GlobalProduct
- MediaSpace
- Shop
- Order
- Logistics
- FirstMile
- Payment
- Discount
- Bundle Deal
- Returns
- Chat

## Reliability controls in place

- Request timeout from env:
  - `LAURA_LLM_REQUEST_TIMEOUT_SECONDS` (default: `15`)
- Per-run timeout override in CLI:
  - `--timeout-seconds`
- Absolute timeout guard using worker thread
- Deterministic fallback decision when LLM request/parse fails
- Fallback output saved in normal output artifact path

## Observability in place

- `doctor` command shows:
  - env file mode and secure flag
  - Ollama reachability
  - supported local models
  - latest LLM result model/fallback/age
- `scripts/laura_status.sh` includes section `[7] LLM local status`:
  - model, fallback flag, age, action, priority, confidence
  - explicit warning when latest result used fallback
- `scripts/laura_status.sh` includes section `[8] LLM baseline audit (24h)`:
  - posture, fallback rate, run counts, p95/avg latency
  - persistent alert guard state visibility

## Baseline alert guard in place

- Script: `scripts/laura_llm_baseline_alert.sh`
- Trigger source: `laura_profitability_llm_baseline_latest.json`
- Rule: alert when posture threshold is breached for N consecutive runs
- Default threshold: `ATTENTION`
- Default consecutive breaches: `2`
- Recovery notification when posture returns to safe zone
- Cron integration: hourly at minute `9` via `scripts/laura_reconcile_cron.sh`

## Validation snapshot (latest)

- Python syntax checks: passing (`py_compile`)
- Bash syntax checks: passing (`bash -n`)
- `doctor`: OK when `.env` mode is secure (`0o600`)
- `llm-analyze`: completes under forced short timeout using fallback
- LLM latest artifact is generated and readable:
  - `reports/laura_profitability_llm_latest.json`
- MediaSpace video upload pipeline: tested end-to-end (init->upload-part->complete->result)

## MediaSpace video upload orchestration

New automation layer for full-stack video upload:

- **Individual CLI commands** (all tested and working):
  - `media-video-init-upload`: initialize multipart session
  - `media-video-upload-part`: send single part (MD5 auto-calculated if omitted)
  - `media-video-complete-upload`: finalize with part list
  - `media-video-upload-result`: query transcoding status
  - `media-video-wait-completion`: polling utility with configurable timeout/interval

- **Orchestration script**: `scripts/laura_media_video_upload.sh`
  - Full automation: init -> split into chunks -> upload all parts -> complete -> wait
  - Configurable chunk size (default 5MB)
  - Automatic MD5 calculation per chunk
  - Structured JSON logging per phase
  - Exit code 0 on completion, 1 on errors
  - Continues polling on timeout (safe resumable state)

## Known runtime behavior

In this environment, native Ollama responses can be slow/intermittent.
When that happens, fallback is expected and treated as safe continuity mode.

MediaSpace video transcoding is asynchronous. Even after `complete_video_upload`, status remains `TRANSCODING` for several minutes. Use `media-video-wait-completion` or periodic polling to track progress.

## Operational guidance

1. Keep `.env` permission at `600`.
2. Keep kill switch / dry-run posture for autopilot until native Ollama latency stabilizes.
3. Monitor fallback frequency via `doctor --json` and `scripts/laura_status.sh`.
4. If fallback rate remains high, tune model or infrastructure (CPU/RAM) before enabling execution mode.
5. For video uploads, use the orchestration script for full automation or individual CLI commands for fine-grained control.

## LLM-Driven Store Analysis (NEW)

**Status:** ✅ Integrated into CLI and systemd scheduler

**New Components:**
- `shopee_agent/prompts.py`: Extended with 4 new system prompts for Ollama
  - `general_agent`: General store health + decision engine (margin, ROAS, refund_rate → action)
  - `triage`: Ultra-compact version for tinyllama (<400 tokens)
  - `product_diagnosis`: Single SKU health analysis (margin, refund rate, recommendation)
  - `daily_report`: Executive summary (status, highlights, action items)

- **CLI Command:** `python3 -m shopee_agent.cli store-analysis`
  - Arguments: `--prompt-type`, `--model`, `--days`, `--dry-run`
  - Supports all 4 prompt types; outputs JSON analysis to `reports/store_analysis_*.json`
  - Fetches real shop data (orders, products) via Shopee API before LLM analysis

- **Automation:** `scripts/laura_analysis_daily.sh`
  - Wrapper script for daily analysis execution
  - Configurable via environment: `PROMPT_TYPE`, `MODEL`, `DAYS`
  - Auto-cleanup of analysis logs (>30 days)

- **Scheduling:** `deploy/laura_analysis.service` + `deploy/laura_analysis.timer`
  - systemd timer runs analysis daily at 04:30 UTC
  - Random delay: 5 minutes (avoid thundering herd)
  - Persistent state: reschedules if system reboots

**Usage Examples:**
```bash
# Dry-run: see input data without calling LLM
python3 -m shopee_agent.cli store-analysis --prompt-type general_agent --dry-run

# Real analysis: fetch shop data + run general_agent prompt
python3 -m shopee_agent.cli store-analysis --prompt-type general_agent --model mistral

# Triage mode: ultra-compact analysis for tinyllama
python3 -m shopee_agent.cli store-analysis --prompt-type triage --model tinyllama

# Analyze past 7 days with product_diagnosis
python3 -m shopee_agent.cli store-analysis --prompt-type product_diagnosis --days 7
```

**Integration Notes:**
- LLM responses are expected to be JSON; non-JSON responses are logged as errors
- Analysis results stored with timestamp: `reports/store_analysis_<prompt_type>_<timestamp>.json`
- All commands support `--model` override (defaults to `LAURA_LLM_MODEL` env var or `mistral`)

## Next recommended step

1. Expand Shopee API endpoint coverage to include remaining undocumented endpoints.
2. Add cron-based health checks for MediaSpace uploads.
3. Monitor LLM analysis consistency; tune prompts based on response patterns.
4. Implement webhook integration for transcoding completion notifications.

- `--self-test`: Run the readiness check and emit a machine-readable self-test result (status, reason, UTC time) for CI/CD or monitoring integration.

