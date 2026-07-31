v0.2.2 — Annoy backend & operational docs
=========================================

Resumo
------
Esta versão adiciona um adaptador Annoy para armazenamento e busca vetorial, integração CLI para busca/reindex, documentação operacional e melhorias na persistência de vetores durante a gravação de outcomes.

Principais destaques
--------------------
- `shopee_agent/vector_store_annoy.py`: adaptador Annoy com persistência do índice e sidecar de metadados.
- CLI: `memory-semantic-search` e `memory-reindex-vectors` suportam `--vector-backend` (opções: `memory`, `annoy`).
- `MemoryLayer.remember_outcome_with_vector` persiste vetores no sidecar e aciona build/persist do índice (imediato) para visibilidade imediata.
- Background build opcional: `LAURA_ANNOY_BACKGROUND_BUILD` e `LAURA_ANNOY_BUILD_INTERVAL` permitem construir o índice em segundo plano.
- Documentação: `docs/ANNoy_BACKEND.md` e `docs/ANNoy_PLAYBOOK.md` com exemplos operacionais (cron/systemd, monitoramento).

Compatibilidade / Migração
-------------------------
- Vetores persistidos anteriormente em `reports/decision_vectors.jsonl` continuam compatíveis; o CLI pode carregar esse JSONL para popular o índice Annoy.
- Garantir que sua dimensionalidade de embedding (`LAURA_VECTOR_DIM`) corresponda ao usado para gerar vetores (padrão 128).

Variáveis de ambiente relevantes
-------------------------------
- `LAURA_VECTOR_BACKEND` — `memory` (padrão) ou `annoy`.
- `LAURA_ANNOY_INDEX_PATH` — caminho do arquivo do índice (padrão `reports/annoy_index.ann`).
- `LAURA_ANNOY_META_PATH` — caminho do sidecar JSON (padrão `reports/annoy_meta.json`).
- `LAURA_VECTOR_DIM` — dimensão do vetor (padrão `128`).
- `LAURA_ANNOY_BACKGROUND_BUILD` — `1` para habilitar build em background.
- `LAURA_ANNOY_BUILD_INTERVAL` — intervalo em segundos para build em background (padrão `60`).

Comandos rápidos
---------------
- Reindex (escreve JSONL ou popula Annoy):

```bash
.venv/bin/python -m shopee_agent.cli memory-reindex-vectors --outcomes-path reports/decision_outcomes.jsonl --vector-backend annoy
```

- Consultar semanticamente:

```bash
.venv/bin/python -m shopee_agent.cli memory-semantic-search --text "consulta" --vector-backend annoy --top-k 5
```

Notas de testes
--------------
- Testes unitários e de integração relevantes para o adaptador Annoy e o fluxo de memória foram adicionados e a suíte completa foi executada localmente (244 testes passaram).

Arquivos principais alterados
---------------------------
- `shopee_agent/vector_store_annoy.py` (novo)
- `shopee_agent/cli.py` (integração do backend e flags)
- `shopee_agent/decision_memory.py` (persistência de vetores e auto-build)
- `shopee_agent/config.py` (opções de configuração de backend)
- `docs/ANNoy_BACKEND.md`, `docs/ANNoy_PLAYBOOK.md` (documentação)

Como reverter
-------------
- Reverter o tag/commit no Git ou alterar `LAURA_VECTOR_BACKEND=memory` para desativar o uso de Annoy se necessário.

Obrigado — entre em contato se quiser que eu publique notas maiores ou crie assets adicionais (ex.: tutorial passo-a-passo ou integração Faiss). 
