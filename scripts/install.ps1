<#
.SYNOPSIS
    Installs Prosody on a Windows PC. No Python, Node, Rust, Git or terminal
    knowledge required.

.DESCRIPTION
    Downloads the latest Prosody release built by CI, verifies its checksum,
    extracts it to %LOCALAPPDATA%\Programs\Prosody, clears the mark-of-the-web
    so SmartScreen does not block it, adds a Start Menu shortcut and launches
    the app.

    Run it without cloning anything:

        irm https://raw.githubusercontent.com/cilviademo/prosody/main/scripts/install.ps1 | iex

    Or from a clone:

        .\scripts\install.ps1

.PARAMETER Destination
    Where to install. Defaults to %LOCALAPPDATA%\Programs\Prosody.

.PARAMETER NoLaunch
    Install but do not start the app.

.PARAMETER ZipPath
    Install from a ZIP already on disk instead of downloading one. Use this
    when the machine has no internet access, or when the ZIP was downloaded
    by hand from the Releases page in a browser.

.PARAMETER Portable
    Keep all app state next to the executable instead of in %LOCALAPPDATA%,
    by writing the portable.flag sentinel. Use this for a USB drive or a
    machine you do not want to leave state on.
#>
[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA "Programs\Prosody"),
    [string]$ZipPath,
    [switch]$NoLaunch,
    [switch]$Portable
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # a progress bar makes Invoke-WebRequest ~10x slower

$Repo = "cilviademo/prosody"

function Say($text)  { Write-Host $text -ForegroundColor Cyan }
function Note($text) { Write-Host "  $text" -ForegroundColor DarkGray }
function Win($text)  { Write-Host $text -ForegroundColor Green }

if ($env:OS -ne "Windows_NT") {
    throw "Prosody is a Windows application. This script only runs on Windows."
}

# TLS 1.2 is not the default on stock Windows PowerShell 5.1, and GitHub
# requires it. Without this the download fails with a bare connection error.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

if ($ZipPath) {
    if (-not (Test-Path $ZipPath)) { throw "No such file: $ZipPath" }
    $ZipPath = (Resolve-Path $ZipPath).Path
}

# --- find the release -----------------------------------------------------
# /releases/latest deliberately skips prereleases, and v0.1.0 is one, so list
# releases and take the newest that has a Windows ZIP attached.
$release = $null
$asset = $null
$sums = $null

if (-not $ZipPath) {
Say "Looking for the latest Prosody release..."
$headers = @{ "User-Agent" = "prosody-install" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }

try {
    $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases?per_page=20" -Headers $headers
} catch {
    throw "Could not reach GitHub: $($_.Exception.Message)"
}

$release = $releases |
    Where-Object { -not $_.draft -and ($_.assets.name -match 'Windows\.zip$') } |
    Select-Object -First 1

if (-not $release) {
    Write-Host ""
    Write-Warning "No Prosody release with a Windows ZIP has been published yet."
    Write-Host @"

The release is built by GitHub Actions on a Windows runner. To produce one:

  * push a commit to main, or
  * open https://github.com/$Repo/actions/workflows/release.yml
    and click 'Run workflow'

It takes roughly 10 minutes. Then run this installer again.
"@
    exit 1
}

$asset = $release.assets | Where-Object { $_.name -match 'Windows\.zip$' } | Select-Object -First 1
$sums  = $release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' }   | Select-Object -First 1
Note "$($release.tag_name)  ->  $($asset.name)  ($([math]::Round($asset.size / 1MB, 1)) MB)"
}

# --- download and verify --------------------------------------------------
$work = Join-Path ([IO.Path]::GetTempPath()) ("prosody-install-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null
$zip = if ($ZipPath) { $ZipPath } else { Join-Path $work $asset.name }

try {
    if (-not $ZipPath) {
    Say "Downloading..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -Headers $headers

    if ($sums) {
        Say "Verifying checksum..."
        # Read it from a file rather than from .Content: GitHub serves release
        # assets as application/octet-stream, and Invoke-WebRequest hands back
        # a byte[] for that, not a string. Splitting a byte[] into lines
        # matches nothing and silently skips the whole check.
        $sumsFile = Join-Path $work "SHA256SUMS.txt"
        Invoke-WebRequest -Uri $sums.browser_download_url -OutFile $sumsFile -Headers $headers
        $line = Get-Content $sumsFile |
            Where-Object { $_ -match ('\s' + [regex]::Escape($asset.name) + '\s*$') } |
            Select-Object -First 1
        if ($line -and $line -match '^([0-9a-fA-F]{64})') {
            $expected = $Matches[1].ToUpperInvariant()
            $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToUpperInvariant()
            if ($actual -ne $expected) {
                throw "Checksum mismatch. Expected $expected, got $actual. The download is corrupt or tampered with; nothing was installed."
            }
            Note "SHA-256 matches"
        } else {
            # The release publishes checksums, so a missing entry is not a
            # normal state — say so where it can be seen.
            Write-Warning "$($asset.name) is not listed in SHA256SUMS.txt; the download could not be verified."
        }
    }
    } else {
        Note "installing from $zip"
    }

    # --- install ----------------------------------------------------------
    Say "Installing to $Destination"
    $staging = Join-Path $work "extract"
    Expand-Archive -Path $zip -DestinationPath $staging -Force

    # The ZIP contains a single Prosody/ folder; install its contents so the
    # destination does not end up as ...\Prosody\Prosody\Prosody.exe.
    $payload = Join-Path $staging "Prosody"
    if (-not (Test-Path (Join-Path $payload "Prosody.exe"))) { $payload = $staging }
    if (-not (Test-Path (Join-Path $payload "Prosody.exe"))) {
        throw "The downloaded archive does not contain Prosody.exe. Nothing was installed."
    }

    # A running copy holds a lock on its own exe; replacing it would fail
    # halfway and leave a broken install.
    Get-Process -Name "Prosody" -ErrorAction SilentlyContinue | ForEach-Object {
        Note "closing the running copy of Prosody"
        $_ | Stop-Process -Force
        Start-Sleep -Milliseconds 500
    }

    if (Test-Path $Destination) { Remove-Item $Destination -Recurse -Force }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Copy-Item (Join-Path $payload "*") $Destination -Recurse -Force

    $exe = Join-Path $Destination "Prosody.exe"

    # Files from the internet carry a mark-of-the-web that makes SmartScreen
    # block them. Clearing it is what "More info -> Run anyway" would do.
    # Cosmetic: a failure here must never abandon a working install.
    try {
        Get-ChildItem $Destination -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
    } catch {
        Note "could not clear the mark-of-the-web; SmartScreen may prompt on first launch"
    }

    if ($Portable) {
        # Presence is the signal; the app never reads the contents.
        Set-Content -Path (Join-Path $Destination "portable.flag") -Value "" -Encoding ASCII
        Note "portable mode: state lives in $Destination\Data"
    }

    # --- Start Menu -------------------------------------------------------
    try {
        $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $startMenu "Prosody.lnk"))
        $shortcut.TargetPath = $exe
        $shortcut.WorkingDirectory = $Destination
        $shortcut.Description = "Prosody"
        $shortcut.Save()
        Note "Start Menu shortcut created"
    } catch {
        Note "could not create the Start Menu shortcut: $($_.Exception.Message)"
    }

    Write-Host ""
    $label = if ($release) { " $($release.tag_name)" } else { "" }
    Win "Prosody$label is installed."
    Write-Host "  $exe"
    Write-Host ""
    Write-Host "Exports go to $env:USERPROFILE\Documents\Prosody\Exports." -ForegroundColor DarkGray
    Write-Host "First launch: open Settings and check that FL Studio was detected," -ForegroundColor DarkGray
    Write-Host "then press Test Connection before dropping a project." -ForegroundColor DarkGray

    if (-not $NoLaunch) {
        Write-Host ""
        Say "Starting Prosody..."
        Start-Process -FilePath $exe -WorkingDirectory $Destination
    }
} finally {
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
