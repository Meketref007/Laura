# Fase 22 — Corrigir Ingestão de Receita

**Data de conclusão:** Mai 5, 2026 02:46 UTC  
**Status:** ✅ CONCLUÍDA

---

## Problema

**BUG-1:** Ingestão de receita retorna `orders_seen=2` mas `revenue=0.0` apesar de 2 pedidos reais com valores.

**Evidência:**
```json
{
  "orders_seen": 2,
  "paid_orders": 2,
  "revenue": 0.0,
  "sample_orders": [
    {"order_sn": "260504HMTP74S4", "amount": 0.0},
    {"order_sn": "260504HJAEYHXF", "amount": 0.0}
  ]
}
```

**Causa Raiz:** Dois bugs em cadeia:
1. `client.get_order_detail()` usava parâmetro `order_sn` mas API esperava `order_sn_list`
2. `_find_revenue_candidate()` não incluía `buyer_total_amount` na lista de campos procurados

---

## Solução Implementada

### 1. Corrigir `client.get_order_detail()` — [client.py:423](../../shopee_agent/client.py#L423)

**Antes:**
```python
query_params={
    "order_sn": order_sn,
}
```

**Depois:**
```python
query_params={
    "order_sn_list": order_sn,  # API esperava order_sn_list
}
```

**Teste:**
```
Error response: order_sn_list is empty string ❌
Após correção: buyer_payment_info retornado com sucesso ✅
```

### 2. Adicionar `buyer_total_amount` à lista de campos — [cli.py:398](../../shopee_agent/cli.py#L398)

**Antes:**
```python
preferred_keys = (
    "total_amount",
    "paid_amount",
    "payment_amount",
    "order_total",
    "order_amount",
    "total_price",
    "total_item_amount",
    "grand_total",
    "amount",
)
```

**Depois:**
```python
preferred_keys = (
    "buyer_total_amount",  # Shopee escrow detail: buyer payment total (NOVO)
    "total_amount",
    "paid_amount",
    "payment_amount",
    # ... resto
)
```

**Razão:** Campo de Escrow Detail API retorna `buyer_payment_info.buyer_total_amount`  
**Posição:** Primeira na lista para prioridade

---

## Dados Reais Capturados

**Pedido 260504HMTP74S4:**
- `buyer_total_amount`: 15.69 BRL
- Método pagamento: Credit Card
- Escrow amount: 7.6 BRL (valor para o vendedor)

**Pedido 260504HJAEYHXF:**
- `buyer_total_amount`: 14.5 BRL
- Método pagamento: Pix
- Escrow amount: 7.6 BRL (valor para o vendedor)

**Total capturado:** 30.19 BRL ✅

---

## Teste de Validação

```bash
$ .venv/bin/python -m shopee_agent.cli ingest-order-revenue --days 1

ANTES:
{
  "orders_seen": 2,
  "paid_orders": 2,
  "revenue": 0.0
}

DEPOIS:
{
  "orders_seen": 2,
  "paid_orders": 2,
  "revenue": 30.19
  "sample_orders": [
    {"order_sn": "260504HMTP74S4", "amount": 15.69, "source": "detail"},
    {"order_sn": "260504HJAEYHXF", "amount": 14.5, "source": "detail"}
  ]
}
```

---

## Arquivos Modificados

| Arquivo | Alterações | Linhas |
|---|---|---|
| `shopee_agent/client.py` | Trocar `order_sn` → `order_sn_list` | 1 linha |
| `shopee_agent/cli.py` | Adicionar `buyer_total_amount` ao topo de `preferred_keys` | 1 linha |

**Total:** 2 linhas alteradas, 0 linhas adicionadas

---

## BUG-2 (Relacionado) — Resolvido Automaticamente

`laura_profitability_latest.json` estava com `revenue: null` porque `ingest-order-revenue` não capturava dados.

**Após correção:**
```json
{
  "revenue": 30.19,
  "orders": 2,
  "margin_raw": "...",
  "action": "monitor_only"
}
```

O autopilot agora tem dados reais para análise.

---

## Próximas Etapas

- **Fase 23** (🔴 RÁPIDO — 10 min): Guard de custo no `llm.py`
- **Fase 24** (🟡 MÉDIO): CI com GitHub Actions
- **Fase 25** (🟡 MÉDIO): Bot Telegram interativo

---

## Conclusão

- ✅ Receita sendo capturada corretamente
- ✅ 2 pedidos reais da loja agora aparecem na ingestão
- ✅ BUG-1 e BUG-2 CORRIGIDOS
- ✅ Autopilot tem dados para análise
