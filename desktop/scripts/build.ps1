# Build TDL Desktop as a portable ("green") zip: engine (PyInstaller) + Tauri shell.
#
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\build.ps1
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\build.ps1 -SkipEngine
#   powershell -ExecutionPolicy Bypass -File desktop\scripts\build.ps1 -Installer   # NSIS installer instead
param(
    [string]$Python = "",
    [switch]$SkipEngine,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
$desktop = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $desktop
$tauri = Join-Path $desktop "src-tauri"
$sidecar = Join-Path $tauri "binaries\tdl-x86_64-pc-windows-msvc.exe"
$version = (Get-Content (Join-Path $tauri "tauri.conf.json") -Raw -Encoding UTF8 | ConvertFrom-Json).version

# rustup adds cargo to PATH only for terminals opened after installation.
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    $env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
}

if (-not $Python) {
    $venv = Join-Path $root ".venv-peer-fix\Scripts\python.exe"
    $Python = if (Test-Path $venv) { $venv } else { "python" }
}

if (-not $SkipEngine) {
    Write-Host "==> Building engine with $Python" -ForegroundColor Cyan
    Push-Location $root
    try {
        & $Python -m PyInstaller --clean --noconfirm `
            --distpath build\desktop-engine --workpath build\pyi-desktop media_downloader.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
    } finally {
        Pop-Location
    }
    New-Item -ItemType Directory -Force (Split-Path $sidecar) | Out-Null
    Copy-Item (Join-Path $root "build\desktop-engine\tdl.exe") $sidecar -Force
}

if (-not (Test-Path $sidecar)) {
    throw "Engine sidecar missing: $sidecar (run without -SkipEngine)"
}

Write-Host "==> Building desktop app" -ForegroundColor Cyan
Push-Location $desktop
try {
    if (-not (Test-Path node_modules)) { npm install }
    if ($Installer) { npx tauri build } else { npx tauri build --no-bundle }
    if ($LASTEXITCODE -ne 0) { throw "tauri build failed" }
} finally {
    Pop-Location
}

if ($Installer) {
    Write-Host "==> Installer:" -ForegroundColor Green
    Get-ChildItem (Join-Path $tauri "target\release\bundle\nsis") -Filter *.exe | ForEach-Object { Write-Host "    $($_.FullName)" }
    return
}

$name = "TDL-Desktop-v$version-portable-x64"
$out = Join-Path $desktop "release"
$folder = Join-Path $out $name
if (Test-Path $folder) { Remove-Item $folder -Recurse -Force }
New-Item -ItemType Directory -Force $folder | Out-Null

Copy-Item (Join-Path $tauri "target\release\tdl-desktop.exe") (Join-Path $folder "TDL Desktop.exe")
Copy-Item $sidecar (Join-Path $folder "tdl.exe")
Copy-Item (Join-Path $desktop "scripts\portable.txt") (Join-Path $folder "portable.txt")

$zip = Join-Path $out "$name.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $folder "*") -DestinationPath $zip
Write-Host "==> Portable build:" -ForegroundColor Green
Write-Host "    $folder"
Write-Host "    $zip"
