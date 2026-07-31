param(
    [int]$CheckInterval = 30,
    [switch]$Stop
)

$ErrorActionPreference = "Continue"
$rootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$logFile = "$rootDir\logs\laura_watchdog.log"
$pidFile = "$rootDir\logs\laura_watchdog.pid"
$daemonPidFile = "$rootDir\logs\laura_daemon.pid"

if (-not (Test-Path "$rootDir\logs")) { New-Item -ItemType Directory -Path "$rootDir\logs" -Force | Out-Null }

if ($Stop) {
    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    $(Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " [WATCHDOG] Stopping daemon..." | Out-File -FilePath $logFile -Append
    $procs = Get-Process -Name "python*" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "laura_daemon" }
    foreach ($p in $procs) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    if (Test-Path $daemonPidFile) { Remove-Item $daemonPidFile -Force -ErrorAction SilentlyContinue }
    Write-Host "[WATCHDOG] Daemon stopped" -ForegroundColor Yellow
    return
}

# Save watchdog PID
$pid.ToString() | Out-File -FilePath $pidFile -Force

$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " [WATCHDOG] Started (interval=${CheckInterval}s)" | Out-File -FilePath $logFile -Append
Write-Host "[WATCHDOG] Monitoring daemon every ${CheckInterval}s (PID: $pid)" -ForegroundColor Cyan

function Start-Daemon {
    $daemonScript = "$rootDir\shopee_agent\laura_daemon.py"
    $python = (Get-Command python).Source
    $logDaemon = "$rootDir\logs\laura_daemon.log"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp [WATCHDOG] Starting daemon..." | Out-File -FilePath $logFile -Append

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $python
    $psi.Arguments = "-u `"$daemonScript`""
    $psi.WorkingDirectory = $rootDir
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1"

    try {
        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.Id | Out-File -FilePath $daemonPidFile -Force
        "$timestamp [WATCHDOG] Daemon started with PID $($proc.Id)" | Out-File -FilePath $logFile -Append
        Write-Host "[WATCHDOG] Daemon started (PID: $($proc.Id))" -ForegroundColor Green
        return $proc
    } catch {
        "$timestamp [WATCHDOG] Failed to start daemon: $_" | Out-File -FilePath $logFile -Append
        Write-Host "[WATCHDOG] Failed: $_" -ForegroundColor Red
        return $null
    }
}

function Ensure-CDP {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:9222/json/version" -TimeoutSec 3 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { return $true }
    } catch {
        # CDP not responding - try to start Brave with debug port
    }
    $brave = "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    if (Test-Path $brave) {
        Start-Process -FilePath $brave -ArgumentList "--remote-debugging-port=9222", "--remote-allow-origins=*"
        "$timestamp [WATCHDOG] CDP offline; started Brave with --remote-debugging-port=9222" | Out-File -FilePath $logFile -Append
    } else {
        "$timestamp [WATCHDOG] Brave not found at $brave; CDP unavailable" | Out-File -FilePath $logFile -Append
    }
    return $false
}

# Initial start
$daemonProc = Start-Daemon

while ($true) {
    Start-Sleep -Seconds $CheckInterval

    if ($daemonProc -eq $null -or $daemonProc.HasExited) {
        $exitCode = if ($daemonProc) { $daemonProc.ExitCode } else { "N/A" }
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$timestamp [WATCHDOG] Daemon exited (code: $exitCode). Restarting..." | Out-File -FilePath $logFile -Append
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
            "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") [WATCHDOG] Health check failed (HTTP $($r.StatusCode)). Restarting daemon..." | Out-File -FilePath $logFile -Append
            if ($daemonProc -and -not $daemonProc.HasExited) { $daemonProc.Kill() }
            $daemonProc = Start-Daemon
        }
    } catch {
        # Webhook server might not be up yet - that's OK
    }

    # Ensure Brave/CDP is available for Seller Center auto-login
    Ensure-CDP | Out-Null
}
