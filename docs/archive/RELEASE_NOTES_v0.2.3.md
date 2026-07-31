Release v0.2.3
=================

Summary
-------
This release adds optional Faiss support as an alternative vector backend to Annoy and InMemory stores. It includes the Faiss adapter, CLI wiring, documentation, test helpers, and CI automation to run Faiss tests.

Highlights
----------
- `shopee_agent/vector_store_faiss.py`: New Faiss-backed adapter that persists the Faiss index and a JSON meta sidecar mapping document IDs to metadata. The adapter attempts to load existing index and meta on initialization and persists on `index()`.
- `shopee_agent/cli.py`: Extended CLI flags to accept `--vector-backend faiss` and `--faiss-index-path/--faiss-meta-path` to select and configure the Faiss backend for `memory-semantic-search` and `memory-reindex-vectors`.
- `docs/FAISS_PLAYBOOK.md`: New playbook with installation instructions (`conda`/`pip`), CLI examples, and troubleshooting (including guidance for PEP 668 "externally-managed" environments).
- `scripts/run_faiss_tests.sh` and `Makefile:test-faiss`: Helpers to run Faiss-specific tests locally.
- `.github/workflows/faiss-tests.yml`: Optional GitHub Actions job that sets up a conda environment, installs `faiss-cpu` (prefers mamba/conda), falls back to `pip install faiss-cpu` if needed, and runs Faiss tests.

Developer notes
---------------
- Faiss is an optional dependency. Tests are skip-aware when `faiss` is not installed.
- For local development, prefer creating a virtualenv or conda env before installing `faiss-cpu`.

Upgrade notes
-------------
No breaking changes. If you plan to use Faiss in production, ensure the environment has matching binary compatibility (manylinux / system BLAS) or use conda/mamba for reliable installs.
