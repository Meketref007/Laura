param(
    [string]$InstallDir = $(Join-Path $env:LOCALAPPDATA "Laura"),
    [switch]$FullUninstall
)

$ErrorActionPreference = "Continue"
$codeDir = Join-Path $InstallDir "code"

Write-Host "=== Laura Uninstaller ===" -ForegroundColor Green
Write-Host "Instalacao: $InstallDir"

if (-not (Test-Path $InstallDir)) {
    Write-Host "Nada para desinstalar (pasta nao existe)." -ForegroundColor Yellow
    exit 0
}

# 1. Para servicos
if (Test-Path "$codeDir\scripts\laura-services.ps1") {
    Write-Host "Parando servicos..."
    & "$codeDir\scripts\laura-services.ps1" stop *> $null
}
Start-Sleep -Seconds 2

# 2. Remove tarefas agendadas
schtasks /Delete /TN "Laura Update" /F 2>$null | Out-Null
Write-Host "Tarefa 'Laura Update' removida."

# 3. Atalhos
$wsh = New-Object -ComObject WScript.Shell
$startupDir = [Environment]::GetFolderPath("Startup")
Get-ChildItem $startupDir -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
    $lnk = $wsh.CreateShortcut($_.FullName)
    if ($lnk.TargetPath -match "wscript" -and $lnk.Arguments -match "iniciar_laura\.vbs") {
        Remove-Item $_.FullName -Force
        Write-Host "Atalho do Startup removido: $($_.Name)"
    }
}
$menuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Laura"
if (Test-Path $menuDir) {
    Remove-Item $menuDir -Recurse -Force
    Write-Host "Menu Iniciar 'Laura' removido."
}
if (Test-Path (Join-Path $InstallDir "iniciar_laura.vbs")) {
    Remove-Item (Join-Path $InstallDir "iniciar_laura.vbs") -Force
}

# 4. Dados
if ($FullUninstall) {
    Remove-Item $InstallDir -Recurse -Force
    Write-Host "Removido por completo (codigo, venv, .env, secrets, relatorios)." -ForegroundColor Red
} else {
    # mantem dados (logs, secrets, reports, backups, .env, data) e codigo
    Remove-Item (Join-Path $codeDir ".venv") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $codeDir ".git") -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $codeDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Ambiente (venv/git/cache) removidos." -ForegroundColor Yellow
    Write-Host "Seus DADOS e codigo foram mantidos em: $codeDir" -ForegroundColor Yellow
    Write-Host "Para apagar tudo: powershell -File installer\uninstall.ps1 -FullUninstall" -ForegroundColor Yellow
}

Write-Host "=== Desinstalacao concluida ===" -ForegroundColor Green
