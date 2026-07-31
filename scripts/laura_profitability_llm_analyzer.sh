#!/usr/bin/env bash
#
# laura_profitability_llm_analyzer.sh
# Integra LLM local (Ollama) ao pipeline de analise de profitabilidade
#
# Uso:
#   ./scripts/laura_profitability_llm_analyzer.sh [--metrics-file JSON] [--prompt-type TYPE] [--model MODEL] [--timeout-seconds N]
#
# Exemplos:
#   ./scripts/laura_profitability_llm_analyzer.sh
#   ./scripts/laura_profitability_llm_analyzer.sh --metrics-file reports/laura_profitability_inputs_latest.json
#   ./scripts/laura_profitability_llm_analyzer.sh --prompt-type refund_analyst
#   ./scripts/laura_profitability_llm_analyzer.sh --model mistral
#   ./scripts/laura_profitability_llm_analyzer.sh --timeout-seconds 5

set -euo pipefail

# ============================================================================
# Configuração
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
REPORTS_DIR="${REPO_ROOT}/reports"
LOGS_DIR="${REPO_ROOT}/logs"

# Arquivos
METRICS_FILE="${REPORTS_DIR}/laura_profitability_inputs_latest.json"
OUTPUT_FILE="${REPORTS_DIR}/laura_profitability_llm_latest.json"
LOG_FILE="${LOGS_DIR}/laura_profitability_llm_analyzer.log"

# Parametros
PROMPT_TYPE="profitability_analyzer"
MODEL="${LAURA_LLM_MODEL:-tinyllama}"
TIMEOUT_SECONDS="${LAURA_LLM_REQUEST_TIMEOUT_SECONDS:-}"
SHOW_HELP=0

# ============================================================================
# Funções
# ============================================================================

log() {
    local level="$1"
    shift
    local msg="$@"
    local ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${ts}] [${level}] ${msg}" | tee -a "$LOG_FILE"
}

error() {
    log "ERROR" "$@"
    return 1
}

info() {
    log "INFO" "$@"
}

usage() {
        cat <<'EOF'
Uso:
    ./scripts/laura_profitability_llm_analyzer.sh [--metrics-file JSON] [--prompt-type TYPE] [--model MODEL] [--timeout-seconds N]

Opcoes:
    --metrics-file PATH   Arquivo JSON de entrada (default: reports/laura_profitability_inputs_latest.json)
    --prompt-type TYPE    profitability_analyzer|refund_analyst|scaling_opportunity_finder|executive_summary
    --model MODEL         tinyllama|llama2|mistral|neural-chat|llama2:13b
    --timeout-seconds N   Timeout da inferencia (sobrescreve LAURA_LLM_REQUEST_TIMEOUT_SECONDS)
    -h, --help            Exibe esta ajuda
EOF
}

# Parse arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --metrics-file)
                METRICS_FILE="$2"
                shift 2
                ;;
            --prompt-type)
                PROMPT_TYPE="$2"
                shift 2
                ;;
            --model)
                MODEL="$2"
                shift 2
                ;;
            --timeout-seconds)
                TIMEOUT_SECONDS="$2"
                shift 2
                ;;
            -h|--help)
                usage
                SHOW_HELP=1
                return 0
                ;;
            *)
                error "Argumento desconhecido: $1"
                usage
                return 1
                ;;
        esac
    done
}

# ============================================================================
# Verificações Preliminares
# ============================================================================

check_dependencies() {
    # Verificar Python 3.10+
    if ! command -v python3 &> /dev/null; then
        error "python3 nao encontrado"
        return 1
    fi
    
    local py_version=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1-2)
    if (( $(echo "$py_version < 3.10" | bc -l) )); then
        error "Python 3.10+ necessario, encontrado: $py_version"
        return 1
    fi
    
    # Verificar requests (usado por llm_local.py)
    if ! python3 -c "import requests" 2>/dev/null; then
        error "Dependencia requests nao instalada. Execute: pip install -r requirements.txt"
        return 1
    fi
    
    info "Dependências OK"
}

check_input_file() {
    if [[ ! -f "$METRICS_FILE" ]]; then
        error "Arquivo de métricas não encontrado: $METRICS_FILE"
        return 1
    fi
    
    # Validar JSON
    if ! python3 -c "import json; json.load(open('$METRICS_FILE'))" 2>/dev/null; then
        error "Arquivo de métricas contém JSON inválido: $METRICS_FILE"
        return 1
    fi
    
    info "Arquivo de métricas validado: $METRICS_FILE"
}

main() {
    info "=== Laura LLM Analyzer (Ollama local) ==="
    
    # Parse arguments
    parse_args "$@"
    if [[ "$SHOW_HELP" -eq 1 ]]; then
        return 0
    fi
    
    # Verificações
    check_dependencies || return 1
    check_input_file || return 1

    # Carregar .env se existir
    if [[ -f "${REPO_ROOT}/.env" ]]; then
        set -a
        source "${REPO_ROOT}/.env"
        set +a
    fi

    # Executar analise local via CLI do projeto
    if [[ -n "$TIMEOUT_SECONDS" ]] && ! [[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] ; then
        error "--timeout-seconds deve ser inteiro positivo"
        return 1
    fi

    info "Iniciando analise LLM local (modelo=${MODEL}, prompt=${PROMPT_TYPE}, timeout=${TIMEOUT_SECONDS:-default})..."
    PY_CMD="${REPO_ROOT}/.venv/bin/python"
    if [[ ! -x "$PY_CMD" ]]; then
        PY_CMD="python3"
    fi
    (
        cd "$REPO_ROOT"
        cmd=(
            "$PY_CMD" -m shopee_agent.cli llm-analyze
            --metrics-file "$METRICS_FILE"
            --prompt-type "$PROMPT_TYPE"
            --output-file "$OUTPUT_FILE"
            --model "$MODEL"
        )
        if [[ -n "$TIMEOUT_SECONDS" ]]; then
            cmd+=(--timeout-seconds "$TIMEOUT_SECONDS")
        fi
        "${cmd[@]}"
    )
}

# Executar
main "$@"
