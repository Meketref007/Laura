# 24H Go-Live Checklist

Use this checklist before leaving Laura running continuously in production.

## 1. Configuration

- `.env` exists and has the real Shopee credentials.
- `.env` permissions are `600`.
- Webhook URLs are configured if alert delivery is required.
- The local Ollama service is reachable.

Run:

```bash
laura doctor
laura health-check
```

## 2. Services and timers

- `laura_analysis.timer` is enabled and active.
- `laura_reports.timer` is enabled and active.
- The next run times look correct.

Run:

```bash
systemctl list-timers | grep laura_
systemctl status laura_analysis.timer laura_reports.timer
```

## 3. Alerts

- Alert config loads without errors.
- A test alert can be generated.
- Alert history is being written.

Run:

```bash
laura alerts config
laura alerts test
laura alerts history --limit 20
```

## 4. LLM / Insights

- `laura llm-prompts` works.
- `laura llm-analyze --model tinyllama` returns either a real answer or a controlled fallback.
- The command does not block beyond the configured timeout.

Run:

```bash
laura llm-prompts
laura llm-analyze --model tinyllama
```

## 5. First 24h observation

- Watch `logs/laura_operations.log` for errors.
- Watch `reports/` for fresh output files.
- Confirm `systemctl list-timers` continues to advance.
- Confirm no repeated fallback or auth failures.

Run:

```bash
tail -f logs/laura_operations.log
tail -f reports/laura_alerts_history.jsonl
```

## 6. Exit criteria

Laura can be considered stable for 24h operation when all of the following are true:

- No auth failures.
- No repeated Ollama timeouts beyond the configured limit.
- Timers run at least once successfully.
- Alert history grows as expected.
- Logs remain free of repeated critical errors.
