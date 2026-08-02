param(
    [switch]$Quiet,
    [switch]$SkipRestart
)

$ErrorActionPreference = "Continue"

if ($env:LAURA_HOME) {
    $codeDir = $env:LAURA_HOME
} else {
    $codeDir = Join-Path $env:LOCALAPPDATA "Laura\code"
}
$logDir = Join-Path $codeDir "logs"
$logFile = Join-Path $logDir "laura-update.log"
$lockFile = Join-Path $logDir "laura-update.lock"

if (-not (Test-Path $codeDir)) { exit 1 }
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log($msg) {
    "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}
function Say($msg) {
    Write-Log $msg
    if (-not $Quiet) { Write-Host $msg }
}

# Lock simples para nao rodar 2 updates ao mesmo tempo (boot + daily)
$lock = $null
try {
    $lock = [System.IO.File]::Open($lockFile, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    Say "[update] Ja existe um update em andamento (lock). Abortando."
    exit 0
}

try {
    if (-not (Test-Path (Join-Path $codeDir ".git"))) {
        Say "[update] $codeDir nao e um repo git. Reinstale: installer\install.ps1"
        exit 1
    }

    Say "[update] Verificando atualizacoes..."
    git -C $codeDir fetch origin main 2>$null
    if ($LASTEXITCODE -ne 0) {
        Say "[update] git fetch falhou (sem rede? repo removido?). Nada foi alterado."
        exit 1
    }

    $local = (git -C $codeDir rev-parse HEAD).Trim()
    $remote = (git -C $codeDir rev-parse origin/main).Trim()
    if ($local -eq $remote) {
        Say "[update] Ja atualizado ($($local.Substring(0, 7)))."
        exit 0
    }

    $shortLocal = $local.Substring(0, 7)
    $shortRemote = $remote.Substring(0, 7)
    $filesChanged = @(git -C $codeDir diff --name-only $local..$remote)
    $depsChanged = @($filesChanged | Where-Object { $_ -match "^(pyproject\.toml|requirements.*\.txt)$" })

    Say "[update] Nova versao disponivel: $shortLocal -> $shortRemote ($($filesChanged.Count) arquivos)"

    if (-not $SkipRestart) {
        Say "[update] Parando servicos..."
        & "$codeDir\scripts\laura-services.ps1" stop *> $null
    }

    git -C $codeDir pull --ff-only origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Say "[update] git pull FALHOU. Restaurando servicos..."
        if (-not $SkipRestart) { & "$codeDir\scripts\laura-services.ps1" start *> $null }
        exit 1
    }

    if ($depsChanged.Count -gt 0) {
        Say "[update] Dependencias mudaram ($($depsChanged -join ', ')). Reinstalando..."
        & (Join-Path $codeDir ".venv\Scripts\python.exe") -m pip install -e . -q 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Say "[update] Dependencias reinstaladas." }
        else { Say "[update] WARN: pip install -e . falhou. Ajuste manual necessario." }
    }

    if (-not $SkipRestart) {
        Say "[update] Reiniciando servicos..."
        & "$codeDir\scripts\laura-services.ps1" start *> $null
    }

    Say "[update] Concluido: Laura atualizada para $shortRemote."
} finally {
    $lock.Close()
    $lock.Dispose()
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}
