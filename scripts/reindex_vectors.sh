#!/usr/bin/env bash
# Helper script to reindex decision vectors and optionally apply configuration
# Usage:
#   ./scripts/reindex_vectors.sh --backend faiss --dim 128 --apply --service laura
#
set -euo pipefail

SCRIPT_NAME=$(basename "$0")
PYTHON_BIN=".venv_test/bin/python"

BACKEND="memory"
DIM=128
INDEX_PATH=""
META_PATH=""
APPLY=false
SERVICE=""
ANNOY_N_TREES=10

print_help() {
  cat <<EOF
$SCRIPT_NAME — Reindex decision vectors sidecar into chosen backend

Usage:
  $0 [--backend memory|annoy|faiss] [--dim N] [--index-path PATH] [--meta-path PATH] [--apply] [--service NAME]

Options:
  --backend       Backend to instantiate (memory, annoy, faiss)
  --dim           Vector dimensionality (default 128)
  --index-path    On-disk index path (for annoy/faiss)
  --meta-path     Meta sidecar path (for annoy/faiss)
  --apply         Persist backend config to reports/vector_backend_config.json
  --service       Service name to restart after reindex (optional)
  --annoy-n-trees n  Annoy `n_trees` value (default 10)
  -h, --help      Show this help and exit

Example:
  $0 --backend faiss --dim 128 --index-path /var/lib/laura/faiss.idx --meta-path /var/lib/laura/faiss.meta.json --apply --service laura
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      BACKEND="$2"; shift 2;;
    --dim)
      DIM="$2"; shift 2;;
    --index-path)
      INDEX_PATH="$2"; shift 2;;
    --meta-path)
      META_PATH="$2"; shift 2;;
    --apply)
      APPLY=true; shift 1;;
    --service)
      SERVICE="$2"; shift 2;;
    --annoy-n-trees)
      ANNOY_N_TREES="$2"; shift 2;;
    -h|--help)
      print_help; exit 0;;
    *)
      echo "Unknown arg: $1"; print_help; exit 1;;
  esac
done

echo "Reindexing vectors -> backend=${BACKEND}, dim=${DIM}, apply=${APPLY}"

CMD=("$PYTHON_BIN" -m shopee_agent.cli reindex-backend --backend "$BACKEND" --dim "$DIM")
if [[ -n "$INDEX_PATH" ]]; then
  CMD+=(--index-path "$INDEX_PATH")
fi
if [[ -n "$META_PATH" ]]; then
  CMD+=(--meta-path "$META_PATH")
fi
if [[ "$APPLY" = true ]]; then
  CMD+=(--apply)
fi
if [[ -n "$ANNOY_N_TREES" ]]; then
  CMD+=(--annoy-n-trees "$ANNOY_N_TREES")
fi

echo "Running: ${CMD[*]}"
"${CMD[@]}"

if [[ -n "$SERVICE" ]]; then
  echo "Restarting service: $SERVICE"
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl restart "$SERVICE" || echo "Failed to restart $SERVICE (you may need permissions)"
  else
    echo "systemctl not available; please restart $SERVICE manually"
  fi
fi

echo "Done."
