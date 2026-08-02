param(
    [int]$CheckInterval = 30,
    [switch]$Stop,
    [switch]$CdpAutoLaunch
)

$ErrorActionPreference = "Continue"
$rootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$logFile = "$rootDir\logs\laura_watchdog.log"
$pidFile = "$rootDir\logs\laura_watchdog.pid"
$daemonPidFile = "$rootDir\logs\laura_daemon.pid"

if (-not (Test-Path "$rootDir\logs")) { New-Item -ItemType Directory -Path "$rootDir\logs" -Force | Out-Null }

function Write-Log($msg) {
    "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}

if ($Stop) {
    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    Write-Log "[WATCHDOG] Stopping daemon..."
    $procs = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "laura_daemon" }
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    if (Test-Path $daemonPidFile) { Remove-Item $daemonPidFile -Force -ErrorAction SilentlyContinue }
    Write-Host "[WATCHDOG] Daemon stopped" -ForegroundColor Yellow
    return
}

# Save watchdog PID
$pid.ToString() | Out-File -FilePath $pidFile -Force

Write-Log "[WATCHDOG] Started (interval=${CheckInterval}s)"
Write-Host "[WATCHDOG] Monitoring daemon every ${CheckInterval}s (PID: $pid)" -ForegroundColor Cyan

# --- Deteccao de navegador Chromium (agente: nao depende de navegador especifico) ---
# Ordem: LAURA_CDP_BROWSER_PATH (env) -> Brave -> Chrome -> Edge
function Find-Browser {
    $envPath = [Environment]::GetEnvironmentVariable("LAURA_CDP_BROWSER_PATH")
    if ($envPath -and (Test-Path $envPath)) { return $envPath }
    $candidates = @(
        "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        "C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

function Test-CDP {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:9222/json/version" -TimeoutSec 3 -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# Verifica se o navegador encontrado ja esta rodando (para nao abrir janelas duplicadas)
function Test-BrowserRunning($exePath) {
    $name = [System.IO.Path]::GetFileNameWithoutExtension($exePath)
    return [bool](Get-Process -Name $name -ErrorAction SilentlyContinue)
}

$script:cdpLaunchAttempted = $false

function Ensure-CDP {
    if (Test-CDP) { return $true }
    if ($script:cdpLaunchAttempted) {
        Write-Log "[WATCHDOG] CDP offline; launch ja tentado nesta sessao, nao vou repetir."
        return $false
    }
    $script:cdpLaunchAttempted = $true
    if (-not $CdpAutoLaunch) {
        Write-Log "[WATCHDOG] CDP offline. Auto-launch desabilitado (use -CdpAutoLaunch para permitir)."
        return $false
    }
    $browser = Find-Browser
    if (-not $browser) {
        Write-Log "[WATCHDOG] CDP offline e nenhum navegador Chromium encontrado. Auto-login do Seller Center indisponivel."
        return $false
    }
    if (Test-BrowserRunning $browser) {
        Write-Log "[WATCHDOG] CDP offline, mas $browser ja esta aberto (sem porta de debug). Nao vou abrir outra janela."
        return $false
    }
    Start-Process -FilePath $browser -ArgumentList "--remote-debugging-port=9222", "--remote-allow-origins=*"
    Write-Log "[WATCHDOG] CDP offline; abri $browser com --remote-debugging-port=9222 (1x nesta sessao)."
    return $false
}

function Start-Daemon {
    $daemonScript = "$rootDir\shopee_agent\laura_daemon.py"
    $outLog = "$rootDir\logs\laura_daemon.out.log"
    $errLog = "$rootDir\logs\laura_daemon.err.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    # Preferir pythonw.exe: roda sem janela de terminal
    $python = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
    $usePythonw = Test-Path $python
    if (-not $usePythonw) {
        $python = (Get-Command python).Source
    }

    try {
        $existing = Find-RunningDaemon
        if ($existing) {
            Write-Log "[WATCHDOG] Daemon ja em execucao (PID $($existing.ProcessId)). Adotando..."
            $existing.ProcessId | Out-File -FilePath $daemonPidFile -Force
            return [int]$existing.ProcessId
        }
        Write-Log "[WATCHDOG] Starting daemon with $python..."
        if ($usePythonw) {
            # pythonw nao tem stdout: sem redirects, loga nos proprios arquivos
            $proc = Start-Process -FilePath $python -ArgumentList "-u", "`"$daemonScript`"" -WorkingDirectory $rootDir -PassThru
        } else {
            $proc = Start-Process -FilePath $python -ArgumentList "-u", "`"$daemonScript`"" -WorkingDirectory $rootDir -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
        }
        $proc.Id | Out-File -FilePath $daemonPidFile -Force
        Write-Log "[WATCHDOG] Daemon started with PID $($proc.Id)"
        return [int]$proc.Id
    } catch {
        Write-Log "[WATCHDOG] Failed to start daemon: $_"
        Write-Host "[WATCHDOG] Failed: $_" -ForegroundColor Red
        return $null
    }
}

function Find-RunningDaemon {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -match "laura_daemon|shopee_agent\.cli daemon" -and
            $_.CommandLine -match [regex]::Escape($rootDir)
        } |
        Select-Object -First 1
}

function Is-Alive($procId) {
    if (-not $procId) { return $false }
    return ($null -ne (Get-Process -Id $procId -ErrorAction SilentlyContinue))
}

$script:restartTimes = @()
$script:crashAlertSent = $false

function Send-TelegramAlert($text) {
    try {
        $envVars = @{}
        Get-Content "$rootDir\.env" -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_ -match "^([A-Za-z0-9_]+)=(.*)$") { $envVars[$matches[1]] = $matches[2] }
        }
        $token = $envVars["LAURA_ALERT_TELEGRAM_BOT_TOKEN"]
        $chat = $envVars["LAURA_ALERT_TELEGRAM_CHAT_ID"]
        if (-not $token -or -not $chat) {
            Write-Log "[WATCHDOG] alerta nao enviado (token/chat ausentes no .env)"
            return
        }
        $uri = "https://api.telegram.org/bot$token/sendMessage"
        Invoke-RestMethod -Uri $uri -Method Post -Body @{ chat_id = $chat; text = $text } -TimeoutSec 15 | Out-Null
        Write-Log "[WATCHDOG] alerta Telegram enviado"
    } catch {
        Write-Log "[WATCHDOG] falha ao enviar alerta: $_"
    }
}

# Initial start (adota daemon existente, se houver; evita daemons duplicados)
$daemonPid = Start-Daemon

while ($true) {
    Start-Sleep -Seconds $CheckInterval

    if (-not (Is-Alive $daemonPid)) {
        Write-Log "[WATCHDOG] Daemon morto (PID $daemonPid). Reiniciando..."
        Write-Host "[WATCHDOG] Daemon died (PID $daemonPid). Restarting..." -ForegroundColor Yellow
        $daemonPid = Start-Daemon
        # alerta se caiu 2+ vezes em 10 minutos (1 alerta, depois silencia por 1h)
        $script:restartTimes = @($script:restartTimes | Where-Object { $_ -gt (Get-Date).AddMinutes(-10) })
        $script:restartTimes += (Get-Date)
        if ($script:restartTimes.Count -ge 2 -and -not $script:crashAlertSent) {
            Send-TelegramAlert "ALERTA LAURA: o daemon reiniciou $($script:restartTimes.Count)x em 10min - possivel problema serio (crash loop)."
            $script:crashAlertSent = $true
        }
        if ((Get-Date) -gt (Get-Date).AddHours(-1) -and -not $script:crashAlertSent) {
            $script:restartTimes = @()
        }
    } else {
        # saudavel: zera janela de alerta apos 30min sem queda
        $lastRestart = if ($script:restartTimes.Count) { $script:restartTimes[-1] } else { $null }
        if ($lastRestart -and $lastRestart -lt (Get-Date).AddMinutes(-30)) {
            $script:restartTimes = @()
            $script:crashAlertSent = $false
        }
    }

    # Also check daemon health endpoint
    try {
        $webhookPort = if (Test-Path "$rootDir\.env") {
            $match = Select-String -Path "$rootDir\.env" -Pattern "LAURA_WEBHOOK_PORT=(\d+)" | ForEach-Object { $_.Matches.Groups[1].Value }
            if ($match) { $match } else { 8766 }
        } else { 8766 }
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$webhookPort/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($r.StatusCode -ne 200) {
            Write-Log "[WATCHDOG] Health check failed (HTTP $($r.StatusCode)). Restarting daemon..."
            if (Is-Alive $daemonPid) { Stop-Process -Id $daemonPid -Force -ErrorAction SilentlyContinue }
            $daemonPid = Start-Daemon
        }
    } catch {
        # Webhook server might not be up yet - that's OK
    }

    # CDP para auto-login do Seller Center (1x por sessao, navegador detectado)
    Ensure-CDP | Out-Null
}
