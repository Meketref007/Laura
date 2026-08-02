# Instalador + atualizações automáticas

Instala a Laura em `%LOCALAPPDATA%\Laura` (fora do OneDrive — portátil) e
mantém o código sempre atualizado via `git pull` da `main`.

## Distribuição "como um software"

- **`Setup.exe`** (Inno Setup): instalador gráfico padrão Windows — instala,
  configura, cria atalhos (Desktop + Menu Iniciar) e desinstala pelo
  "Programas e recursos". Baixe em `dist\Laura-Setup-3.1.0.exe`.
- **Painel de Controle** (`laura_painel.pyw`): app desktop com ícone no Menu
  Iniciar — mostra status de webhook/telegram/daemon/watchdog, health check,
  botões Iniciar/Parar/Reiniciar/Atualizar agora, logs do daemon ao vivo,
  e atalhos para o Dashboard e pastas.

Para gerar o Setup.exe:

```powershell
powershell -File installer\build_setup.ps1
```

O script gera o ícone (PIL), baixa o Inno Setup se não houver, e compila
`laura_setup.iss` → `dist\Laura-Setup-<versão>.exe`.

## Como instalar (sem Setup.exe)

Requisitos: Windows 10/11, **git**, **Python 3.12+**, **Ollama**.

```powershell
# a partir de uma pasta qualquer (o instalador baixa o repo do GitHub)
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

Flags úteis:

| Flag | Efeito |
|---|---|
| `-InstallPlaywright` | Instala também o browser do Playwright (auto-login Seller Center) |
| `-OldDir "C:\caminho\agente"` | Migra `.env`, `secrets`, `logs`, `backups`, `reports`, `data` de uma instalação antiga |
| `-NoMigrate` | Pula a migração de dados |
| `-Force` | Reinstala por cima de uma instalação existente (sem apagar dados) |
| `-NoSchedule` | Não cria a tarefa agendada de update diário |
| `-NoShortcut` | Não cria atalhos nem início automático |
| `-AsService` | Cria tarefas ONSTART (rodam no boot **sem precisar de login**). Requer **admin**: `powershell -File installer\install.ps1 -AsService` num terminal elevado |

O que o instalador faz:

1. Baixa o código do GitHub (git clone; fallback para ZIP sem git).
2. Cria `.venv` e instala as dependências (`pip install -e .`).
3. Detecta uma instalação antiga (ex.: `OneDrive\Documentos\Laura\agente`),
   para os serviços dela e migra os dados (sem apagar a pasta antiga).
4. Cria `.env` a partir do `.env.example` se não existir.
5. Agenda **"Laura Update"** (diário às 03:00) e **"Laura Backup"** (diário às 03:30).
6. Com `-AsService` (admin): cria **"Laura Services"** e **"Laura Update Boot"** com `ONSTART` —
   webhook, telegram, daemon e watchdog sobem no boot mesmo sem ninguém fazer login.
7. Cria `iniciar_laura.vbs` + atalho no **Startup** (início automático no boot)
   e atalhos no Menu Iniciar ("Laura CLI", "Iniciar Laura").

## Como funciona a atualização automática

- **No boot**: o `iniciar_laura.vbs` roda `scripts/laura-update.ps1` (silencioso).
- **1x/dia (03:00)**: a tarefa "Laura Update" roda o mesmo script.

O `laura-update.ps1`:

1. `git fetch origin main` e compara com o commit local.
2. Se houver novidade: para os serviços → `git pull --ff-only` →
   reinstala dependências (só se `pyproject.toml`/`requirements*` mudaram) →
   sobe os serviços de novo.
3. Loga tudo em `logs\laura-update.log`. Não toca em `.env`, `secrets/` nem `reports/`.

Atualização manual:

```powershell
powershell -File scripts\laura-update.ps1
```

## Gerenciar serviços

```powershell
powershell -File scripts\laura-services.ps1 status   # ver o que está rodando
powershell -File scripts\laura-services.ps1 restart  # reiniciar tudo
powershell -File scripts\laura-services.ps1 stop     # parar tudo
```

ou pelo console `laura.cmd` (Menu Iniciar → Laura CLI): `laura status`, `laura update`, etc.

## Desinstalar

```powershell
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1
# mantém dados (logs, backups, reports, .env). Para apagar tudo:
# powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1 -FullUninstall
```

## Estrutura

```
%LOCALAPPDATA%\Laura\
├── code\                  # código (git clone, atualizado automaticamente)
│   ├── .venv\             # ambiente Python
│   ├── .env               # credenciais (nunca vai para o git)
│   ├── logs\ secrets\ reports\ data\ backups\   # dados migrados/mantidos
│   ├── scripts\laura-update.ps1    # auto-update
│   ├── scripts\laura-services.ps1  # start/stop/status
│   └── installer\         # este instalador
├── iniciar_laura.vbs      # início automático no boot (gerado pelo instalador)
└── install.log
```

> A pasta antiga (`OneDrive\...\agente`) fica intacta como backup após a migração.
