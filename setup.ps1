<#
.SYNOPSIS
    One-command setup and start for Laura Shopee Agent
.DESCRIPTION
    Checks environment, installs dependencies, ensures Ollama + models,
    and starts all services. Run with: powershell -ExecutionPolicy Bypass -File setup.ps1
#>

param(
    [switch]$Docker,
    [switch]$NoOllama
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSCommandPath
Set-Location $rootDir

Write-Host "=== Laura Agent Setup ===" -ForegroundColor Cyan

if ($Docker) {
    Write-Host "[Docker mode]" -ForegroundColor Yellow
    docker compose up --build -d
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Containers started! Use 'docker compose logs -f' to follow." -ForegroundColor Green
    }
    exit
}

# --- Python check ---
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python not found! Install Python 3.12+ from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python: $($py.Source)" -ForegroundColor Green

# --- Install pip deps ---
if (Test-Path requirements.txt) {
    Write-Host "Installing dependencies..."
    pip install -r requirements.txt
} else {
    Write-Host "Installing core dependencies..."
    pip install requests python-dotenv websocket-client
}

# --- Ollama check ---
if (-not $NoOllama) {
    $ollamaExe = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaExe) {
        Write-Host "Ollama not found! Download from https://ollama.com" -ForegroundColor Yellow
        Write-Host "After installing, run this script again." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] Ollama: $($ollamaExe.Source)" -ForegroundColor Green
    
    # Check if Ollama is running
    $ollamaRunning = $false
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($r.StatusCode -eq 200) { $ollamaRunning = $true }
    } catch {}
    
    if (-not $ollamaRunning) {
        Write-Host "Starting Ollama..." -ForegroundColor Yellow
        Start-Process -WindowStyle Hidden -FilePath "ollama.exe" -ArgumentList "serve"
        Start-Sleep -Seconds 5
    }
    
    # Download models via LLM manager
    Write-Host "Checking LLM models..."
    python -c "from shopee_agent.llm_manager import garantir_todos_modelos; garantir_todos_modelos()"
}

# --- .env check ---
if (-not (Test-Path .env)) {
    Write-Host "ERROR: .env file not found! Create it from .env.example" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] .env found" -ForegroundColor Green

# --- Kill old processes ---
Get-WmiObject Win32_Process -Filter "Name like '%pythonw.exe%'" | Where-Object { $_.CommandLine -match 'laura_daemon|telegram-bot|webhook-start' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# --- Start services ---
Write-Host "Starting services..." -ForegroundColor Cyan
Start-Process -WindowStyle Hidden -FilePath "pythonw.exe" -ArgumentList "-m shopee_agent.cli webhook-start --host 0.0.0.0 --port 8766"
Start-Process -WindowStyle Hidden -FilePath "pythonw.exe" -ArgumentList "-m shopee_agent.cli telegram-bot"
Start-Process -WindowStyle Hidden -FilePath "pythonw.exe" -ArgumentList "laura_daemon.pyw"

Start-Sleep -Seconds 10

# --- Verify ---
$procs = Get-WmiObject Win32_Process -Filter "Name like '%pythonw.exe%'" | Where-Object { $_.CommandLine -match 'laura_daemon|telegram-bot|webhook-start' }
Write-Host "Running processes: $($procs.Count)" -ForegroundColor Cyan
foreach ($p in $procs) {
    $name = if ($p.CommandLine -match 'laura_daemon') { "daemon" } elseif ($p.CommandLine -match 'telegram-bot') { "telegram" } else { "webhook" }
    Write-Host "  [$name] PID $($p.ProcessId)" -ForegroundColor Green
}

try {
    $webhookStatus = (Invoke-WebRequest -Uri "http://127.0.0.1:8766/health" -TimeoutSec 5 -ErrorAction SilentlyContinue).StatusCode
    Write-Host "[OK] Webhook: HTTP $webhookStatus" -ForegroundColor Green
} catch {
    Write-Host "[WARN] Webhook health check failed" -ForegroundColor Yellow
}

Write-Host "`nLaura is running! Use 'setup.ps1 -Docker' for Docker mode." -ForegroundColor Cyan
