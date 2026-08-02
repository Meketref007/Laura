param(
    [switch]$Models,
    [switch]$Playwright
)

$ErrorActionPreference = "Continue"

if ($env:LAURA_HOME) {
    $codeDir = $env:LAURA_HOME
} else {
    $codeDir = Join-Path $env:LOCALAPPDATA "Laura\code"
}
$logDir = Join-Path $codeDir "logs"
$logFile = Join-Path $logDir "laura-extra-setup.log"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log($msg) {
    "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Host $msg
}

if ($Models) {
    $ollamaBin = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaBin) {
        Write-Log "[extra] WARN: ollama nao encontrado. Instale em https://ollama.com"
    } else {
        $installed = & $ollamaBin.Source list 2>$null
        foreach ($model in @("moondream", "llama3.2:3b")) {
            if ($installed -match [regex]::Escape($model)) {
                Write-Log "[extra] modelo ja instalado: $model"
            } else {
                Write-Log "[extra] baixando $model..."
                & $ollamaBin.Source pull $model
                if ($LASTEXITCODE -eq 0) { Write-Log "[extra] OK: $model" } else { Write-Log "[extra] WARN: falha em $model" }
            }
        }
    }
}

if ($Playwright) {
    $venvPython = Join-Path $codeDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        Write-Log "[extra] instalando browser do Playwright (chromium)..."
        & $venvPython -m playwright install chromium
        if ($LASTEXITCODE -eq 0) { Write-Log "[extra] OK: playwright chromium" } else { Write-Log "[extra] WARN: playwright falhou" }
    } else {
        Write-Log "[extra] WARN: venv nao encontrado em $venvPython"
    }
}

if (-not $Models -and -not $Playwright) {
    Write-Host "Uso: laura-extra-setup.ps1 [-Models] [-Playwright]"
}
Write-Log "[extra] concluido"
