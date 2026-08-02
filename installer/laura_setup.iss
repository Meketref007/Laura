; Laura - Setup (Inno Setup)
; Compile: powershell -File build_setup.ps1  (baixa o Inno se necessario)

#ifndef AppVersion
#define AppVersion "3.1.0"
#endif
#define AppName "Laura"
#define AppPublisher "Meketref"

[Setup]
AppId={{8C4F2E9A-3B61-4D7A-9E54-0A7F2C8B5D11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Laura
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Laura-Setup-{#AppVersion}
SetupIconFile=laura_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
; codigo completo (sem .git/.venv/dados - dados sao migrados ou criados na 1a execucao)
Source: "..\*"; DestDir: "{app}\code"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: ".git,.venv,logs,backups,reports,data,secrets,tests,.pytest_cache,__pycache__,*.pyc,*.pyo,dist,htmlcov,.env,.coverage,*.log,*.db,*.pid"

[Icons]
Name: "{userprograms}\Laura\Painel de Controle"; Filename: "{app}\code\.venv\Scripts\pythonw.exe"; Parameters: """{app}\code\installer\laura_painel.pyw"""; IconFilename: "{app}\code\installer\laura_icon.ico"; WorkingDir: "{app}\code"
Name: "{userprograms}\Laura\Laura CLI"; Filename: "{app}\code\installer\laura.cmd"; IconFilename: "{app}\code\installer\laura_icon.ico"; WorkingDir: "{app}\code"
Name: "{userdesktop}\Laura Painel"; Filename: "{app}\code\.venv\Scripts\pythonw.exe"; Parameters: """{app}\code\installer\laura_painel.pyw"""; IconFilename: "{app}\code\installer\laura_icon.ico"; WorkingDir: "{app}\code"

[Tasks]
Name: "models"; Description: "Baixar modelos do Ollama (moondream + llama3.2:3b, ~4 GB)"; GroupDescription: "Extras:"
Name: "playwright"; Description: "Instalar browser do Playwright (auto-login Seller Center, ~150 MB)"; GroupDescription: "Extras:"

[Run]
; 1a execucao: venv, dependencias, migracao de dados, agendamento, boot, servicos
Filename: "powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\code\installer\install.ps1"" -SkipClone -Force -NoShortcut -InstallDir ""{app}"""; StatusMsg: "Configurando Laura (venv, dependencias, dados, agendamento)..."; Flags: waituntilterminated runhidden
; extras opcionais marcados pelo usuario
Filename: "powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\code\scripts\laura-extra-setup.ps1"" -Models"; Tasks: models; StatusMsg: "Baixando modelos do Ollama..."; Flags: waituntilterminated runhidden
Filename: "powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\code\scripts\laura-extra-setup.ps1"" -Playwright"; Tasks: playwright; StatusMsg: "Instalando browser do Playwright..."; Flags: waituntilterminated runhidden
; abrir o painel ao final (checkbox opcional)
Filename: "{app}\code\.venv\Scripts\pythonw.exe"; Parameters: """{app}\code\installer\laura_painel.pyw"""; Description: "Abrir o Painel de Controle da Laura"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; para servicos + remove tarefa agendada + VBS de boot (dados sao mantidos)
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""& '{app}\code\scripts\laura-services.ps1' stop; schtasks /Delete /TN 'Laura Update' /F 2>$null | Out-Null; schtasks /Delete /TN 'Laura Backup' /F 2>$null | Out-Null; Remove-Item -LiteralPath '{app}\iniciar_laura.vbs' -Force -ErrorAction SilentlyContinue"""; Flags: runhidden; RunOnceId: "laura-uninstall-cleanup"

[UninstallDelete]
; remove venv e git, mantem dados (logs, secrets, reports, backups, .env)
Type: filesandordirs; Name: "{app}\code\.venv"
Type: filesandordirs; Name: "{app}\code\.git"
