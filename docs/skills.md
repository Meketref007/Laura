# Skills (GOAP)

A Laura usa um sistema de **skills modulares** com planejamento GOAP (Goal-Oriented
Action Planning): cada skill declara **precondições** e **efeitos**, e o planner
encadeia skills até atingir o objetivo.

## Listar skills

```bash
laura skill-list                 # todas as skills
laura skill-profile <nome>       # detalhes de uma skill
laura skill-history <nome>       # histórico de execuções
```

## Registro e criação

```bash
laura skill-register <nome> --preconditions '{"browser_available": true}' --effects '{"browser_action_completed": true}' --cost 3 --priority 1
laura skill-create <nome> --description "..."    # gera a base
laura skill-simulate <nome>                      # testa a skill no sandbox
laura skill-test <nome>                          # roda os testes da skill
```

Cada skill vive em `shopee_agent/skills/` (estrutura de plugin):

```
skills/<nome>/
├── skill.py         # classe SkillBase: can_run(), run(ctx), effects
├── tests/           # testes da skill
└── metadata.json    # preconditions, effects, cost, priority
```

## Execução e aprovação

```bash
laura skill-run <nome>            # executa manualmente
laura skill-goap-plan <objetivo>  # planeja uma cadeia de skills (GOAP)
laura skill-approval-list         # skills aguardando aprovação
laura skill-approve <nome>        # aprova (entram no fluxo autônomo)
laura skill-reject <nome>         # rejeita
```

## Princípios

- **Preconditions** descrevem o estado do mundo necessário (ex.: `browser_available`).
- **Effects** declaram o que muda no mundo após a execução.
- **Cost + priority** orientam o planner na escolha da sequência.
- Skills **não aprovadas** ficam fora do loop autônomo do daemon.
- Novas skills entram por aprovação (guardrail) antes de agir no mundo real.

Exemplo de skill registrada hoje: `browser_skill` (custo 3, prioridade 1,
precondição `browser_available`, efeito `browser_action_completed`).
