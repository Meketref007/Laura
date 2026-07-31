Annoy Vector Backend
=====================

Overview
--------
This document explains how to use the Annoy-backed vector store included in the project.

Annoy provides a lightweight, persistent, approximate nearest-neighbor index suitable for local or small-scale production usage. The project includes `AnnoyVectorStore` (in `shopee_agent/vector_store_annoy.py`) and CLI support to build and query an Annoy index.

Prerequisites
-------------
- Python virtual environment with project dependencies installed.
- The `annoy` package must be available in the runtime environment. Install in your venv:

```bash
.venv/bin/python -m pip install annoy
```

Default files & parameters
--------------------------
- Annoy index path (default used by CLI): `reports/annoy_index.ann`
- Meta sidecar JSON (maps doc_id -> meta): `reports/annoy_meta.json`
- Default embedding dimensionality used by CLI: `128` (must match vectors written to the index)

CLI Usage
---------

1) Rebuild (reindex) outcomes into an Annoy index:

```bash
.venv/bin/python -m shopee_agent.cli memory-reindex-vectors \
  --outcomes-path reports/decision_outcomes.jsonl \
  --vector-backend annoy \
  --annoy-index-path reports/annoy_index.ann \
  --annoy-meta-path reports/annoy_meta.json
```

Use `--dry-run` to preview without writing files.

2) Run semantic search using the Annoy backend:

```bash
.venv/bin/python -m shopee_agent.cli memory-semantic-search \
  --text "meu texto de consulta" \
  --vector-backend annoy \
  --annoy-index-path reports/annoy_index.ann \
  --annoy-meta-path reports/annoy_meta.json \
  --top-k 5
```

Notes & tips
------------
- Dimensionality: Annoy indices require a fixed vector dimensionality. The CLI and code use 128 by default for deterministic fallback embeddings. If you use a custom embedder, ensure vectors have the same dimension.
- Sidecar metadata: The adapter writes a JSON sidecar (`annoy_meta.json`) that maps document IDs to metadata (rule_id and other attributes). Keep this sidecar with the index for best experience.
- Approximate search: Annoy is approximate and uses the angular metric by default. Scores are mapped to a 0..1-like similarity for display.
- Rebuilding: Reindexing will add vectors to the index and build trees; do this periodically or after batch imports.
- Fallback: If Annoy is unavailable, the CLI will fall back to the in-memory store for searches.

Programmatic usage
-------------------
Example: construct an `AnnoyVectorStore` and pass it to `MemoryLayer`:

```python
from shopee_agent.vector_store_annoy import AnnoyVectorStore
from shopee_agent.decision_memory import MemoryLayer

store = AnnoyVectorStore(dim=128, index_path='reports/annoy_index.ann', meta_path='reports/annoy_meta.json')
mem = MemoryLayer(path='reports/decision_outcomes.jsonl', vector_store=store)

# When outcomes are remembered with a `vector`, they will be indexed in Annoy.
```

When to use Annoy
------------------
- Local deployments that need persistent approximate nearest-neighbor search.
- Lightweight production usage where Faiss/Weaviate/Redis are not available yet.

Limitations
-----------
- Not intended for large-scale distributed production as-is. For larger scale, consider Faiss, Weaviate, or RedisVector.
