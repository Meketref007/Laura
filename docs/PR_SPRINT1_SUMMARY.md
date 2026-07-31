# Sprint 1 — Correções e Preparação para Produção

Resumo das mudanças incluídas neste PR/commit set:

- Corrigido ingestão de receita: agora filtra `order_status=COMPLETED` e usa `update_time`.
- Conectado `autonomous_loop.py` ao `DecisionIntegrator` para processar ciclos autonomamente.
- `health_score` garantido como valor numérico (int) no `healthcheck_service`.
- Tornado dependências opcionais (e.g., `uvicorn`, `annoy`, `faiss`) robustas e testes puláveis quando ausentes.
- Melhorias em `DecisionMemory` para filtrar ids sem vetores e proteger contra mismatch dimensional (padding).
- Adicionado passo no workflow `faiss.yml` para instalar `httpx2`, resolvendo erro de coleta de testes (`starlette.testclient`).
- Atualizados testes para pular testes de backends opcionais quando dependências faltam; suite local principal: `251 passed, 3 deselected`.

Notas operacionais:
- CI principal (`CI` workflow) e workflow Faiss manual foram executados com sucesso após a correção.
- Vetores persistem em `reports/` como sidecar JSONL (nenhuma mudança de API externa esperada).

Próximos passos recomendados:
- Revisão de código e merge para `main` (este branch contém apenas o resumo — código já está em `main`).
- Se preferir, mover alguns testes heavy-native para workflow separado (já existe `faiss.yml`).
- Planejar Sprint 2: scaffolding para `SkillRegistry` e integração contínua de testes LLM locais.

Contatos: enviar dúvidas no PR ou abrir issue referenciando este resumo.
