@echo off
rem Laura CLI - atalho para o ambiente instalado
set "VENVPY=%LOCALAPPDATA%\Laura\code\.venv\Scripts\python.exe"
if not exist "%VENVPY%" (
    echo Laura nao instalada. Rode o instalador:
    echo   powershell -ExecutionPolicy Bypass -File installer\install.ps1
    pause
    exit /b 1
)
"%VENVPY%" -m shopee_agent.cli %*
