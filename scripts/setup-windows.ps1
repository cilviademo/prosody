<#
.SYNOPSIS
    Sets up and launches Prosody on a Windows studio PC.

.DESCRIPTION
    Creates the Python virtualenv, installs the backend and the desktop
    dependencies, then either launches the app or builds an installer.

.PARAMETER Bundle
    Build a Windows installer instead of launching in development mode.

.EXAMPLE
    .\scripts\setup-windows.ps1
    .\scripts\setup-windows.ps1 -Bundle
#>
[CmdletBinding()]
param([switch]$Bundle)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Require($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name was not found on PATH. $hint"
    }
}

Write-Host "Checking prerequisites..." -ForegroundColor Cyan
Require "python" "Install Python 3.10 or newer from python.org."
Require "npm"    "Install Node.js 18 or newer from nodejs.org."
Require "cargo"  "Install Rust from rustup.rs (needed to build the window)."

$pythonVersion = (python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))")
Write-Host "  Python $pythonVersion" -ForegroundColor DarkGray

# --- backend --------------------------------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtualenv..." -ForegroundColor Cyan
    python -m venv .venv
}
Write-Host "Installing the Prosody backend..." -ForegroundColor Cyan
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".venv\Scripts\python.exe" -m pip install --quiet -e ".[dev]"

Write-Host "Checking the environment..." -ForegroundColor Cyan
& ".venv\Scripts\flpf.exe" doctor

# Point the desktop app at this interpreter so it does not have to guess.
$env:PROSODY_PYTHON = (Resolve-Path ".venv\Scripts\python.exe").Path

# --- desktop --------------------------------------------------------------
Set-Location "apps\desktop"
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing desktop dependencies..." -ForegroundColor Cyan
    npm install
}

if ($Bundle) {
    Write-Host "Building the Windows installer (this takes a few minutes)..." -ForegroundColor Cyan
    npm run bundle
    $nsis = Join-Path $repo "apps\desktop\src-tauri\target\release\bundle\nsis"
    $msi  = Join-Path $repo "apps\desktop\src-tauri\target\release\bundle\msi"
    Write-Host ""
    Write-Host "Installer written to:" -ForegroundColor Green
    if (Test-Path $nsis) { Get-ChildItem $nsis -Filter *.exe | ForEach-Object { Write-Host "  $($_.FullName)" } }
    if (Test-Path $msi)  { Get-ChildItem $msi  -Filter *.msi | ForEach-Object { Write-Host "  $($_.FullName)" } }
} else {
    Write-Host "Launching Prosody..." -ForegroundColor Green
    npm run app
}
