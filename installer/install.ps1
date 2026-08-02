param(
    [string]$InstallDir = $(Join-Path $env:LOCALAPPDATA "Laura"),
    [string]$OldDir = "",
    [switch]$InstallPlaywright,
    [switch]$Force,
    [switch]$SkipClone,
    [switch]$InstallModels,
    [switch]$NoSchedule,
    [switch]$NoShortcut,
    [switch]$NoMigrate
)

$ErrorActionPreference = "Continue"
$RepoUrl = "https://github.com/Meketref007/Laura.git"
$RepoZip = "https://codeload.github.com/Meketref007/Laura/zip/refs/heads/main"
$codeDir = Join-Path $InstallDir "code"
$installLog = Join-Path $InstallDir "install.log"

function Write-Log($msg) {
    "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $msg" | Out-File -FilePath $installLog -Append -Encoding utf8
}
function Say($msg, $color = "White") {
    Write-Log $msg
    if ($color -eq "Green") { Write-Host $msg -ForegroundColor Green }
    elseif ($color -eq "Yellow") { Write-Host $msg -ForegroundColor Yellow }
    elseif ($color -eq "Red") { Write-Host $msg -ForegroundColor Red }
    else { Write-Host $msg }
}

if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
if (-not (Test-Path (Join-Path $InstallDir "logs"))) { New-Item -ItemType Directory -Path (Join-Path $InstallDir "logs") -Force | Out-Null }

Say "=== Laura Installer ===" -color Green
Say "Instalando em: $codeDir"

# ---------- 0. Pre-requisitos ----------
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Say "WARN: git nao encontrado. O instalador vai baixar o ZIP do GitHub (sem git), mas atualizacoes automaticas exigem git." -color Yellow
}
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Say "ERRO: python nao encontrado. Instale Python 3.12+ (https://www.python.org/downloads/) e rode de novo." -color Red
    exit 1
}
try {
    $pyVer = (& $pythonCmd.Source --version) -replace "[^0-9.]", ""
    $pyMajorMinor = [version]($pyVer -replace "\.\d+$", "")
    if ($pyMajorMinor -lt [version]"3.12") {
        Say "ERRO: Python $pyVer encontrado, mas Laura exige >= 3.12." -color Red
        exit 1
    }
} catch {
    Say "ERRO: nao consegui ler a versao do python ($_)." -color Red
    exit 1
}
Say "OK: Python $pyVer"
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Say "WARN: ollama nao encontrado. Laura precisa dele para o LLM local (instale em https://ollama.com)." -color Yellow
}

# ---------- 1. Codigo ----------
if ($SkipClone) {
    Say "SkipClone: usando o codigo ja instalado em $codeDir"
    if (-not (Test-Path $codeDir)) {
        Say "ERRO: -SkipClone mas $codeDir nao existe." -color Red
        exit 1
    }
    if ($git -and -not (Test-Path "$codeDir\.git")) {
        Say "Inicializando git (para as atualizacoes automaticas)..."
        git -C $codeDir init 2>$null | Out-Null
        git -C $codeDir remote add origin $RepoUrl 2>$null
        git -C $codeDir fetch origin main --depth 1 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            git -C $codeDir reset --hard origin/main 2>$null | Out-Null
            Say "OK: repo git pronto (branch main)"
        } else {
            Say "WARN: fetch falhou; atualizacoes automaticas indisponiveis nesta sessao" -color Yellow
        }
    } elseif (-not $git) {
        Say "WARN: git nao encontrado; atualizacoes automaticas indisponiveis" -color Yellow
    }
} elseif (Test-Path $codeDir) {
    if (-not $Force) {
        Say "ERRO: $codeDir ja existe. Use -Force para reinstalar (sem apagar dados)." -color Red
        exit 1
    }
    Say "Diretorio existente: atualizando codigo..."
    if ($git) {
        git -C $codeDir fetch origin main 2>$null | Out-Null
        git -C $codeDir pull --ff-only origin main 2>$null | Out-Null
    }
} elseif ($git) {
    Say "Clonando repositório (git)..."
    git clone --depth 1 $RepoUrl $codeDir 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Say "git clone falhou. Tentando via ZIP..." -color Yellow
        Remove-Item $codeDir -Recurse -Force -ErrorAction SilentlyContinue
        $zip = Join-Path $InstallDir "laura-main.zip"
        Invoke-WebRequest -UseBasicParsing -Uri $RepoZip -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $InstallDir -Force
        Move-Item (Join-Path $InstallDir "Laura-main") $codeDir -Force
        Remove-Item $zip -Force
    }
} else {
    Say "Baixando codigo via ZIP (sem git)..."
    $zip = Join-Path $InstallDir "laura-main.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $RepoZip -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $InstallDir -Force
    Move-Item (Join-Path $InstallDir "Laura-main") $codeDir -Force
    Remove-Item $zip -Force
}
if (-not (Test-Path $codeDir)) {
    Say "ERRO: nao consegui obter o codigo." -color Red
    exit 1
}
Say "OK: codigo em $codeDir"

# ---------- 2. Ambiente Python ----------
$venv = Join-Path $codeDir ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Say "Criando venv..."
    & $pythonCmd.Source -m venv $venv
    if ($LASTEXITCODE -ne 0) { Say "ERRO: falha ao criar venv." -color Red; exit 1 }
}
$venvPython = Join-Path $venv "Scripts\python.exe"
Say "Instalando dependencias (pip install -e .)... isso pode levar alguns minutos."
& $venvPython -m pip install --upgrade pip -q 2>&1 | Out-Null
& $venvPython -m pip install -e . -q 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "ERRO: pip install falhou." -color Red
    exit 1
}
Say "OK: dependencias instaladas"

if ($InstallPlaywright) {
    Say "Instalando browser do Playwright (chromium)..."
    & $venvPython -m playwright install chromium 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Say "OK: playwright chromium" } else { Say "WARN: playwright install falhou" -color Yellow }
}

# ---------- 3. Migracao de dados ----------
if (-not $NoMigrate) {
    if (-not $OldDir) {
        $candidates = @(
            (Join-Path $env:USERPROFILE "OneDrive\Documentos\Laura\agente"),
            (Join-Path $env:USERPROFILE "OneDrive\Documents\Laura\agente"),
            (Join-Path $env:USERPROFILE "OneDrive\Laura\agente")
        )
        $OldDir = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if ($OldDir -and (Test-Path $OldDir) -and ((Resolve-Path $OldDir).Path -ne $codeDir)) {
        Say "Migrando dados de $OldDir -> $codeDir ..."
        # para os servicos antigos (watchdog antigo pode renascer o daemon)
        $oldProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match [regex]::Escape((Resolve-Path $OldDir).Path) -and $_.CommandLine -match "laura|shopee" }
        foreach ($p in $oldProcs) {
            Say "parando servico antigo: PID $($p.ProcessId) ($($p.Name))"
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 3

        foreach ($item in @(".env", "secrets", "logs", "backups", "reports", "data", "tools")) {
            $src = Join-Path $OldDir $item
            if (Test-Path $src) {
                Copy-Item -Path $src -Destination $codeDir -Recurse -Force
                Say "migrado: $item"
            }
        }
        Say "OK: migracao concluida (a pasta antiga foi mantida como backup)."
    } elseif ($OldDir) {
        Say "OldDir informado nao existe ou e o proprio destino; pulando migracao."
    }
}

# ---------- 4. Extras: cloudflared + modelos Ollama ----------
# cloudflared (tunel do webhook) - download oficial se nao existir
$cloudflared = Join-Path $codeDir "tools\cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    Say "Baixando cloudflared (tunel do webhook)..."
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $cloudflared -TimeoutSec 120
        Say "OK: cloudflared instalado"
    } catch {
        Say "WARN: nao consegui baixar o cloudflared ($_). O daemon baixa de novo se precisar." -color Yellow
    }
}

# modelos Ollama (LLM local) - opt-in, custo zero
if ($InstallModels) {
    $ollamaBin = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaBin) {
        Say "WARN: ollama nao encontrado; nao ha modelos para instalar. Instale em https://ollama.com" -color Yellow
    } else {
        $installed = & $ollamaBin.Source list 2>$null
        foreach ($model in @("moondream", "llama3.2:3b")) {
            if ($installed -match [regex]::Escape($model)) {
                Say "OK: modelo ja instalado ($model)"
            } else {
                $size = if ($model -eq "llama3.2:3b") { "~2.0 GB" } else { "~1.7 GB" }
                Say "Baixando modelo $model ($size)..."
                & $ollamaBin.Source pull $model
                if ($LASTEXITCODE -eq 0) { Say "OK: $model instalado" } else { Say "WARN: falha ao baixar $model" -color Yellow }
            }
        }
    }
}

# ---------- 5. .env ----------
$envFile = Join-Path $codeDir ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $codeDir ".env.example") $envFile -Force
    Say "Criado .env a partir do .env.example. IMPORTANTE: edite com suas credenciais (SHOPEE_PARTNER_ID, tokens, etc)." -color Yellow
} else {
    Say "OK: .env ja existe (mantido)"
}

# ---------- 5. Agendamento (atualizacao 1x/dia) ----------
if (-not $NoSchedule) {
    $updCmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$codeDir\scripts\laura-update.ps1`""
    schtasks /Create /TN "Laura Update" /TR "'$updCmd'" /SC DAILY /ST 03:00 /F | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Say "OK: tarefa agendada 'Laura Update' (diario 03:00)"
    } else {
        Say "WARN: nao consegui criar a tarefa agendada (rode como admin?). Atualizacao via boot ainda funciona." -color Yellow
    }
    $bkCmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$codeDir\scripts\laura-backup.ps1`""
    schtasks /Create /TN "Laura Backup" /TR "'$bkCmd'" /SC DAILY /ST 03:30 /F | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Say "OK: tarefa agendada 'Laura Backup' (diario 03:30, retem 7 dias)"
    } else {
        Say "WARN: nao consegui criar a tarefa de backup" -color Yellow
    }
}

# ---------- 6. Inicio automatico (boot) ----------
if (-not $NoShortcut) {
    # VBS de boot (maquina-especifica; nao vai para o git)
    $newVbs = Join-Path $InstallDir "iniciar_laura.vbs"
    $ollamaCmd = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollamaCmd) { $ollamaCmd = "C:\Users\$env:USERNAME\AppData\Local\Programs\Ollama\ollama.exe" }
    $vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
baseDir = "$codeDir"
WshShell.CurrentDirectory = baseDir

' 0. Ollama (LLM local)
If (WshShell.Run("tasklist /FI ""IMAGENAME eq ollama.exe"" /NH", 0, True) <> 0) Then
    WshShell.Run """" & "$ollamaCmd" & """" & " serve", 0, False
    WScript.Sleep 5000
End If

' 1. Verificar atualizacoes (silencioso)
WshShell.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & Chr(34) & baseDir & "\scripts\laura-update.ps1" & Chr(34), 0, False

' 2. Subir servicos (webhook, telegram, daemon, watchdog)
WshShell.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & Chr(34) & baseDir & "\scripts\laura-services.ps1" & Chr(34) & " start", 0, False
"@
    $vbsContent | Out-File -FilePath $newVbs -Encoding ASCII
    Say "OK: $newVbs"

    # repontar/atualizar atalho existente do Startup (ou criar novo)
    $startupDir = [Environment]::GetFolderPath("Startup")
    $wsh = New-Object -ComObject WScript.Shell
    $targetLnk = $null
    Get-ChildItem $startupDir -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        $lnk = $wsh.CreateShortcut($_.FullName)
        if ($lnk.TargetPath -match "iniciar_laura\.vbs") { $targetLnk = $_.FullName }
    }
    $shortcutPath = if ($targetLnk) { $targetLnk } else { Join-Path $startupDir "Laura Iniciar.lnk" }
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "wscript.exe"
    $shortcut.Arguments = "`"$newVbs`""
    $shortcut.WorkingDirectory = $codeDir
    $shortcut.Description = "Laura - inicio automatico"
    $shortcut.Save()
    if ($targetLnk) { Say "OK: atalho do Startup repontado ($shortcutPath)" } else { Say "OK: atalho criado ($shortcutPath)" }

    # atalhos no Menu Iniciar
    $menuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Laura"
    New-Item -ItemType Directory -Path $menuDir -Force | Out-Null
    $cliLnk = $wsh.CreateShortcut((Join-Path $menuDir "Laura CLI.lnk"))
    $cliLnk.TargetPath = Join-Path $codeDir "installer\laura.cmd"
    $cliLnk.WorkingDirectory = $codeDir
    $cliLnk.Save()
    $startLnk = $wsh.CreateShortcut((Join-Path $menuDir "Iniciar Laura.lnk"))
    $startLnk.TargetPath = "powershell.exe"
    $startLnk.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$codeDir\scripts\laura-services.ps1`" start"
    $startLnk.WorkingDirectory = $codeDir
    $startLnk.Save()
    Say "OK: atalhos do Menu Iniciar criados"
}

# ---------- 7. Inicio ----------
Say "Iniciando servicos..."
& "$codeDir\scripts\laura-services.ps1" start *> $null
Start-Sleep -Seconds 2
& "$codeDir\scripts\laura-services.ps1" status

Say "=== Instalacao concluida ===" -color Green
Say "Codigo:   $codeDir"
Say "Logs:     $(Join-Path $codeDir 'logs')"
Say "CLI:      $codeDir\installer\laura.cmd  (ex.: laura status, laura update)"
Say "Update:   automatico a cada boot + diario 03:00 (git pull da main)"
Say "Comando manual: powershell -File `"$codeDir\scripts\laura-update.ps1`""
Say "Desinstalar: powershell -File `"$codeDir\installer\uninstall.ps1`""
