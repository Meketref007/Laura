param(
    [int]$Port = 8765,
    [string]$CloudflaredPath = "",
    [switch]$Stop
)

$ErrorActionPreference = "Continue"
$rootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$logDir = "$rootDir\logs"
$reportDir = "$rootDir\reports"
$latestUrlFile = "$reportDir\laura_webhook_tunnel_latest.txt"
$latestCallbackFile = "$reportDir\laura_webhook_callback_latest.txt"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
if (-not (Test-Path $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }

if ($Stop) {
    Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "[Tunnel] cloudflared stopped" -ForegroundColor Yellow
    return
}

if (-not $CloudflaredPath) {
    $candidates = @(
        "$rootDir\cloudflared.exe",
        "$rootDir\tools\cloudflared.exe",
        "cloudflared.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $CloudflaredPath = $c; break }
    }
}

if (-not $CloudflaredPath -or -not (Test-Path $CloudflaredPath)) {
    Write-Host "[ERROR] cloudflared.exe not found!" -ForegroundColor Red
    Write-Host "Download from: https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -ForegroundColor Yellow
    exit 1
}

Write-Host "[Tunnel] Starting cloudflared tunnel for http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "[Tunnel] Binary: $CloudflaredPath" -ForegroundColor Cyan

$logFile = "$logDir\laura_tunnel_windows.log"
"--- Tunnel started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ---" | Out-File -FilePath $logFile

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $CloudflaredPath
$psi.Arguments = "tunnel --url http://127.0.0.1:$Port --no-autoupdate"
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)

$callbackPath = if ($env:LAURA_WEBHOOK_PATH) { $env:LAURA_WEBHOOK_PATH } else { "/webhook/shopee" }

$reader = $proc.StandardOutput
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$timeout = 30000

while (-not $reader.EndOfStream -and $timer.ElapsedMilliseconds -lt $timeout) {
    $line = $reader.ReadLine()
    Add-Content -Path $logFile -Value $line
    Write-Host $line -ForegroundColor Gray

    if ($line -match 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com') {
        $tunnelUrl = $matches[0]
        $callbackUrl = "$tunnelUrl$callbackPath"
        $tunnelUrl | Out-File -FilePath $latestUrlFile
        $callbackUrl | Out-File -FilePath $latestCallbackFile
        Write-Host ""
        Write-Host "[TUNNEL URL] $tunnelUrl" -ForegroundColor Green
        Write-Host "[CALLBACK URL] $callbackUrl" -ForegroundColor Green
        Write-Host ""
        Write-Host "To register webhook: python -m shopee_agent.shopee_webhook register" -ForegroundColor Cyan
        $timer.Reset()
        break
    }
}

while (-not $reader.EndOfStream) {
    $line = $reader.ReadLine()
    Add-Content -Path $logFile -Value $line
}

$proc.WaitForExit()
Write-Host "[Tunnel] Process exited with code $($proc.ExitCode)" -ForegroundColor Red
