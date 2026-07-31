Annoy Operational Playbook
==========================

Purpose
-------
This playbook provides practical steps to operate the Annoy-backed vector store included in the project. It covers configuration, periodic reindexing, background build mode, and simple monitoring checks.

Environment variables (recommended)
----------------------------------
- `LAURA_VECTOR_BACKEND=annoy` — enable Annoy globally
- `LAURA_ANNOY_INDEX_PATH=reports/annoy_index.ann`
- `LAURA_ANNOY_META_PATH=reports/annoy_meta.json`
- `LAURA_VECTOR_DIM=128` — vector dimensionality (must match your embedder)
- `LAURA_ANNOY_BACKGROUND_BUILD=1` — enable background builder thread
- `LAURA_ANNOY_BUILD_INTERVAL=60` — builder interval in seconds

Basic CLI commands
------------------
- Reindex all outcomes into the sidecar (JSONL) or Annoy index:

```bash
.venv/bin/python -m shopee_agent.cli memory-reindex-vectors \
  --outcomes-path reports/decision_outcomes.jsonl \
  --vectors-path reports/decision_vectors.jsonl \
  --vector-backend annoy \
  --annoy-index-path reports/annoy_index.ann \
  --annoy-meta-path reports/annoy_meta.json
```

- Run semantic search (uses Annoy if configured):

```bash
.venv/bin/python -m shopee_agent.cli memory-semantic-search --text "consulta" --vector-backend annoy
```

Background build vs immediate build
----------------------------------
- Immediate build: `MemoryLayer.remember_outcome_with_vector` now calls the store's `_ensure_index()` and `_save_meta()` synchronously where available. This guarantees data is visible to queries immediately but can incur CPU cost.
- Background build: enable `LAURA_ANNOY_BACKGROUND_BUILD=1` to have the `AnnoyVectorStore` spawn a background thread that periodically builds and persists the index when new vectors are present. This reduces per-write latency.

Operational examples
--------------------

1) Systemd service that runs periodic reindex (batch rebuild): create `/etc/systemd/system/laura-annoy-reindex.service`:

```ini
[Unit]
Description=Laura Annoy Reindex
After=network.target

[Service]
Type=oneshot
User=laura
WorkingDirectory=/home/laura/agente
Environment=LAURA_VECTOR_BACKEND=annoy
Environment=LAURA_ANNOY_INDEX_PATH=/home/laura/agente/reports/annoy_index.ann
ExecStart=/home/laura/agente/.venv/bin/python -m shopee_agent.cli memory-reindex-vectors --outcomes-path reports/decision_outcomes.jsonl --vector-backend annoy --annoy-index-path reports/annoy_index.ann --annoy-meta-path reports/annoy_meta.json

[Install]
WantedBy=multi-user.target
```

Run once via: `systemctl start laura-annoy-reindex.service` or schedule with a timer.

2) Simple cron example (daily rebuild at 03:00):

```cron
0 3 * * * cd /home/laura/agente && .venv/bin/python -m shopee_agent.cli memory-reindex-vectors --outcomes-path reports/decision_outcomes.jsonl --vector-backend annoy --annoy-index-path reports/annoy_index.ann --annoy-meta-path reports/annoy_meta.json >> /var/log/laura/annoy_reindex.log 2>&1
```

Monitoring & quick checks
-------------------------
- Check index file exists:

```bash
ls -l reports/annoy_index.ann reports/annoy_meta.json
```

- Run a smoke search to validate queries:

```bash
.venv/bin/python -m shopee_agent.cli memory-semantic-search --text "test" --vector-backend annoy --top-k 3
```

- Verify the meta sidecar contains mapping:

```bash
python - <<'PY'
import json
print(json.load(open('reports/annoy_meta.json')))
PY
```

Performance notes
-----------------
- `n_trees` (parameter to `AnnoyVectorStore`) controls index build time vs query accuracy. Default in the adapter is 10; for larger datasets increase accordingly.
- Use background build mode on write-heavy systems to reduce write latency.
- Annoy index is memory-mapped when loaded, so ensure the host has sufficient RAM for the index.

When to prefer other backends
----------------------------
- For very large scale or distributed deployments, prefer Faiss (GPU/CPU optimizations), Weaviate, or Redis vector modules which provide sharding, persistence, and scaling.
