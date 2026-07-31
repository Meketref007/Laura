**Release QA Checklist**

Use esta lista para validar uma release antes de publicar/mesclar em `main`.

- [ ] Código: revisar mudanças de PR relacionadas (arquivos, testes, CI).
- [ ] Testes: rodar `pytest tests/ -q` e garantir que os testes novos e existentes passam.
- [ ] Lint: executar `ruff check shopee_agent/ tests/` e corrigir problemas críticos.
- [ ] Integração Ollama: verificar `laura ollama-status` e validar que o modelo carrega.
- [ ] Ingestão de receita: rodar `laura ingest-order-revenue --days 7 --dry-run` e validar outputs em `reports/`.
- [ ] Vetores: executar `laura memory-reindex-vectors --outcomes reports/decision_outcomes.jsonl --out /tmp/vectors.jsonl --vector-backend memory --dry-run` e revisar `/tmp/vectors.jsonl`.
- [ ] Annoy/Faiss: quando aplicável, instalar `annoy` / `faiss-cpu` localmente e rodar testes específicos (`tests/test_cli_reindex_annoy.py`, `tests/test_cli_reindex_faiss.py`).
- [ ] CI: verificar que o job `vector-tests` passou (ou reexecutar manualmente se necessário).
- [ ] Artefatos: confirmar que índices/faiss meta/annoy meta foram gerados e, se apropriado, anexá-los como artefatos de build.
- [ ] Segurança: revisar mudanças que envolvem secrets/config; garantir que nada sensível foi comitado.
- [ ] Documentação: confirmar `CHANGELOG.md`, `docs/VECTOR_STORE_CLI.md` e `docs/phases/` atualizados.
- [ ] Aprovação: obter revisão de pelo menos 1 mantenedor e marcação de aprovação no PR.
- [ ] Tag & Release: criar tag semântica e publicar release (ou usar rascunho se preferir revisão adicional).

Notas:
- Sempre replicar passos críticos em ambiente local antes de aprovar a publicação.
- Quando houver dependências opcionais (Faiss/Annoy), documentar versões testadas.
