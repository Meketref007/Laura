# 🚀 LLM 100% Local com Ollama (Sem API Externa!)

## Resiliencia (Fallback Automatico)

Se o Ollama ficar lento, indisponivel ou retornar resposta invalida, a Laura aplica
fallback heuristico deterministico para manter o pipeline funcionando em `dry_run`.

- Mantem o mesmo formato de saida JSON
- Marca o campo `model` com sufixo `(fallback)`
- Registra a causa tecnica no campo `reasoning`

## Por que Ollama?

✅ **Totalmente Local**: Roda na sua máquina, 0 dependências externas  
✅ **Grátis**: Open source, sem custos  
✅ **Privado**: Dados nunca saem do seu computador  
✅ **Offline**: Funciona sem internet  
✅ **Rápido**: Modelos 7B rodam em qualquer máquina moderna  

---

## 📦 Instalação (3 passos)

### Passo 1: Instalar Ollama

```bash
# Linux/Mac
curl -fsSL https://ollama.ai/install.sh | sh

# Windows
# Baixar em: https://ollama.ai/download
```

### Passo 2: Instalar dependências Python

```bash
cd /home/shopee/agente
pip install -r requirements.txt
pip install -e .
```

### Passo 3: Pronto!

Não há chaves API, não há configuração. Tudo local!

---

## 🎯 Usar

### Via CLI

```bash
# Listar modelos disponíveis
laura llm-prompts

# Analise com modelo padrao (tinyllama)
laura llm-analyze

# Análise com Mistral (mais rápido)
laura llm-analyze --model mistral

# Com arquivo customizado
laura llm-analyze --metrics-file reports/metricas.json

# Análise especializada
laura llm-analyze --prompt-type refund_analyst

# Teste de integração
laura llm-analyze --self-test
```

### Via Python

```python
from shopee_agent.llm_local import create_analyzer

# Criar analisador
analyzer = create_analyzer(model="tinyllama")

# Preparar métricas
metrics = {
    "revenue": 50000.00,
    "cogs": 15000.00,
    "ad_spend": 5000.00,
    "shipping_subsidy": 2000.00,
    "refunds": 500.00,
    "orders": 150
}

# Executar análise
result = analyzer.analyze_profitability(metrics=metrics)

# Ver resultado
print(f"Decisão: {result.decision}")
print(f"Tempo: {result.inference_time_ms}ms")
print(f"Reasoning: {result.reasoning}")
```

### Via Script Bash

```bash
./scripts/laura_profitability_llm_analyzer.sh --model tinyllama
./scripts/laura_profitability_llm_analyzer.sh --model mistral
```

---

## 📊 Modelos Disponíveis

| Modelo | Tamanho | RAM Mín | Velocidade | Qualidade |
|--------|---------|---------|-----------|-----------|
| **tinyllama** | 1.1B | 2GB | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| **llama2** | 7B | 8GB | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **mistral** | 7B | 8GB | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **neural-chat** | 7B | 8GB | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **llama2:13b** | 13B | 16GB | ⭐⭐ | ⭐⭐⭐⭐⭐ |

**Recomendacao**: Comece com `tinyllama` (ambientes leves). Em maquinas mais fortes, use `llama2` ou `mistral`.

---

## ⚙️ Como Funciona

### Fluxo

```
CLI/Python
    ↓
LauraOllamaAnalyzer (llm_local.py)
    ↓
Verifica se Ollama está rodando
    ↓
Se não: Inicia automaticamente
    ↓
Verifica se modelo está baixado
    ↓
Se não: Baixa (primeira vez)
    ↓
Envia prompt + métricas
    ↓
Ollama processa localmente
    ↓
Retorna resposta JSON
    ↓
Parse + Validação
    ↓
LLMAnalysisResult
    ↓
Salva em JSON + Histórico JSONL
```

### Por baixo dos panos

1. **Ollama serve** roda em background na porta 11434
2. **POST /api/generate** envia prompt + temperatura
3. **Llama 2/Mistral** processa na CPU/GPU
4. **JSON response** é parseado e validado
5. **Resultado** é salvo e retornado

---

## 💻 Requisitos de Hardware

| RAM | GPU | Modelo |
|-----|-----|--------|
| 8GB | Nenhuma | llama2, mistral (lento) |
| 16GB | Nenhuma | llama2, mistral (razoável) |
| 8GB | NVIDIA/AMD | Muito mais rápido! |
| 32GB+ | Qualquer | llama2:13b |

**Nota**: Primeira execução baixa o modelo (~4GB para 7B)

---

## 🎓 Exemplos

### Exemplo 1: Negócio Saudável

```python
metrics = {
    "revenue": 45000,
    "cogs": 15000,
    "ad_spend": 5000,
    "shipping_subsidy": 2000,
    "refunds": 500,
    "orders": 150
}

result = analyzer.analyze_profitability(metrics)
# → decision: "SCALE_WINNERS"
# → priority: "MEDIUM"
# → confidence: 0.92
# → inference_time_ms: 2500
```

### Exemplo 2: Problema com Reembolsos

```python
metrics = {
    "revenue": 30000,
    "cogs": 12000,
    "ad_spend": 8000,
    "shipping_subsidy": 3000,
    "refunds": 3000,  # 10% taxa!
    "orders": 100
}

result = analyzer.analyze_profitability(metrics)
# → decision: "REFUND_GUARD"
# → priority: "CRITICAL"
# → reasoning: "Taxa de reembolsos crítica (10% > 5%)..."
```

---

## 🐛 Troubleshooting

### Erro: "Ollama não está rodando"

```bash
# Iniciar manualmente
ollama serve

# Em outro terminal:
laura llm-analyze
```

### Erro: "Modelo não encontrado"

```bash
# Ollama baixa automaticamente, mas se quiser manualmente:
ollama pull llama2
ollama pull mistral

# Ver modelos disponíveis
ollama list
```

### Análise muito lenta

```bash
# Usar modelo mais rápido
laura llm-analyze --model mistral

# Ou com GPU (se tiver)
# Ollama usa GPU automaticamente se disponível
```

### Resposta em JSON inválido

Às vezes o modelo gera texto antes do JSON. Código detecta automaticamente e extrai o JSON válido.

---

## 📈 Performance

### Tempo de Inferência (aprox)

| Modelo | CPU 8GB | CPU 16GB | GPU NVIDIA |
|--------|---------|----------|-----------|
| mistral | 45s | 25s | 3s |
| llama2 | 60s | 35s | 4s |
| neural-chat | 50s | 30s | 3s |

**Nota**: Primeira execução pode ser mais lenta (JIT compilation)

---

## 🔐 Segurança

✅ **Privacidade Garantida**:
- Dados NUNCA são enviados para nenhum servidor
- Tudo roda localmente na sua máquina
- Sem dependência de APIs externas
- Nenhuma chave, nenhum token

---

## 🔄 Integração com Cron

```bash
# Adicionar análise LLM a cada 10 min
*/10 * * * * cd /home/shopee/agente && ./scripts/laura_profitability_llm_analyzer.sh >> logs/llm.log 2>&1
```

---

## 📊 Resultados

Cada análise retorna:

```json
{
  "decision": "SCALE_WINNERS",
  "action": "scale_winners",
  "priority": "MEDIUM",
  "mode": "dry_run",
  "metrics": {
    "margin_pct": 22.5,
    "roas": 4.2,
    "refund_rate_pct": 2.1,
    "order_volume": 150
  },
  "reasoning": "Negócio saudável com margem 22.5% e ROAS 4.2x...",
  "next_steps": "Aumentar investimento em produtos top performers...",
  "confidence": 0.88,
  "inference_time_ms": 2847,
  "model": "llama2",
  "timestamp": "2024-04-20T..."
}
```

---

## 📝 Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `shopee_agent/llm_local.py` | SDK Ollama (novo) |
| `shopee_agent/cli.py` | CLI atualizado (usa Ollama) |
| `requirements.txt` | Sem anthropic, só requests |
| `.env.example` | Sem ANTHROPIC_API_KEY |

---

## 🎯 Comparação: Cloud vs Local

| Aspecto | Claude API | Ollama Local |
|---------|-----------|------------|
| Chave API | ✅ Necessária | ❌ Não precisa |
| Custo | $3/mês | Grátis |
| Privacidade | ⚠️ Cloud | ✅ Local |
| Internet | ✅ Necessária | ❌ Offline |
| Qualidade | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Velocidade | ⭐⭐⭐ | ⭐⭐ (CPU) |
| Setup | Fácil | Muito fácil |
| GPU? | N/A | ✅ Sim (mais rápido) |

---

## 🚀 Quick Start (TL;DR)

```bash
# 1. Instalar Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# 2. Instalar Python deps
pip install -r requirements.txt

# 3. Usar!
laura llm-analyze

# Pronto! Tudo roda local, grátis, privado
```

---

## 📚 Referências

- Ollama: https://ollama.ai
- Llama 2: https://llama.meta.com
- Mistral: https://mistral.ai
- Modelos: https://ollama.ai/library

---

**Status**: ✅ Pronto para produção (100% local)  
**Data**: 2024-04-20  
**Versão**: 1.0
