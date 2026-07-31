# Faiss Backend Playbook

This playbook explains how to enable and use the optional Faiss vector backend for local development and small deployments.

Note: `faiss` is an optional, system-level dependency and is not included in `requirements.txt` by default. Install it only on machines where you need Faiss-powered nearest-neighbour search.

## Installing Faiss (cpu)

Preferred (pip wheel on many Linux distros):

```bash
# inside your venv
pip install faiss-cpu
```

If `faiss-cpu` is not available for your platform, consider using conda:

```bash
conda install -c pytorch faiss-cpu
```

For GPU-enabled setups, install the appropriate `faiss-gpu` variant per Faiss docs.

## CLI: Reindexing outcomes into Faiss

Use the `memory-reindex-vectors` command to rebuild the vector sidecar and populate the Faiss index:

```bash
laura memory-reindex-vectors \
  --vector-backend faiss \
  --faiss-index-path reports/faiss_index.faiss \
  --faiss-meta-path reports/faiss_meta.json \
  --outcomes-path reports/decision_outcomes.jsonl \
  --vectors-path reports/decision_vectors.jsonl
```

After the command completes, the Faiss index file and meta sidecar will be written to the paths provided.

## CLI: Semantic search using Faiss

```bash
laura memory-semantic-search \
  --vector-backend faiss \
  --faiss-index-path reports/faiss_index.faiss \
  --faiss-meta-path reports/faiss_meta.json \
  --text "buscar por similaridade"
```

## Notes
- The adapter writes the Faiss index file and a small JSON meta sidecar mapping document ids to metadata.
- Tests for Faiss are skip-aware (they will skip if `faiss` is not importable in your environment).
- For reproducible tests, prefer using the deterministic `simple_text_to_vector` embedder in tests instead of external LLM embedders.

## Troubleshooting

If you run into issues installing `faiss-cpu` or importing `faiss`, try the following:

- Ensure build tools are available (on Debian/Ubuntu):

```bash
sudo apt update
sudo apt install -y build-essential cmake libopenblas-dev libomp-dev
```

- Prefer conda/mamba for binary wheels when possible:

```bash
conda create -n laura-test python=3.10 -y
conda activate laura-test
conda install -c pytorch faiss-cpu -y
```

- If you must use pip, use the pre-built wheel when available or install from PyPI:

```bash
pip install faiss-cpu
```

- Common errors:
  - "No module named 'faiss'" — the package was not installed in the active Python environment; check `python -m pip show faiss-cpu` and ensure you're using the same `python` that runs the tests.
  - Build fails with BLAS/OpenMP errors — install `libopenblas-dev` and `libomp-dev` before attempting pip build.

- If CI fails to find `mamba`, the workflow falls back to `conda` or pip; consider installing `mamba` for faster installs.

If you want, provide the `pip`/`conda` output and I can help diagnose the specific failure.

### Note on system-managed Python environments (PEP 668)

On some machines (notably images managed by the OS/package manager), `pip` will refuse to install packages system-wide and will show an "externally-managed-environment" error. In that case:

- Create and use a virtual environment for local development:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install faiss-cpu
```

- Or use conda/mamba as recommended above to install `faiss-cpu` into an isolated conda environment.

If you tried installing and saw the externally-managed error, creating a venv or using conda is the recommended next step.

## CI notes

- The repository CI uses a single canonical workflow at `.github/workflows/faiss-tests.yml`.
- The workflow uses `actions/setup-python@v4` with `python-version: '3.10'`, creates a local virtualenv, installs `faiss-cpu` with pip-first fallback logic, runs `tests/test_vector_store_faiss.py`, and uploads debug logs as artifacts (`faiss-ci-logs`) with `if: always()`.
- The same workflow supports `workflow_dispatch`, `pull_request` (to `main`), and temporary `push` triggers on `ci-trigger/*` branches for CI diagnostics.
- To reproduce the CI steps locally (recommended):

```bash
# create venv and install faiss via pip
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install faiss-cpu || pip install faiss-cpu==1.7.3

# install project
pip install -r requirements.txt
pip install -e .

# run only the Faiss test
python -m pytest tests/test_vector_store_faiss.py -q
```

- If CI still fails on the runner, collect the workflow logs (Actions -> run -> download logs) and share them; the logs we added to the pipeline include the pip/conda install output and an import check for `faiss` to speed diagnosis.
- If CI still fails on the runner, collect the workflow logs and download the `faiss-ci-logs` artifact from the run; it contains environment/import output and test output files used for diagnosis.
