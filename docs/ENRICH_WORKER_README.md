# Decision Outcomes Enrichment Worker

This worker enriches `reports/decision_outcomes.jsonl` with realized impact metrics
derived from `reports/laura_profitability_history.jsonl`.

Installation (systemd)

1. Copy unit and timer:

```bash
sudo cp deploy/enrich_outcomes.service /etc/systemd/system/
sudo cp deploy/enrich_outcomes.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now enrich_outcomes.timer
```

2. Logs are emitted to `logs/enrich_outcomes.log` and `logs/enrich_outcomes.err`.

Manual run

```bash
/home/shopee/agente/.venv/bin/python -m shopee_agent.enrich_outcomes --hours 6
# or
/home/shopee/agente/scripts/run_enrich_outcomes.sh --hours 6
```

Notes

- The worker is intentionally conservative: it only enriches outcomes older than
  the configured lookback window and writes a full rewritten `reports/decision_outcomes.jsonl`.
- Phase 36 will replace this with an event-driven worker and incremental updates.

Status

- The wrapper writes a JSON status file to `reports/enrich_worker_status.json` after each run.
- Use the helper to read it:
  - Run: `.venv/bin/python -m shopee_agent.enrich_status`
  - Fields: `last_run`, `last_success`, `last_updated_count`, `last_error`
