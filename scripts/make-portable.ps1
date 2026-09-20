<#
.SYNOPSIS
    Assemble the portable Prosody ZIP from a completed Tauri build.

.DESCRIPTION
    `tauri build` produces the installer and a bare Prosody.exe; a portable
    layout is not one of its targets, so it is assembled here. On Windows the
    app resolves bundled resources relative to the executable, so the ZIP has
    to mirror the installed layout exactly:

        Prosody/
          Prosody.exe
          resources/prosody-core/prosody-core.exe + _internal/
          licenses/
          README.txt

    Verify the result by running the extracted copy, not by reading this file.
#>
[CmdletBinding()]
param(
    [string]$Version,
    [switch]$Portable   # also drop portable.flag so Data\ is used
)

$ErrorActionPreference = "Stop"
$repo    = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $repo "apps\desktop"
$tauri   = Join-Path $desktop "src-tauri"
$release = Join-Path $tauri "target\release"

if (-not $Version) {
    $conf = Get-Content (Join-Path $tauri "tauri.conf.json") -Raw | ConvertFrom-Json
    $Version = $conf.version
}

$exe = Join-Path $release "Prosody.exe"
if (-not (Test-Path $exe)) {
    throw "Prosody.exe not found at $exe. Run 'npm run tauri build' first."
}

$core = Join-Path $tauri "resources\prosody-core\prosody-core.exe"
if (-not (Test-Path $core)) {
    throw "The core was not built. Run 'python -m PyInstaller prosody-core.spec' first."
}

$dist = Join-Path $repo "dist\Prosody"
$out  = Join-Path $repo "release"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Path $dist -Force | Out-Null
New-Item -ItemType Directory -Path $out  -Force | Out-Null

Write-Host "Assembling portable layout..." -ForegroundColor Cyan
Copy-Item $exe (Join-Path $dist "Prosody.exe")

# Resources exactly as the bundle lays them out.
$resourceSrc = Join-Path $tauri "resources"
$resourceDst = Join-Path $dist "resources"
New-Item -ItemType Directory -Path $resourceDst -Force | Out-Null
Copy-Item (Join-Path $resourceSrc "prosody-core") $resourceDst -Recurse -Force
Remove-Item (Join-Path $resourceDst "prosody-core\PLACEHOLDER.txt") -ErrorAction SilentlyContinue
if (Test-Path (Join-Path $resourceSrc "bin")) {
    Copy-Item (Join-Path $resourceSrc "bin") $resourceDst -Recurse -Force
}

# Licences travel with the binaries that need them.
$licenseSrc = Join-Path $repo "licenses"
if (Test-Path $licenseSrc) {
    Copy-Item $licenseSrc (Join-Path $dist "licenses") -Recurse -Force
}

if ($Portable) {
    Set-Content (Join-Path $dist "portable.flag") `
        "Prosody keeps its data in the Data folder beside this file." -Encoding UTF8
}

# README.txt — the first thing a user opens.
@"
PROSODY $Version
Turn loops into records.

RUNNING IT
  Extract this whole folder somewhere you can write to, then double-click
  Prosody.exe. Keep the folder together: Prosody.exe needs the resources
  folder next to it.

FIRST LAUNCH
  Windows SmartScreen will say "Windows protected your PC" because this
  build is not code-signed. Click "More info", then "Run anyway". You only
  have to do this once.

  If Windows says the Edge WebView2 runtime is missing, install it from
  https://go.microsoft.com/fwlink/p/?LinkId=2124703 and start Prosody again.

WHAT YOU NEED
  Nothing. Python, Node and Rust are not required — Prosody ships its own
  core. FL Studio is optional: without it you still get analysis, arrangement
  planning, the arranged .flp, per-role MIDI and the portable project. WAV,
  MP3 and stems need FL Studio, which you point Prosody at under Settings.

  While rendering, FL Studio opens its own window. That is expected and
  cannot be suppressed; leave it alone until the build finishes.

WHERE YOUR FILES GO
  Exports    %USERPROFILE%\Documents\Prosody\Exports
  Settings   %LOCALAPPDATA%\Prosody\settings.json
  Logs       %LOCALAPPDATA%\Prosody\Logs

PORTABLE MODE
  Create an empty file called portable.flag next to Prosody.exe. Prosody then
  keeps everything in a Data folder beside the executable and writes nothing
  to your user profile — put the folder on a USB stick and it travels.

YOUR ORIGINALS ARE NEVER MODIFIED
  Prosody hashes every source .flp before it starts and checks it again
  afterwards. A mismatch aborts the build. Output goes to a new versioned
  folder; nothing is ever overwritten.

OFFLINE
  Prosody makes no network calls. AI planners are optional, off by default,
  and would only ever receive numbers and role names.
"@ | Set-Content (Join-Path $dist "README.txt") -Encoding UTF8

$zip = Join-Path $out "Prosody-v$Version-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Write-Host "Compressing $zip ..." -ForegroundColor Cyan
Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal

# Checksums for every release file.
$sums = Join-Path $out "SHA256SUMS.txt"
Get-ChildItem $out -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
    ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name } |
    Set-Content $sums -Encoding UTF8

Write-Host ""
Write-Host "Portable ZIP : $zip" -ForegroundColor Green
Write-Host "Layout       : $dist" -ForegroundColor Green
Write-Host "Checksums    : $sums" -ForegroundColor Green
