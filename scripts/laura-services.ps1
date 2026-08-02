param(
    [ValidateSet("start", "stop", "status", "restart")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Continue"

# Resolve o diretorio do codigo: LAURA_HOME (env) ou %LOCALAPPDATA%\Laura\code
if ($env:LAURA_HOME) {
    $codeDir = $env:LAURA_HOME
} else {
    $codeDir = Join-Path $env:LOCALAPPDATA "Laura\code"
}
$pyw = Join-Path $codeDir ".venv\Scripts\pythonw.exe"
$py = Join-Path $codeDir ".venv\Scripts\python.exe"
$watchdog = Join-Path $codeDir "scripts\laura_watchdog.ps1"
$logFile = Join-Path $codeDir "logs\laura-services.log"

if (-not (Test-Path $codeDir)) {
    Write-Host "[laura] Codigo nao encontrado em $codeDir`nRode o instalador: powershell -ExecutionPolicy Bypass -File installer\install.ps1" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $codeDir "logs"))) { New-Item -ItemType Directory -Path (Join-Path $codeDir "logs") -Force | Out-Null }

function Write-Log($msg) {
    "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}

function Get-LauraProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -match [regex]::Escape($codeDir) -and
            $_.CommandLine -match "laura_daemon|shopee_agent\.cli|laura_watchdog"
        } |
        Sort-Object ProcessId
}

function Stop-Services {
    $procs = Get-LauraProcesses
    if (-not $procs) { Write-Log "stop: nada rodando"; return }
    # para o watchdog por ultimo (ele renasce o daemon)
    $ordered = $procs | Where-Object { $_.CommandLine -notmatch "laura_watchdog" }
    $ordered += $procs | Where-Object { $_.CommandLine -match "laura_watchdog" }
    foreach ($p in $ordered) {
        Write-Log "stop: PID $($p.ProcessId) ($($p.Name))"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Start-Services {
    # 0. Ollama (LLM local)
    if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
        if ($ollama) {
            Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Hidden | Out-Null
            Write-Log "start: ollama serve"
            Start-Sleep -Seconds 4
        } else {
            Write-Log "start: WARN ollama nao encontrado (Laura precisa dele para o LLM local)"
        }
    }

    # 1. Webhook (Mini App + eventos)
    Start-Process -FilePath $pyw -ArgumentList "-m", "shopee_agent.cli", "webhook-start", "--host", "0.0.0.0", "--port", "8766" -WorkingDirectory $codeDir | Out-Null
    Write-Log "start: webhook (:8766)"
    Start-Sleep -Seconds 3

    # 2. Telegram Bot
    Start-Process -FilePath $pyw -ArgumentList "-m", "shopee_agent.cli", "telegram-bot" -WorkingDirectory $codeDir | Out-Null
    Write-Log "start: telegram-bot"
    Start-Sleep -Seconds 3

    # 3. Daemon autonomo
    Start-Process -FilePath $pyw -ArgumentList "-m", "shopee_agent.cli", "daemon" -WorkingDirectory $codeDir | Out-Null
    Write-Log "start: daemon"
    Start-Sleep -Seconds 2

    # 4. Watchdog (mantem daemon vivo)
    if (Test-Path $watchdog) {
        Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$watchdog`"" | Out-Null
        Write-Log "start: watchdog"
    }
}

function Show-Status {
    $procs = Get-LauraProcesses
    if (-not $procs) {
        Write-Host "[laura] Servicos PARADOS" -ForegroundColor Yellow
        return
    }
    Write-Host "[laura] Servicos ATIVOS ($($procs.Count)):" -ForegroundColor Green
    foreach ($p in $procs) {
        $cmd = $p.CommandLine
        $label = if ($cmd -match "webhook-start") { "webhook" }
                 elseif ($cmd -match "telegram-bot") { "telegram" }
                 elseif ($cmd -match "laura_daemon") { "daemon" }
                 elseif ($cmd -match "laura_watchdog") { "watchdog" }
                 else { "outro" }
        "{0,-9} PID {1,-7} {2}" -f $label, $p.ProcessId, ($cmd -replace [regex]::Escape($codeDir), ".").Trim() | ForEach-Object { Write-Host $_ }
    }
}

switch ($Action) {
    "start"   { Start-Services; Start-Sleep -Seconds 2; Write-Log "start: completo"; Show-Status }
    "stop"    { Stop-Services; Write-Log "stop: completo"; Write-Host "[laura] Servicos parados" -ForegroundColor Yellow }
    "status"  { Show-Status }
    "restart" { Stop-Services; Start-Services; Start-Sleep -Seconds 2; Write-Log "restart: completo"; Show-Status }
}
