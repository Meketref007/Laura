## Laura v3.0.0 — Agente Autônomo para Shopee

Release principal com evolução completa do sistema: 1205+ testes passando, CI 100% verde no GitHub Actions e cobertura de 43%.

### Destaques

**Automação & Decisão**
- GOAP Planner + Skill Registry modular com execução de habilidades referenciadas por decisões
- Decision Engine com memória vetorial (Annoy/Faiss) e reindexação
- MemoryLayer com memória semântica persistente e CLI de busca vetorial
- Feature flag `LAURA_ENABLE_AUTO_SKILLS` para execução autônoma de skills

**Operação & Confiabilidade**
- Daemon Guardian: auto-restart do agente com backoff exponencial (5s→40s)
- Monitor de rate limits da API Shopee (`laura api-usage`, SQLite, alertas 80%/95%)
- Cache de respostas LLM com TTL 24h (`LAURA_LLM_CACHE`)
- Self-healing em falhas de rede/API
- Startup rápido: CLI carrega em ~0.25s (lazy loading)

**Plataforma & Integração**
- API REST versionada (`/api/v1/`, `/api/v2/`) com headers de deprecação
- Dashboard web com auto-build do frontend e suporte a SPA
- Plugin SDK (`laura plugin` + `create_plugin`)
- Webhook pipeline E2E, onboarding wizard (`laura setup`) e Cloudflare tunnel

**Documentação & Qualidade**
- SDS completo (System Design Specification, ~3000 linhas)
- Site de documentação (mkdocs, 10 páginas)
- Type hints em módulos core, mypy em 13 módulos no CI
- 1205+ testes (unitários + 75 E2E), CI verde com ruff/mypy/cobertura

### Links
- [Documentação](https://meketref007.github.io/Laura/)
- [CLI — todos os comandos](README.md#cli)
