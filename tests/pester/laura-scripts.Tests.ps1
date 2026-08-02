# Testes Pester dos scripts PowerShell do instalador/updater

$ErrorActionPreference = "Stop"

BeforeAll {
    $script:repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$scripts = @(
    "scripts\laura-services.ps1",
    "scripts\laura-update.ps1",
    "scripts\laura-backup.ps1",
    "scripts\laura-extra-setup.ps1",
    "scripts\laura_watchdog.ps1",
    "installer\install.ps1",
    "installer\uninstall.ps1",
    "installer\build_setup.ps1"
)

Describe "Scripts PowerShell - sintaxe" {
    It "todos os scripts compilam sem erros de parser" {
        foreach ($s in $scripts) {
            $path = Join-Path $script:repoRoot $s
            $path | Should -Exist
            $tokens = $null
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
            $errors.Count | Should -Be 0 -Because "erros de sintaxe em $s"
        }
    }
}

Describe "install.ps1" {
    It "tem os parametros esperados" {
        $content = Get-Content (Join-Path $script:repoRoot "installer\install.ps1") -Raw
        foreach ($p in @("SkipClone", "InstallModels", "Force", "NoShortcut", "InstallDir")) {
            $content | Should -Match ("\`$$p\b") -Because "parametro -$p"
        }
    }
    It "agenda update e backup" {
        $content = Get-Content (Join-Path $script:repoRoot "installer\install.ps1") -Raw
        $content | Should -Match "Laura Update"
        $content | Should -Match "Laura Backup"
    }
}

Describe "laura_setup.iss (Inno Setup)" {
    It "contem as secoes obrigatorias" {
        $iss = Get-Content (Join-Path $script:repoRoot "installer\laura_setup.iss") -Raw
        foreach ($section in @("[Setup]", "[Files]", "[Icons]", "[Tasks]", "[Run]", "[UninstallRun]")) {
            $iss | Should -Match ([regex]::Escape($section)) -Because "secao $section"
        }
    }
    It "usa a versao via preprocessor (define externo)" {
        $iss = Get-Content (Join-Path $script:repoRoot "installer\laura_setup.iss") -Raw
        $iss | Should -Match "ifndef AppVersion"
    }
}

Describe "laura_watchdog.ps1" {
    It "nao abre navegador sem opt-in (-CdpAutoLaunch)" {
        $content = Get-Content (Join-Path $script:repoRoot "scripts\laura_watchdog.ps1") -Raw
        $content | Should -Match "CdpAutoLaunch"
    }
    It "adota daemon existente (evita duplicados)" {
        $content = Get-Content (Join-Path $script:repoRoot "scripts\laura_watchdog.ps1") -Raw
        $content | Should -Match "Find-RunningDaemon"
    }
    It "alerta via Telegram em crash loop" {
        $content = Get-Content (Join-Path $script:repoRoot "scripts\laura_watchdog.ps1") -Raw
        $content | Should -Match "Send-TelegramAlert"
    }
}

Describe "laura-update.ps1" {
    It "usa lock e git pull --ff-only" {
        $content = Get-Content (Join-Path $script:repoRoot "scripts\laura-update.ps1") -Raw
        $content | Should -Match "laura-update.lock"
        $content | Should -Match "pull --ff-only"
    }
}
