param(
    [Parameter(Mandatory = $true)]
    [string]$CommitMessage,

    [string]$CommitBody = "",
    [string]$SpecPath = "media_downloader.spec",
    [switch]$SkipTests,
    [switch]$FullTests,
    [switch]$CleanBuild,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    Write-Host ">> $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

if (-not $SkipTests) {
    $testModules = @(
        "tests.module.test_clash_controller",
        "tests.module.test_download_stat",
        "tests.module.test_native_ui",
        "tests.module.test_app",
        "tests.module.test_resilience"
    )

    if ($FullTests) {
        $testModules = @(
            "tests.module.test_bot_status",
            "tests.module.test_clash_controller",
            "tests.module.test_download_stat",
            "tests.module.test_resilience",
            "tests.module.test_app",
            "tests.module.test_app_recovery",
            "tests.module.test_existing_file_recovery",
            "tests.module.test_filter_gui_mode",
            "tests.module.test_history_timeout",
            "tests.module.test_native_ui",
            "tests.module.test_scan_prefetch",
            "tests.utils.test_format"
        )
    }

    $testArgs = @(
        "-m",
        "unittest"
    ) + $testModules
    Invoke-Checked ".\.venv\Scripts\python.exe" $testArgs

    $compileModules = @(
        "media_downloader.py",
        "module\app.py",
        "module\bot.py",
        "module\download_stat.py",
        "module\pyrogram_extension.py",
        "module\clash_controller.py",
        "module\network_watchdog.py",
        "module\get_chat_history_v2.py",
        "module\native_ui.py",
        "module\filter.py",
        "gui_launcher.py"
    )

    if ($FullTests) {
        $compileModules += "module\web.py"
    }

    $compileArgs = @(
        "-m",
        "py_compile"
    ) + $compileModules
    Invoke-Checked ".\.venv\Scripts\python.exe" $compileArgs
}

if (-not $NoBuild) {
    $buildArgs = @(
        "-m",
        "PyInstaller",
        $SpecPath,
        "--noconfirm"
    )
    if ($CleanBuild) {
        $buildArgs += "--clean"
    }
    Invoke-Checked ".\.venv\Scripts\python.exe" $buildArgs
    if (-not (Test-Path "dist\tdl.exe")) {
        throw "Build output not found: dist\tdl.exe"
    }
    Write-Host "Created asset: dist\tdl.exe"
}

Invoke-Checked git @("add", "-A")

$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "No staged changes. Skipping commit."
    return
}

if ($CommitBody) {
    Invoke-Checked git @("commit", "-m", $CommitMessage, "-m", $CommitBody)
} else {
    Invoke-Checked git @("commit", "-m", $CommitMessage)
}

Write-Host "Done. No GitHub push or release was performed."
