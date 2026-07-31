# Fase 33 — Flash Sales Automáticas

**Status:** Em andamento / núcleo entregue  
**Data:** Maio 2026  
**Objetivo:** sugerir e criar flash sales para produtos com estoque alto e sem vendas recentes

## Entregue nesta etapa

- Módulo `shopee_agent/flash_sale_recommender.py`
- Comando CLI `flash-sale-recommend`
- Testes unitários cobrindo:
  - identificação de produtos parados
  - montagem do payload de flash sale
  - criação opcional da flash sale via API

## Regra de negócio

Um item entra como candidato quando:

- `stock >= min_stock` (padrão: 20)
- `sales_7d == 0`

A recomendação sugere um desconto padrão de 15%, configurável via CLI.

## Uso

```bash
laura flash-sale-recommend --shop-id 123 --access-token TOKEN
laura flash-sale-recommend --shop-id 123 --access-token TOKEN --create
```

## Saídas geradas

- `reports/laura_flash_sale_recommendation_latest.json`
- `reports/laura_flash_sale_recommendation_history.jsonl`
- `reports/laura_flash_sale_result_latest.json` quando `--create` é usado

## Próximo passo sugerido

- Adicionar verificação automática no loop autônomo para produzir uma sugestão semanal de flash sale
- Integrar alerta via Telegram quando houver candidatos
