**Vector Store CLI**

- **Purpose**: quick reference for `memory-reindex-vectors` and `memory-semantic-search` CLI commands used to build and query vector indices from decision outcomes.

- **Reindex (writes sidecar or indexes into Annoy/Faiss)**:
  - Usage: `laura memory-reindex-vectors --outcomes reports/decision_outcomes.jsonl --out reports/decision_vectors.jsonl --vector-backend memory`
  - Annoy: add `--vector-backend annoy --annoy-index-path path/to/index.ann --annoy-meta-path path/to/meta.jsonl`
  - Faiss: add `--vector-backend faiss --faiss-index-path path/to/faiss.idx --faiss-meta-path path/to/meta.json`
  - `--dry-run` skips writing index files but still writes `--out` when provided.

- **Semantic search (query existing vectors)**:
  - Usage: `laura memory-semantic-search --text "search terms" --vectors path/to/vectors.jsonl --vector-backend memory`
  - For Annoy/Faiss supply the index/meta paths via the corresponding flags.

- **Running tests locally**:
  - Create and activate test venv (optional):
    - `python -m venv .venv_test`
    - `source .venv_test/bin/activate`
  - Install minimal deps for tests:
    - `pip install -r requirements.txt pytest`
  - To run only vector-related tests:
    - `pytest tests/test_cli_reindex_end_to_end.py tests/test_cli_reindex_annoy.py tests/test_cli_reindex_faiss.py -q`
  - Optional: install `annoy` and `faiss-cpu` to enable full coverage:
    - `pip install annoy`
    - `pip install faiss-cpu` (or `pip install faiss-cpu==1.14.2`)

- **Notes for reviewers**:
  - Annoy/Faiss tests are written to skip when the optional packages are missing so CI remains fast and robust.
  - The `vector-tests` CI job in `.github/workflows/ci.yml` runs these tests and tries to install `faiss-cpu` only on the `faiss` matrix row.
