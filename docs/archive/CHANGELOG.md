# Changelog

## v0.2.2 - 2026-05-23

### Added
- Annoy-backed vector store adapter (`shopee_agent/vector_store_annoy.py`) with optional background build.
- CLI support for semantic memory using vector backends: `memory-semantic-search` and `memory-reindex-vectors` (choose `memory` or `annoy`).
- Operational playbook for Annoy (`docs/ANNoy_PLAYBOOK.md`) and configuration via environment variables.

### Changed
- `MemoryLayer.remember_outcome_with_vector` now persists vectors and triggers index build for immediate availability.
- `shopee_agent/config.py` exposes vector backend configuration (`LAURA_VECTOR_BACKEND`, `LAURA_ANNOY_*`).

### Notes
- Added unit/integration tests for Annoy integration; full test suite verified locally.

## v0.2.0 - 2026-05-23

### Added
- Phase 35: Memory & Learning Layer
  - Implemented `DecisionOutcome` dataclass and `MemoryLayer` backed by JSONL (`shopee_agent/decision_memory.py`).
  - CLI commands to inspect and manage decision memory (`shopee_agent/decision_cli.py` and wiring in `shopee_agent/cli.py`).
- Gmail OAuth helper persisted tokens to `secrets/gmail_tokens_laura.json` (already present in workspace).

### Changed
- Hardened LLM local wrapper and JSON parsing in `shopee_agent/llm_local.py`.
- Made `healthcheck_service` deterministic for `products_count` and improved notification formatting.

### Fixed
- Test stability improvements and deterministic healthcheck logic.

### Notes
- CI: full test suite passed locally (244 tests). Recommended to run CI pipeline on remote.

## v0.2.3 - 2026-05-23

### Added
- Optional Faiss-backed vector store adapter (`shopee_agent/vector_store_faiss.py`) with index and meta persistence.
- CLI support for `faiss` backend in `memory-semantic-search` and `memory-reindex-vectors` (flags: `--vector-backend faiss`, `--faiss-index-path`, `--faiss-meta-path`).
- Documentation: `docs/FAISS_PLAYBOOK.md` with install, CLI examples and troubleshooting (PEP 668 note).
- Developer helpers: `scripts/run_faiss_tests.sh` and `Makefile` target `test-faiss` to run Faiss-specific tests.
- CI: GitHub Actions workflow `.github/workflows/faiss-tests.yml` to run Faiss tests in a conda environment (with pip fallback).

### Changed
- `README.md` updated with badge and instructions for Faiss tests.

### Notes
- Faiss tests pass locally in an isolated virtualenv; the CI workflow attempts conda install and falls back to `pip install faiss-cpu`.
- Release `v0.2.3` created and pushed.

## v0.2.4 - 2026-05-24

### Added
- Integrate `DecisionExecutor` with `DecisionEngine` to persist executed decisions into the `MemoryLayer` (including vector indexing) (`shopee_agent/decision_integration.py`).
- Integration test `tests/test_decision_executor_integration.py` verifying executor → engine → memory → vector indexing flow.
- Phase 36 documentation: `docs/PHASE_36_DECISION_MEMORY.md` describing the integration and CLI examples.

### Changed
- Decision execution path now notifies the engine to create `DecisionOutcome` entries, enabling semantic memory indexing and search via existing CLI tools.

### Notes
- PR opened: `phase36/decision-memory-integration` (includes code + tests). Run full CI to validate on remote.

## v0.2.5 - 2026-05-26

### Added
- CLI end-to-end tests for vector reindexing: InMemory, Annoy and Faiss (`tests/test_cli_reindex_end_to_end.py`, `tests/test_cli_reindex_annoy.py`, `tests/test_cli_reindex_faiss.py`).
- CI: `vector-tests` job added with a matrix row to attempt `faiss-cpu` installation; artifacts (Faiss/Annoy indices, meta, and reports) uploaded when present.
- Documentation: `docs/VECTOR_STORE_CLI.md` added with CLI usage and local test instructions.

### Changed
- Vector store tests now skip gracefully when optional dependencies (`annoy`, `faiss`) are not present to keep CI robust.

### Notes
- All new vector-related tests pass locally in `.venv_test` after installing optional deps; CI will attempt Faiss install only on the `faiss` matrix row.
