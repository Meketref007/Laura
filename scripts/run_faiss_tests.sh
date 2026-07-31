#!/usr/bin/env bash
set -euo pipefail

PY=python3

echo "Checking for faiss..."
if ! $PY -c 'import importlib,sys
try:
    importlib.import_module("faiss")
    print("FOUND")
except Exception:
    sys.exit(2)'
then
  echo "faiss not found in current Python environment." >&2
  echo "To run Faiss tests, install faiss-cpu (pip) or use conda:"
  echo "  pip install faiss-cpu"
  echo "  # or: conda install -c pytorch faiss-cpu"
  exit 0
fi

echo "Running faiss-specific tests..."
$PY -m pytest tests/test_vector_store_faiss.py -q || exit 1
echo "Faiss tests finished."
