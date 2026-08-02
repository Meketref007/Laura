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
    $range = "$local..$remote"
    $filesChanged = @(git -C $codeDir diff --name-only $range 2>$null)
    $depsChanged = @($filesChanged | Where-Object { $_ -match "^(pyproject\.toml|requirements.*\.txt)$" })

    Say "[update] Nova versao disponivel: $shortLocal -> $shortRemote ($($filesChanged.Count) arquivos)"

    if (-not $SkipRestart) {
        Say "[update] Parando servicos..."
        & "$codeDir\scripts\laura-services.ps1" stop *> $null
    }

    # Remove untracked locais que colidem com arquivos versionados no repo
    # (ex.: artefatos gerados localmente que viraram parte do projeto).
    # NUNCA toca em dados gitignorados (.env, secrets, data, reports, backups, logs).
    $remoteFiles = @(git -C $codeDir ls-tree -r --name-only origin/main 2>$null)
    $untracked = @(git -C $codeDir ls-files --others --exclude-standard 2>$null)
    foreach ($f in $untracked) {
        if ($remoteFiles -contains $f) {
            Say "[update] Removendo arquivo local que colide com o repo: $f"
            Remove-Item (Join-Path $codeDir $f) -Force -ErrorAction SilentlyContinue
        }
    }

    git -C $codeDir pull --ff-only origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Say "[update] Primeiro pull falhou; normalizando repositorio local e tentando de novo..."
        # Descarta mudancas locais em arquivos rastreados (a instalacao espelha o repo).
        # Dados locais (.env, secrets, data, reports, backups, logs) sao untracked/ignorados e NAO sao tocados.
        git -C $codeDir checkout -- . 2>&1 | Out-Null
        $crlf = git -C $codeDir config core.autocrlf
        if ($crlf -eq "true") {
            Say "[update] core.autocrlf=true detectado; trocando para false (evita falsos modificados por CRLF)"
            git -C $codeDir config core.autocrlf false
            git -C $codeDir checkout -- . 2>&1 | Out-Null
        }
        git -C $codeDir pull --ff-only origin main 2>&1 | Out-Null
    }
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
