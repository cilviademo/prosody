<#
.SYNOPSIS
    Build the Prosody Windows release: portable ZIP and NSIS installer.

.DESCRIPTION
    Run from a plain PowerShell on the studio PC. Needs Python 3.10+, Node 18+
    and Rust (msvc) on PATH. Everything else is fetched or built here.

.EXAMPLE
    .\scripts\build-release.ps1
    .\scripts\build-release.ps1 -SkipCore    # reuse an existing core build
#>
[CmdletBinding()]
param(
    [switch]$SkipCore,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$repo    = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $repo "apps\desktop"
$tauri   = Join-Path $desktop "src-tauri"
Set-Location $repo

function Require($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name was not found on PATH. $hint"
    }
}

Write-Host "== Prerequisites ==" -ForegroundColor Cyan
Require "python" "Install Python 3.10 or newer from python.org."
Require "npm"    "Install Node.js 18 or newer from nodejs.org."
Require "cargo"  "Install Rust from rustup.rs."

# -- 1. the core ------------------------------------------------------------
if (-not $SkipCore) {
    Write-Host "== Building the core (PyInstaller, onedir) ==" -ForegroundColor Cyan
    if (-not (Test-Path ".venv")) { python -m venv .venv }
    & ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    & ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller
    & ".venv\Scripts\python.exe" -m PyInstaller prosody-core.spec --noconfirm --clean

    # -- 2. into the Tauri resources ---------------------------------------
    $dest = Join-Path $tauri "resources\prosody-core"
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-Item "dist\prosody-core\*" $dest -Recurse -Force

    $coreExe = Join-Path $dest "prosody-core.exe"
    if (-not (Test-Path $coreExe)) { throw "the core did not build: $coreExe missing" }

    Write-Host "   Verifying the core answers ping..." -ForegroundColor DarkGray
    $reply = '{"id":1,"method":"ping"}' | & $coreExe
    if ($reply -notmatch '"ok":\s*true') {
        throw "the built core did not answer ping: $reply"
    }
    Write-Host "   $reply" -ForegroundColor DarkGray
}

# -- 3. the app -------------------------------------------------------------
Write-Host "== Building the desktop app ==" -ForegroundColor Cyan
Set-Location $desktop
if (Test-Path "package-lock.json") { npm ci } else { npm install }
if ($SkipInstaller) { npm run build; npx tauri build --no-bundle }
else { npm run tauri build }
Set-Location $repo

# -- 4. the portable ZIP ----------------------------------------------------
Write-Host "== Assembling the portable ZIP ==" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "make-portable.ps1")

# -- 5. say exactly where everything is ------------------------------------
$conf    = Get-Content (Join-Path $tauri "tauri.conf.json") -Raw | ConvertFrom-Json
$version = $conf.version
$release = Join-Path $repo "release"

Write-Host ""
Write-Host "== Done ==" -ForegroundColor Green
Write-Host ("Prosody.exe : " + (Join-Path $tauri "target\release\Prosody.exe"))
Write-Host ("Portable    : " + (Join-Path $release "Prosody-v$version-Windows.zip"))

$nsis = Join-Path $tauri "target\release\bundle\nsis"
if (Test-Path $nsis) {
    Get-ChildItem $nsis -Filter *.exe | ForEach-Object {
        $target = Join-Path $release $_.Name
        Copy-Item $_.FullName $target -Force
        Write-Host ("Installer   : " + $target)
    }
    # Refresh checksums now that the installer is in place.
    Get-ChildItem $release -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
        ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name } |
        Set-Content (Join-Path $release "SHA256SUMS.txt") -Encoding UTF8
} else {
    Write-Host "Installer   : not produced (bundling skipped)" -ForegroundColor Yellow
}
Write-Host ("Checksums   : " + (Join-Path $release "SHA256SUMS.txt"))
