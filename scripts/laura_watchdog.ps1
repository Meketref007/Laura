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
        Write-Log "[WATCHDOG] Starting daemon with $python..."
        if ($usePythonw) {
            # pythonw nao tem stdout: sem redirects, loga nos proprios arquivos
            $proc = Start-Process -FilePath $python -ArgumentList "-u", "`"$daemonScript`"" -WorkingDirectory $rootDir -PassThru
        } else {
            $proc = Start-Process -FilePath $python -ArgumentList "-u", "`"$daemonScript`"" -WorkingDirectory $rootDir -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
        }
        $proc.Id | Out-File -FilePath $daemonPidFile -Force
        Write-Log "[WATCHDOG] Daemon started with PID $($proc.Id)"
        return $proc
    } catch {
        Write-Log "[WATCHDOG] Failed to start daemon: $_"
        Write-Host "[WATCHDOG] Failed: $_" -ForegroundColor Red
        return $null
    }
}

# Initial start
$daemonProc = Start-Daemon

while ($true) {
    Start-Sleep -Seconds $CheckInterval

    if ($daemonProc -eq $null -or $daemonProc.HasExited) {
        $exitCode = if ($daemonProc) { $daemonProc.ExitCode } else { "N/A" }
        Write-Log "[WATCHDOG] Daemon exited (code: $exitCode). Restarting..."
        Write-Host "[WATCHDOG] Daemon died (code: $exitCode). Restarting..." -ForegroundColor Yellow
        $daemonProc = Start-Daemon
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
            if ($daemonProc -and -not $daemonProc.HasExited) { $daemonProc.Kill() }
            $daemonProc = Start-Daemon
        }
    } catch {
        # Webhook server might not be up yet - that's OK
    }

    # CDP para auto-login do Seller Center (1x por sessao, navegador detectado)
    Ensure-CDP | Out-Null
}
