Resumo do PR — Phase 35 (Memory & Learning Layer)

Objetivo
- Consolidar as mudanças da Fase 35: `DecisionOutcome` + `MemoryLayer`, ajustes em `llm_local`, `healthcheck_service` e comandos CLI.

O que foi alterado
- Implementado `shopee_agent/decision_memory.py` (JSONL-backed MemoryLayer).
- Atualizado `shopee_agent/decision_cli.py` e `shopee_agent/cli.py` para expor comandos de inspeção/learning.
- Adicionado wrapper `_check_model_loaded()` em `shopee_agent/llm_local.py`.
- Tornado `shopee_agent/healthcheck_service.py` determinístico em relação a `products_count`.
- Testes: novos testes para `decision_memory` e CLI; ajustes para determinismo.

Resultados dos testes
- `pytest` (suíte completa): 244 passed, 0 failed, 324 warnings. Tempo: ~7s (local)

Observações de segurança (necessário)
- Durante preparação local foi criada a branch `pr/phase35-prepare` que acidentalmente contém arquivos sensíveis e backups (ex.: `Credencial.Laura.json`, backups, `secrets/gmail_tokens_laura.json`). NÃO dar push dessa branch.
- Use `pr/phase35-prepare-clean` (branch criada a partir de `main`) para abrir o PR; este branch contém apenas o rascunho e commits limpos.

Próximos passos (sugestão)
1. Revisar mudanças em `pr/phase35-prepare-clean`.
2. Push do branch e abrir PR no repositório remoto.
3. Após revisão e aprovação, executar deploy/smoke em staging e monitorar Telegram/healthcheck.

Comandos úteis
- Criar branch limpa (local): `git checkout -B pr/phase35-prepare-clean main`
- Subir branch e abrir PR: `git push origin pr/phase35-prepare-clean` e abrir PR via GitHub/GitLab UI.

Notas
- Se quiser que eu tente reescrever o histórico de `pr/phase35-prepare` para remover totalmente arquivos sensíveis (git filter-repo), preciso de confirmação — isso é destrutivo e requer cuidado com pushes já feitos.
