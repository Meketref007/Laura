#!/usr/bin/env bash
#
# laura_llm_integration_check.sh
# Verifica se a integracao LLM local (Ollama) esta corretamente configurada
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "╔════════════════════════════════════════════════════════════╗"
echo "║    Laura LLM Integration Check (Ollama Local)             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# ============================================================================
# Verificações
# ============================================================================

CHECKS_PASSED=0
CHECKS_FAILED=0

check() {
    local name=$1
    local command=$2
    
    echo -n "[$name] ... "
    
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        ((CHECKS_PASSED+=1))
    else
        echo -e "${RED}✗${NC}"
        ((CHECKS_FAILED+=1))
    fi
}

# 1. Python
echo "📦 Dependências Python"
check "Python 3.10+" "python3 --version | grep -E '3\.(10|11|12|13)'"

# 2. Arquivos necessários
echo
echo "📁 Arquivos Criados"
check "shopee_agent/prompts.py" "[[ -f '$REPO_ROOT/shopee_agent/prompts.py' ]]"
check "shopee_agent/llm_local.py" "[[ -f '$REPO_ROOT/shopee_agent/llm_local.py' ]]"
check "scripts/laura_profitability_llm_analyzer.sh" "[[ -f '$REPO_ROOT/scripts/laura_profitability_llm_analyzer.sh' ]]"
check "OLLAMA_LOCAL_GUIDE.md" "[[ -f '$REPO_ROOT/OLLAMA_LOCAL_GUIDE.md' ]]"

# 3. Sintaxe Python
echo
echo "🐍 Validação de Sintaxe Python"
check "prompts.py" "python3 -m py_compile '$REPO_ROOT/shopee_agent/prompts.py'"
check "llm_local.py" "python3 -m py_compile '$REPO_ROOT/shopee_agent/llm_local.py'"

# 4. Sintaxe Bash
echo
echo "🔧 Validação de Sintaxe Bash"
check "laura_profitability_llm_analyzer.sh" "bash -n '$REPO_ROOT/scripts/laura_profitability_llm_analyzer.sh'"

# 5. Estrutura do projeto
echo
echo "🏗️  Estrutura do Projeto"
check "reports/ directory" "[[ -d '$REPO_ROOT/reports' ]]"
check "logs/ directory" "[[ -d '$REPO_ROOT/logs' ]]"
check "scripts/ directory" "[[ -d '$REPO_ROOT/scripts' ]]"

# 6. Configuração .env
echo
echo "⚙️  Configuração"
check ".env.example com config Ollama" "grep -q 'LAURA_OLLAMA_HOST' '$REPO_ROOT/.env.example'"

# 7. Documentação
echo
echo "📖 Documentação"
check "README.md com seção LLM local" "grep -q 'LLM Local (Ollama' '$REPO_ROOT/README.md'"
check "Sistema prompt profitabilidade" "grep -q 'SYSTEM_PROMPT_PROFITABILITY_ANALYZER' '$REPO_ROOT/shopee_agent/prompts.py'"
check "Sistema prompt reembolsos" "grep -q 'SYSTEM_PROMPT_REFUND_ANALYST' '$REPO_ROOT/shopee_agent/prompts.py'"
check "Sistema prompt oportunidades" "grep -q 'SYSTEM_PROMPT_SCALING_OPPORTUNITY_FINDER' '$REPO_ROOT/shopee_agent/prompts.py'"
check "Sistema prompt executivo" "grep -q 'SYSTEM_PROMPT_EXECUTIVE_SUMMARY' '$REPO_ROOT/shopee_agent/prompts.py'"

# 8. Importações no CLI
echo
echo "🔗 Integração CLI"
check "CLI imports LLM local" "grep -q 'from .llm_local import' '$REPO_ROOT/shopee_agent/cli.py'"
check "CLI imports prompts" "grep -q 'from .prompts import' '$REPO_ROOT/shopee_agent/cli.py'"
check "CLI comando llm-analyze" "grep -q 'llm-analyze' '$REPO_ROOT/shopee_agent/cli.py'"
check "CLI comando llm-prompts" "grep -q 'llm-prompts' '$REPO_ROOT/shopee_agent/cli.py'"

# 9. Requirements.txt
echo
echo "📋 Dependências"
check "requests em requirements.txt" "grep -q '^requests' '$REPO_ROOT/requirements.txt'"

# ============================================================================
# Resumo
# ============================================================================

echo
echo "╔════════════════════════════════════════════════════════════╗"
TOTAL=$((CHECKS_PASSED + CHECKS_FAILED))
PERCENTAGE=$((CHECKS_PASSED * 100 / TOTAL))

if [[ $CHECKS_FAILED -eq 0 ]]; then
    echo -e "║ ${GREEN}✓ TODOS OS TESTES PASSARAM!${NC}"
    echo -e "║ ${GREEN}Integracao Ollama local esta pronta para usar${NC}           ║"
else
    echo "║ Status: $CHECKS_PASSED/$TOTAL verificações"
    echo "║ Sucesso: $PERCENTAGE%"
fi
echo "╚════════════════════════════════════════════════════════════╝"

echo
echo "📝 Próximos Passos:"
echo

echo "  1. Instalar Ollama (se ainda nao instalado):"
echo "     curl -fsSL https://ollama.ai/install.sh | sh"
echo

echo "  2. Instalar dependencias Python:"
echo "     python3 -m venv .venv"
echo "     source .venv/bin/activate"
echo "     pip install -r requirements.txt"
echo
echo "  3. Testar integração:"
echo "     source .venv/bin/activate"
echo "     laura llm-prompts"
echo "     laura llm-analyze"
echo
echo "  4. Ver documentação:"
echo "     cat OLLAMA_LOCAL_GUIDE.md"
echo

if [[ $CHECKS_FAILED -eq 0 ]]; then
    exit 0
else
    exit 1
fi
