param(
    [string]$From = "",
    [switch]$NoStop,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"

if ($env:LAURA_HOME) {
    $codeDir = $env:LAURA_HOME
} else {
    $codeDir = Join-Path $env:LOCALAPPDATA "Laura\code"
}
$logFile = Join-Path $codeDir "logs\laura-restore.log"

function Write-Log($msg) {
    "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
    if (-not $Quiet) { Write-Host $msg }
}

if (-not (Test-Path $codeDir)) {
    Write-Log "[restore] ERRO: $codeDir nao existe"
    exit 1
}
$logDir = Join-Path $codeDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

# resolve a pasta de backup: -From explicito, ou a mais recente em backups\daily
$dailyDir = Join-Path $codeDir "backups\daily"
if (-not $From) {
    if (-not (Test-Path $dailyDir)) {
        Write-Log "[restore] ERRO: nenhum backup encontrado em $dailyDir (rode laura-backup.ps1 antes)"
        exit 1
    }
    $From = (Get-ChildItem $dailyDir -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
}
if (-not (Test-Path $From)) {
    Write-Log "[restore] ERRO: backup nao encontrado: $From"
    exit 1
}

Write-Log "[restore] Restaurando a partir de: $From"

if (-not $NoStop) {
    Write-Log "[restore] Parando servicos..."
    & "$codeDir\scripts\laura-services.ps1" stop *> $null
    Start-Sleep -Seconds 2
}

$items = @("reports", "data", "secrets", "logs")
$restored = 0
foreach ($item in $items) {
    $src = Join-Path $From $item
    if (Test-Path $src) {
        $dest = Join-Path $codeDir $item
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue }
        Copy-Item -Path $src -Destination $codeDir -Recurse -Force -ErrorAction SilentlyContinue
        $restored++
        Write-Log "[restore] restaurado: $item"
    } else {
        Write-Log "[restore] ignorado (nao estava no backup): $item"
    }
}

if (-not $NoStop) {
    Write-Log "[restore] Reiniciando servicos..."
    & "$codeDir\scripts\laura-services.ps1" start *> $null
}

if ($restored -eq 0) {
    Write-Log "[restore] ERRO: o backup nao continha nenhum item restauravel"
    exit 1
}

Write-Log "[restore] concluido: $restored item(ns) restaurado(s) de $From"
