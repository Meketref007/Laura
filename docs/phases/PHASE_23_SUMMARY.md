# Fase 23 — Guard de Custo no llm.py

**Data de conclusão:** Mai 5, 2026 02:52 UTC  
**Status:** ✅ CONCLUÍDA

---

## Problema

**BUG-3 — Risco Financeiro:** `llm.py` importa e usa Anthropic Claude API (PAGA) sem proteção. Se qualquer script chamar esse módulo acidentalmente → cobrança automática.

**Risco:** Qualquer desenvolvedor ou script poderia fazer uma simples import e gerar custo.

---

## Solução Implementada

### 1. Guard no Topo de `llm.py` — [llm.py:14-21](../../shopee_agent/llm.py#L14-L21)

Adicionado após os imports (bloqueia no nível de módulo, antes de qualquer outro código):

```python
# GUARD: Prevent accidental use of paid LLM API without explicit opt-in
_allow_paid_llm = os.getenv("LAURA_ALLOW_PAID_LLM", "0")
if _allow_paid_llm != "1":
    raise RuntimeError(
        "llm.py uses Anthropic Claude API (PAID). "
        "To use free LLM, use llm_local.py (Ollama) instead. "
        "To explicitly enable paid API, set LAURA_ALLOW_PAID_LLM=1 in .env"
    )
```

**Comportamento:**
- ✅ Sem `LAURA_ALLOW_PAID_LLM`: levanta RuntimeError
- ✅ Com `LAURA_ALLOW_PAID_LLM=1`: carrega normalmente

### 2. Adicionar Variable ao `.env.example` — [.env.example:92-100](../../.env.example#L92-L100)

Nova seção de configuração com valor default seguro:

```bash
# ============================================================================
# LLM (Paid - Claude API) — DESABILITADO POR PADRÃO
# ============================================================================

# CUIDADO: llm.py usa Anthropic Claude API, que é PAGA.
# Para evitar custos acidentais, o módulo llm.py é bloqueado por padrão.
# Para habilitar (apenas se souber o que está fazendo):
#   LAURA_ALLOW_PAID_LLM=1
# Default: 0 (bloqueado — use Ollama local em vez disso)
LAURA_ALLOW_PAID_LLM=0
```

---

## Testes de Validação

### ✅ Teste 1: Guard bloqueia sem env var

```bash
$ .venv/bin/python3 -c "from shopee_agent import llm"

RuntimeError: llm.py uses Anthropic Claude API (PAID). 
To use free LLM, use llm_local.py (Ollama) instead. 
To explicitly enable paid API, set LAURA_ALLOW_PAID_LLM=1 in .env
```

### ✅ Teste 2: Guard permite com env var

```bash
$ LAURA_ALLOW_PAID_LLM=1 .venv/bin/python3 -c "from shopee_agent import llm; print('✅ llm.py carregado com sucesso quando LAURA_ALLOW_PAID_LLM=1')"

✅ llm.py carregado com sucesso quando LAURA_ALLOW_PAID_LLM=1
```

---

## Arquivos Modificados

| Arquivo | Alterações | Impacto |
|---|---|---|
| `shopee_agent/llm.py` | Adicionar guard (8 linhas) | Bloqueia import acidental |
| `.env.example` | Adicionar seção LLM Paid (11 linhas) | Documenta configuração |

**Total:** 19 linhas adicionadas, 0 linhas removidas

---

## BUG-3 Status

- ✅ **CORRIGIDO:** Módulo `llm.py` agora bloqueado por padrão
- ✅ **SEGURO:** Requer opt-in explícito (`LAURA_ALLOW_PAID_LLM=1`)
- ✅ **DOCUMENTADO:** Comentários claros no `.env.example`
- ✅ **TESTADO:** Guard funcionando em ambos os casos

---

## Política de Custo Zero — Atualizada

| Componente | Status | Garantia |
|---|---|---|
| Ollama local | ✅ Gratuito | Sempre ativo por padrão |
| llm.py (Claude) | 🔒 **Bloqueado** | Requer `LAURA_ALLOW_PAID_LLM=1` |
| Webhook tunnel | ✅ Gratuito | Cloudflare free |
| Telegram | ✅ Gratuito | API Bot grátis |

---

## Próximas Etapas

- **Fase 24** (🟡 MÉDIO): CI com GitHub Actions
- **Fase 25** (🟡 MÉDIO): Bot Telegram interativo

---

## Conclusão

- ✅ BUG-3 CORRIGIDO — Risco financeiro eliminado
- ✅ Projeto mantém garantia de custo ZERO
- ✅ Proteção no nível de módulo (impossível bypassed acidentalmente)
