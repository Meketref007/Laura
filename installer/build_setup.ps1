param(
    [string]$OutDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "dist")
)

$ErrorActionPreference = "Stop"
$issDir = $PSScriptRoot
Set-Location $issDir

# ---------- 0. Versao (fonte unica: pyproject.toml) ----------
$pyproject = Join-Path (Split-Path $issDir -Parent) "pyproject.toml"
$version = (Select-String -Path $pyproject -Pattern '^version\s*=\s*"([^"]+)"').Matches.Groups[1].Value
if (-not $version) { Write-Host "ERRO: versao nao encontrada em pyproject.toml" -ForegroundColor Red; exit 1 }
Write-Host "Versao: $version"

Write-Host "=== Build do Setup da Laura ($version) ===" -ForegroundColor Green

# ---------- 1. Icone (PIL - usa o venv da Laura instalada ou qualquer python com pillow) ----------
$venvPy = Join-Path $env:LOCALAPPDATA "Laura\code\.venv\Scripts\python.exe"
$py = if (Test-Path $venvPy) { $venvPy } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Host "ERRO: python nao encontrado." -ForegroundColor Red; exit 1 }

$iconScript = Join-Path $env:TEMP "laura_make_icon.py"
@'
from PIL import Image, ImageDraw, ImageFont
import os
import sys

SIZE = 512
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

top, bottom = (26, 91, 180), (12, 52, 110)
for y in range(SIZE):
    t = y / SIZE
    c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    d.line([(0, y), (SIZE, y)], fill=c + (255,))

radius = 110
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=radius, outline=(255, 255, 255, 40), width=2)

font_paths = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf"]
font = None
for fp in font_paths:
    if os.path.exists(fp):
        font = ImageFont.truetype(fp, 330)
        break
if font is None:
    font = ImageFont.load_default()

bbox = d.textbbox((0, 0), "L", font=font)
w = bbox[2] - bbox[0]
h = bbox[3] - bbox[1]
d.text(((SIZE - w) / 2, (SIZE - h) / 2 - bbox[1]), "L", font=font, fill=(255, 255, 255, 255))

out_ico = sys.argv[1]
img.save(out_ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icone: " + out_ico)
'@ | Out-File -FilePath $iconScript -Encoding UTF8

$iconOut = Join-Path $issDir "laura_icon.ico"
& $py $iconScript $iconOut
if (-not (Test-Path $iconOut)) {
    Write-Host "ERRO: falha ao gerar o icone (PIL instalado?). pip install pillow" -ForegroundColor Red
    exit 1
}
Write-Host "OK: icone gerado"

# ---------- 2. Inno Setup (ISCC) ----------
$isccPath = $null
$found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($found) { $isccPath = $found.Source }
if (-not $isccPath) {
    $cands = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Laura\innosetup\ISCC.exe")
    )
    $isccPath = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $isccPath) {
    Write-Host "Baixando Inno Setup..."
    $dl = Join-Path $env:TEMP "inno-setup.exe"
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe" -OutFile $dl
    $instDir = Join-Path $env:LOCALAPPDATA "Laura\innosetup"
    Write-Host "Instalando Inno Setup em $instDir (silencioso)..."
    Start-Process -FilePath $dl -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$instDir`"" -Wait
    $isccPath = Join-Path $instDir "ISCC.exe"
}
if (-not (Test-Path $isccPath)) { Write-Host "ERRO: ISCC nao encontrado em $isccPath" -ForegroundColor Red; exit 1 }
Write-Host "OK: Inno Setup em $isccPath"

# ---------- 3. Compilar ----------
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
Write-Host "Compilando Setup.exe (versao $version)..."
& $isccPath "/DAppVersion=$version" "laura_setup.iss"
if ($LASTEXITCODE -ne 0) { Write-Host "ERRO: ISCC falhou (codigo $LASTEXITCODE)" -ForegroundColor Red; exit 1 }

$setup = Get-ChildItem $OutDir -Filter "Laura-Setup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($setup) {
    Write-Host "=== Setup gerado: $($setup.FullName) ($([math]::Round($setup.Length/1MB,1)) MB) ===" -ForegroundColor Green
} else {
    Write-Host "WARN: nenhum Setup encontrado em $OutDir" -ForegroundColor Yellow
}
