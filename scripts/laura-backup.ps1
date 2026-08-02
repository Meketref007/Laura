param(
    [int]$KeepDays = 7,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"

if ($env:LAURA_HOME) {
    $codeDir = $env:LAURA_HOME
} else {
    $codeDir = Join-Path $env:LOCALAPPDATA "Laura\code"
}
$logFile = Join-Path $codeDir "logs\laura-backup.log"

function Write-Log($msg) {
    "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
    if (-not $Quiet) { Write-Host $msg }
}

if (-not (Test-Path $codeDir)) {
    Write-Log "[backup] ERRO: $codeDir nao existe"
    exit 1
}
$logDir = Join-Path $codeDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$dest = Join-Path $codeDir "backups\daily\$stamp"
# cria o destino ANTES: sem isso, o Copy-Item achata o conteudo (ex.: reports) na raiz do backup
New-Item -ItemType Directory -Path $dest -Force | Out-Null

$items = @("reports", "data", "secrets", "logs")
foreach ($item in $items) {
    $src = Join-Path $codeDir $item
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "[backup] copiado: $item"
    }
}

# rotacao: mantem apenas os $KeepDays mais recentes
$dailyDir = Join-Path $codeDir "backups\daily"
if (Test-Path $dailyDir) {
    $all = Get-ChildItem $dailyDir -Directory | Sort-Object Name -Descending
    $toDelete = $all | Select-Object -Skip $KeepDays
    foreach ($d in $toDelete) {
        Remove-Item $d.FullName -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "[backup] removido (antigo): $($d.Name)"
    }
    Write-Log "[backup] rotacao: mantidos $($all.Count - $toDelete.Count) de $($all.Count)"
}

Write-Log "[backup] concluido em $dest"
