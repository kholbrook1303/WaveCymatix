#requires -version 5.1

[CmdletBinding()]
param(
    [Alias('m')]
    [ValidateSet('install', 'update', 'uninstall')]
    [string]$Mode,

    [ValidateSet('minimal', 'optimized')]
    [string]$Profile,

    [Alias('p')]
    [string]$Plugins,

    [Alias('a')]
    [switch]$Autostart,

    [switch]$NoAutostart,

    [Alias('l')]
    [Alias('local-install')]
    [switch]$LocalInstall,

    [Alias('s')]
    [string]$Source,

    [Alias('o')]
    [Alias('output-dir')]
    [string]$OutputDir = "$env:ProgramData\WaveCymatix",

    [switch]$Hyperion,

    [switch]$RebuildProjectM,

    [switch]$ReinstallVenv,

    [switch]$RefreshPrereqs,

    [switch]$RefreshContent,

    [switch]$ResetConfig,

    [switch]$DryRun,

    [switch]$Yes,

    [string]$Ref,

    [string]$ProjectMRef,

    [string]$AssetsRef,

    [string]$User,

    [switch]$Purge,

    [Alias('h')]
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SupportedInstallerApi = $null
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot
$InstallerEnvPath = Join-Path $ScriptRoot 'installer.env'
$InstallerEnv = @{}
$ThirdPartyDir = Join-Path $OutputDir 'runtime\build-cache'
$DownloadsDir = Join-Path $ThirdPartyDir 'downloads'
$VcpkgDir = Join-Path $ThirdPartyDir 'vcpkg'
$RuntimeArtifactsDir = Join-Path $OutputDir 'runtime\artifacts'
$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$InstallerCore = Join-Path $RepoRoot 'bin\installer_core.py'
$PythonExe = $null
$VenvPath = $null
$TargetProfile = $null
$TargetUsername = $null
$ResolvedAssetsRef = $null
$ResolvedSourceRef = $null
$SourceCommit = ''
$AssetsCommit = $null
$StateManifest = Join-Path $OutputDir '.install-state.json'
$script:ManifestActive = $false
$script:TemporaryManifestHelper = $null

trap {
    $failure = $_
    if ($script:ManifestActive) {
        $script:ManifestActive = $false
        try {
            Invoke-InstallerCore @(
                'manifest-operation', '--output', $OutputDir, '--action', 'failed',
                '--error', $failure.Exception.Message
            ) | Out-Null
        }
        catch {
            Write-Host "Failed to record installer failure in the manifest: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    if ($script:TemporaryManifestHelper) {
        Remove-Item -LiteralPath $script:TemporaryManifestHelper -Force -ErrorAction SilentlyContinue
        $script:TemporaryManifestHelper = $null
    }
    Write-Host $failure.Exception.Message -ForegroundColor Red
    exit 1
}

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host '==================================================' -ForegroundColor Cyan
    Write-Host $Message -ForegroundColor Cyan
    Write-Host '==================================================' -ForegroundColor Cyan
}

function Read-InstallerEnv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Shared installer configuration is missing: $Path"
    }

    $values = @{}
    $allowed = @(
        'INSTALLER_API', 'APP_REPO', 'APP_DEFAULT_REF', 'ASSETS_REPO', 'ASSETS_DEFAULT_REF',
        'PROJECTM_REPO', 'PROJECTM_VERSION', 'PROJECTM_DEFAULT_REF', 'PROJECTM_RENDERER',
        'PROJECTM_CMAKE_FLAGS_WINDOWS', 'PROJECTM_CMAKE_FLAGS_MACOS', 'PROJECTM_CMAKE_FLAGS_LINUX',
        'PYTHON_VERSION', 'VCPKG_REPO', 'VCPKG_REF', 'WIN_VS_GENERATOR', 'WIN_CMAKE_ARCH',
        'WIN_GIT_PACKAGE_ID', 'WIN_CMAKE_PACKAGE_ID', 'WIN_PYTHON_PACKAGE_PREFIX',
        'WIN_FFMPEG_PACKAGE_ID', 'WIN_VLC_PACKAGE_ID', 'MIN_CMAKE_VERSION', 'PLEXAMP_VERSION',
        'NODE_VERSION', 'DEJAVU_FONT_VERSION', 'DEJAVU_FONT_URL', 'DEJAVU_FONT_SHA256',
        'LIBERATION_FONT_VERSION', 'LIBERATION_FONT_URL',
        'CMAKE_VERSION', 'BLUEZ_VERSION', 'SHAIRPORT_SYNC_VERSION', 'NQPTP_VERSION', 'SPOTIFYD_VERSION'
    )
    foreach ($line in Get-Content -LiteralPath $Path) {
        $entry = $line.Trim()
        if (-not $entry -or $entry.StartsWith('#')) { continue }
        $parts = $entry -split '=', 2
        if ($parts.Count -ne 2 -or $parts[0] -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "Invalid installer.env entry: $line"
        }
        if ($parts[0] -notin $allowed) {
            throw "Unknown installer.env key: $($parts[0])"
        }
        if ($values.ContainsKey($parts[0])) {
            throw "Duplicate installer.env key: $($parts[0])"
        }
        $values[$parts[0]] = $parts[1].Trim()
    }
    foreach ($required in @(
        'INSTALLER_API', 'APP_REPO', 'APP_DEFAULT_REF', 'ASSETS_REPO', 'ASSETS_DEFAULT_REF',
        'PROJECTM_REPO', 'PROJECTM_VERSION', 'PROJECTM_RENDERER',
        'PROJECTM_CMAKE_FLAGS_WINDOWS', 'VCPKG_REPO', 'VCPKG_REF',
        'WIN_VS_GENERATOR', 'WIN_CMAKE_ARCH', 'PYTHON_VERSION',
        'WIN_GIT_PACKAGE_ID', 'WIN_CMAKE_PACKAGE_ID', 'WIN_PYTHON_PACKAGE_PREFIX',
        'WIN_FFMPEG_PACKAGE_ID', 'WIN_VLC_PACKAGE_ID',
        'DEJAVU_FONT_VERSION', 'DEJAVU_FONT_URL', 'DEJAVU_FONT_SHA256',
        'LIBERATION_FONT_VERSION', 'LIBERATION_FONT_URL'
    )) {
        if (-not $values[$required]) { throw "Required installer.env value is missing: $required" }
    }
    if ($values['INSTALLER_API'] -notmatch '^\d+$') {
        throw 'INSTALLER_API must be an integer.'
    }
    foreach ($versionKey in @(
        'PROJECTM_VERSION', 'PYTHON_VERSION', 'DEJAVU_FONT_VERSION',
        'LIBERATION_FONT_VERSION', 'NODE_VERSION', 'PLEXAMP_VERSION'
    )) {
        if ($values[$versionKey] -notmatch '^\d+(\.\d+){1,2}$') {
            throw "$versionKey must be a numeric version."
        }
    }
    return $values
}

function Invoke-InstallerCore([string[]]$Arguments) {
    if (-not $PythonExe) {
        throw "Python $($InstallerEnv['PYTHON_VERSION']) is required before invoking the installer core."
    }
    $result = & $PythonExe $InstallerCore @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Installer core command failed: $($Arguments -join ' ')"
    }
    return $result
}

function Read-InstallManifest {
    if (Test-Path -LiteralPath $StateManifest) {
        try {
            return Get-Content -LiteralPath $StateManifest -Raw | ConvertFrom-Json
        }
        catch {
            throw "Unable to read install state manifest '$StateManifest': $($_.Exception.Message)"
        }
    }
    return @{}
}

function Get-ManifestValue([object]$Manifest, [string]$Path, [object]$Default = $null) {
    $current = $Manifest
    foreach ($part in $Path.Split('.')) {
        if ($null -eq $current -or -not $current.PSObject.Properties[$part]) {
            return $Default
        }
        $current = $current.$part
    }
    return $current
}

function Set-ManifestComponent(
    [string]$Name,
    [ValidateSet('in_progress', 'installed', 'removed', 'failed')]
    [string]$Status,
    [hashtable]$Details = @{},
    [string]$FailureReason
) {
    $arguments = @(
        'manifest-component', '--output', $OutputDir, '--name', $Name, '--status', $Status
    )
    if ($Details.Count -gt 0) {
        $detailsJson = ConvertTo-Json -InputObject $Details -Compress -Depth 20
        $detailsBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($detailsJson))
        $arguments += @('--details-base64', $detailsBase64)
    }
    if ($FailureReason) { $arguments += @('--error', $FailureReason) }
    Invoke-InstallerCore $arguments | Out-Null
}

function Set-ManifestOperation([string]$Action) {
    Invoke-InstallerCore @('manifest-operation', '--output', $OutputDir, '--action', $Action) | Out-Null
}

function Resolve-TargetUser {
    $userName = $User
    if (-not $userName) {
        $computer = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
        $userName = $computer.UserName
    }
    if (-not $userName) {
        throw 'No interactive console user was found. Specify -User <name> to select the target user.'
    }
    try {
        $sid = ([System.Security.Principal.NTAccount]::new($userName)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        throw "Could not resolve Windows target user '$userName' to a SID."
    }
    $profileKey = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid"
    $profile = (Get-ItemProperty -LiteralPath $profileKey -Name ProfileImagePath -ErrorAction Stop).ProfileImagePath
    if (-not $profile -or -not (Test-Path -LiteralPath $profile -PathType Container)) {
        throw "Could not resolve an existing profile for target user '$userName'."
    }
    $script:TargetUsername = $userName
    $script:TargetProfile = [Environment]::ExpandEnvironmentVariables($profile)
}

function Set-TargetUserShortcut([bool]$Enabled, [bool]$RemoveAll = $false) {
    $programs = Join-Path $TargetProfile 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
    $startup = Join-Path $programs 'Startup'
    $shortcutPath = Join-Path $programs 'WaveCymatix.lnk'
    $startupPath = Join-Path $startup 'WaveCymatix.lnk'
    if ($RemoveAll) {
        foreach ($path in @($shortcutPath, $startupPath)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -ErrorAction Stop
            }
        }
        if ((Test-Path -LiteralPath $shortcutPath) -or (Test-Path -LiteralPath $startupPath)) {
            throw "Could not remove WaveCymatix shortcuts for target user '$TargetUsername'."
        }
        return
    }

    Ensure-Directory $programs
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path (Split-Path -Parent $script:VenvPython) 'pythonw.exe'
    $shortcut.Arguments = '-m wavecymatix'
    $shortcut.WorkingDirectory = $OutputDir
    $iconPath = & $script:VenvPython -c "from importlib.resources import files; print(files('wavecymatix').joinpath('assets', 'WaveCymatix.ico'))"
    if ($LASTEXITCODE -ne 0 -or -not $iconPath -or -not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
        throw "Could not resolve the WaveCymatix shortcut icon from the installed package."
    }
    $shortcut.IconLocation = "$iconPath,0"
    $shortcut.Save()

    if ($Enabled) {
        Ensure-Directory $startup
        Copy-Item -LiteralPath $shortcutPath -Destination $startupPath -Force
    }
    else {
        Remove-Item -LiteralPath $startupPath -Force -ErrorAction SilentlyContinue
    }
}

function Show-Usage {
    @'
Usage: .\bin\install-windows.ps1 [options]

Run this script from an elevated PowerShell session. The default operation is
update when installed, otherwise install, to C:\ProgramData\WaveCymatix.

Parameters:
    -Mode <mode>             Select the installation operation:
                             install    Install WaveCymatix.
                             update     Update an existing installation.
                             uninstall  Remove the Windows installation from
                                        -OutputDir.
                             Default: update when installed, otherwise install.

    -Plugins <list>          Comma-separated plugin list. Supported on Windows:
                             vlc        Installs the latest VLC media player
                                        via winget and sets vlc = true in
                                        settings.toml.
                             Any other Linux-only plugin name is accepted for
                             CLI compatibility but ignored with a warning.

    -Autostart               Add a Startup shortcut for the selected user.
    -NoAutostart             Remove the Startup shortcut.
    -Profile <name>          Select the minimal or optimized performance
                             profile (default: optimized for a fresh config).
    -ReinstallVenv           Recreate the application virtual environment.
    -RefreshPrereqs          Refresh winget package sources before install.
    -RefreshContent          Force visual-assets resync even when the commit matches.
    -ResetConfig             Back up current configuration and use release defaults.
    -Yes                     Use silent winget installs where supported; OS
                             authentication and other system prompts may remain.
    -DryRun                  Print the planned operation without changing files.
    -Verbose                 Show detailed installer diagnostics in addition to
                             normal progress output.

    -LocalInstall            Use a local WaveCymatix checkout instead of
                             cloning the repository from GitHub.
                             Without -Source, the checkout is the repository
                             containing this script.

    -Source <path>           Use the specified local repository as the source
                             for WaveCymatix application files. Supplying
                             -Source automatically enables local-install
                             behavior; -LocalInstall is not required.

                             The path must contain pyproject.toml and src\wavecymatix\, and
                             conf\. Relative paths are resolved from the
                             current working directory. Use an absolute path
                             when launching the installer from another folder.

                             -Source affects application files only. Presets,
                             textures, and sprites are still downloaded from
                             the visual-assets repository.

    -OutputDir <path>        Installation and application-data directory.
                             Default: $env:ProgramData\WaveCymatix

    -Ref <ref|latest>        WaveCymatix source ref (default: latest stable release).
    -ProjectMRef <ref>       Select a projectM tag/branch/commit. When omitted,
                             updates retain the installed projectM source ref.
    -AssetsRef <ref>         Visual-assets ref (default: main).
    -User <name>             Target Windows user when no console user is logged on.
    -Purge                   Remove user state during uninstall.

    -Hyperion                Accepts the Linux ambient-lighting option for CLI
                             compatibility. Hyperion is not supported on
                             Windows and the switch is ignored with a warning.

    -Help, -h                Display this usage information.

Examples (run from an elevated PowerShell prompt):
    First install with hardware tuning (normal default profile):
        .\bin\install-windows.ps1 -Mode install -Profile optimized

    First install with the minimal performance profile:
        .\bin\install-windows.ps1 -Mode install -Profile minimal

    Update the installed application and preserve config (default behavior):
        .\bin\install-windows.ps1 -Mode update

    Update and replace config with release defaults (backs up current config):
        .\bin\install-windows.ps1 -Mode update -ResetConfig

    Enable autostart and install VLC during an install/update:
        .\bin\install-windows.ps1 -Mode update -Autostart -Plugins vlc

    Use a local checkout for application files:
        .\bin\install-windows.ps1 -Mode update -Source C:\src\WaveCymatix

    Choose a non-default installation directory:
        .\bin\install-windows.ps1 -Mode install -Profile optimized -OutputDir D:\WaveCymatix

    Choose a release and visual-assets ref:
        .\bin\install-windows.ps1 -Mode update -Ref latest -AssetsRef main

    Force content and package-source refresh; show detailed diagnostics:
        .\bin\install-windows.ps1 -Mode update -RefreshContent -RefreshPrereqs -Verbose

    Preview an install without changing files:
        .\bin\install-windows.ps1 -Mode install -Profile optimized -DryRun

    Use silent winget installs where supported:
        .\bin\install-windows.ps1 -Mode update -Plugins vlc -Yes

    Force a projectM rebuild:
        .\bin\install-windows.ps1 -Mode update -RebuildProjectM

    Install for a named user when no console user is logged on:
        .\bin\install-windows.ps1 -Mode install -User <windows-user>

    Uninstall the application but keep config, data, content, and runtime:
        .\bin\install-windows.ps1 -Mode uninstall

    Uninstall and remove the entire installation directory and retained data:
        .\bin\install-windows.ps1 -Mode uninstall -Purge

    Show all parameters and examples:
        .\bin\install-windows.ps1 -Help
'@ | Write-Host
}

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Command-Exists([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [System.Environment]::GetEnvironmentVariable('Path', 'User')
}

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this installer from an elevated PowerShell session (Run as Administrator).'
    }
}

function Install-WingetPackage([string]$Id) {
    $existing = winget list --id $Id --exact --accept-source-agreements 2>$null
    if ($LASTEXITCODE -eq 0 -and $existing) {
        Write-Verbose "Already installed: $Id"
        return
    }

    $wingetArgs = @('install', '--id', $Id, '--exact', '--accept-source-agreements', '--accept-package-agreements')
    if ($Yes) { $wingetArgs += '--silent' }
    winget @wingetArgs
    if ($LASTEXITCODE -ne 0) { throw "winget failed to install $Id (exit code $LASTEXITCODE)." }
    Refresh-Path
}

function Update-WingetPackage([string]$Id) {
    $existing = winget list --id $Id --exact --accept-source-agreements 2>$null
    if ($LASTEXITCODE -eq 0 -and $existing) {
        Write-Verbose "Updating to latest version: $Id"
        $wingetArgs = @('upgrade', '--id', $Id, '--exact', '--accept-source-agreements', '--accept-package-agreements')
        if ($Yes) { $wingetArgs += '--silent' }
        winget @wingetArgs
    }
    else {
        Write-Verbose "Installing latest version: $Id"
        $wingetArgs = @('install', '--id', $Id, '--exact', '--accept-source-agreements', '--accept-package-agreements')
        if ($Yes) { $wingetArgs += '--silent' }
        winget @wingetArgs
    }
    if ($LASTEXITCODE -ne 0) { throw "winget failed to update/install $Id (exit code $LASTEXITCODE)." }
    Refresh-Path
}

function Install-VlcPlugin {
    Write-Step 'Installing latest VLC media player'
    Update-WingetPackage -Id $InstallerEnv['WIN_VLC_PACKAGE_ID']
}

function Ensure-Prerequisites {
    Write-Step 'Checking prerequisites'

    if (-not (Command-Exists 'winget')) {
        throw 'winget is required (install App Installer from Microsoft Store).'
    }

    $packages = @(
        $InstallerEnv['WIN_GIT_PACKAGE_ID'],
        $InstallerEnv['WIN_CMAKE_PACKAGE_ID'],
        "$($InstallerEnv['WIN_PYTHON_PACKAGE_PREFIX'])$($InstallerEnv['PYTHON_VERSION'])",
        $InstallerEnv['WIN_FFMPEG_PACKAGE_ID']
    )
    foreach ($package in $packages) {
        if ($RefreshPrereqs) { Update-WingetPackage -Id $package }
        else { Install-WingetPackage -Id $package }
    }
}

function Ensure-MSVC {
    Write-Step 'Detecting Visual Studio C++ toolchain'

    if (-not (Test-Path -LiteralPath $VsWhere)) {
        throw 'vswhere was not found. Install Visual Studio Build Tools with Desktop C++ workload.'
    }

    $vsPath = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ([string]::IsNullOrWhiteSpace($vsPath)) {
        throw @"
No valid MSVC toolchain found.

Install Visual Studio Build Tools with:
- Desktop development with C++
- MSVC v143 toolset
- Windows 10/11 SDK
"@
    }

    Write-Verbose "MSVC detected at: $vsPath"
}

function Install-Fonts {
    Write-Step 'Installing required fonts'

    $expectedFonts = @(
        'DejaVuSans.ttf',
        'DejaVuSansMono-Bold.ttf',
        'LiberationSans-Regular.ttf',
        'LiberationSans-Bold.ttf'
    )
    $windowsFonts = Join-Path $env:WINDIR 'Fonts'
    $fontsRegistry = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'

    $missingFonts = @($expectedFonts | Where-Object { -not (Test-Path -LiteralPath (Join-Path $windowsFonts $_)) })
    if ($missingFonts.Count -eq 0) {
        Write-Verbose 'All required fonts are already installed, skipping.'
        return
    }

    $workDir = Join-Path $env:TEMP 'WaveCymatix-Fonts'
    $dejaVuZip = Join-Path $workDir "dejavu-fonts-ttf-$($InstallerEnv['DEJAVU_FONT_VERSION']).zip"
    $liberationTarGz = Join-Path $workDir "liberation-fonts-ttf-$($InstallerEnv['LIBERATION_FONT_VERSION']).tar.gz"
    $dejaVuUrl = $InstallerEnv['DEJAVU_FONT_URL']
    $liberationUrl = $InstallerEnv['LIBERATION_FONT_URL']
    $expectedDejaVuSha256 = $InstallerEnv['DEJAVU_FONT_SHA256']

    if (Test-Path -LiteralPath $workDir) {
        Remove-Item -LiteralPath $workDir -Recurse -Force
    }
    Ensure-Directory $workDir

    $dejaVuExtract = Join-Path $workDir 'DejaVu'
    $liberationExtract = Join-Path $workDir 'Liberation'
    Ensure-Directory $dejaVuExtract
    Ensure-Directory $liberationExtract

    Invoke-WebRequest -Uri $dejaVuUrl -OutFile $dejaVuZip -UseBasicParsing
    $actualSha = (Get-FileHash -LiteralPath $dejaVuZip -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualSha -ne $expectedDejaVuSha256) {
        throw "DejaVu checksum verification failed."
    }
    Expand-Archive -LiteralPath $dejaVuZip -DestinationPath $dejaVuExtract -Force

    Invoke-WebRequest -Uri $liberationUrl -OutFile $liberationTarGz -UseBasicParsing
    $tarCmd = Get-Command tar.exe -ErrorAction SilentlyContinue
    if (-not $tarCmd) {
        throw 'tar.exe is required to extract Liberation Fonts archive.'
    }
    & $tarCmd.Source -xzf $liberationTarGz -C $liberationExtract
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe extraction failed with exit code $LASTEXITCODE"
    }

    $fontPaths = @{}
    foreach ($fontName in $expectedFonts) {
        $matches = @(Get-ChildItem -Path $dejaVuExtract, $liberationExtract -Filter $fontName -File -Recurse -ErrorAction SilentlyContinue)
        if ($matches.Count -ne 1) {
            throw "Unable to resolve exactly one source file for $fontName"
        }
        $fontPaths[$fontName] = $matches[0].FullName
    }

    $registryNames = @{
        'DejaVuSans.ttf' = 'DejaVu Sans (TrueType)'
        'DejaVuSansMono-Bold.ttf' = 'DejaVu Sans Mono Bold (TrueType)'
        'LiberationSans-Regular.ttf' = 'Liberation Sans (TrueType)'
        'LiberationSans-Bold.ttf' = 'Liberation Sans Bold (TrueType)'
    }

    foreach ($fontName in $expectedFonts) {
        $source = $fontPaths[$fontName]
        $destination = Join-Path $windowsFonts $fontName

        # Already-registered fonts are locked by the Font Driver Host; only copy what's missing.
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }

        if (-not (Get-ItemProperty -Path $fontsRegistry -Name $registryNames[$fontName] -ErrorAction SilentlyContinue)) {
            New-ItemProperty -Path $fontsRegistry -Name $registryNames[$fontName] -Value $fontName -PropertyType String -Force | Out-Null
        }
    }

    Remove-Item -LiteralPath $workDir -Recurse -Force
}

function Ensure-Vcpkg {
    Write-Step 'Ensuring vcpkg is available'
    Ensure-Directory $ThirdPartyDir
    Ensure-Directory $DownloadsDir

    if (-not (Test-Path -LiteralPath $VcpkgDir)) {
        git clone --branch $InstallerEnv['VCPKG_REF'] $InstallerEnv['VCPKG_REPO'] $VcpkgDir
        if ($LASTEXITCODE -ne 0) { throw 'Failed to fetch vcpkg.' }
    }

    $vcpkgExecutable = Join-Path $VcpkgDir 'vcpkg.exe'
    if (-not (Test-Path -LiteralPath $vcpkgExecutable)) {
        & "$VcpkgDir\bootstrap-vcpkg.bat"
        if ($LASTEXITCODE -ne 0) { throw 'Failed to bootstrap vcpkg.' }
    }
}

function Ensure-GlewRuntime {
    $runtimeGlew = Join-Path $RuntimeArtifactsDir 'glew32.dll'
    if (Test-Path -LiteralPath $runtimeGlew) {
        return
    }

    Ensure-Vcpkg
    $vcpkgExecutable = Join-Path $VcpkgDir 'vcpkg.exe'
    & $vcpkgExecutable install 'glew:x64-windows'
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install the GLEW runtime dependency with vcpkg.' }

    $vcpkgGlew = Join-Path $VcpkgDir 'installed\x64-windows\bin\glew32.dll'
    if (-not (Test-Path -LiteralPath $vcpkgGlew)) {
        throw "vcpkg installed GLEW but its runtime DLL is missing: $vcpkgGlew"
    }
    Ensure-Directory $RuntimeArtifactsDir
    Copy-Item -LiteralPath $vcpkgGlew -Destination $runtimeGlew -Force
}

function Repair-RuntimeArtifactPermissions {
    if (-not (Test-Path -LiteralPath $RuntimeArtifactsDir -PathType Container)) {
        throw "ProjectM runtime artifacts directory is missing: $RuntimeArtifactsDir"
    }

    $icacls = Join-Path $env:SystemRoot 'System32\icacls.exe'
    & $icacls $RuntimeArtifactsDir '/reset' '/T' '/C' '/Q'
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to restore inherited permissions for runtime artifacts in $RuntimeArtifactsDir (icacls exit code $LASTEXITCODE)."
    }
}

function Invoke-ProjectMComponent(
    [string]$Action,
    [string]$SourceType,
    [string]$Ref,
    [string]$Commit,
    [string]$Toolchain,
    [hashtable]$BuildSettings,
    [hashtable]$Artifacts,
    [switch]$AllowLegacy
) {
    $settingsJson = ConvertTo-Json -InputObject $BuildSettings -Compress -Depth 20
    $settingsBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($settingsJson))
    $arguments = @(
        'projectm-component', '--output', $OutputDir, '--action', $Action,
        '--version', $ProjectMVersion, '--renderer', $InstallerEnv['PROJECTM_RENDERER'],
        '--source-type', $SourceType, '--ref', $Ref, '--commit', $Commit,
        '--toolchain', $Toolchain, '--build-settings-base64', $settingsBase64
    )
    foreach ($name in $Artifacts.Keys) {
        $arguments += @('--artifact', "$name=$($Artifacts[$name])")
    }
    if ($AllowLegacy) { $arguments += '--allow-legacy' }
    return (Invoke-InstallerCore $arguments | ConvertFrom-Json)
}

function Build-ProjectM {
    $manifest = Read-InstallManifest
    $stampVersion = Get-ManifestValue -Manifest $manifest -Path 'components.projectm.version'
    $stampRenderer = Get-ManifestValue -Manifest $manifest -Path 'components.projectm.renderer'
    $stampRef = Get-ManifestValue -Manifest $manifest -Path 'components.projectm.ref'
    $stampCommit = Get-ManifestValue -Manifest $manifest -Path 'components.projectm.commit'
    $stampToolchain = Get-ManifestValue -Manifest $manifest -Path 'components.projectm.toolchain'
    $stampVcpkgCommit = Get-ManifestValue -Manifest $manifest -Path 'components.projectm.build_settings.vcpkg_commit'
    $artifacts = @{
        'projectM-4.dll' = Join-Path $RuntimeArtifactsDir 'projectM-4.dll'
        'projectM-4-playlist.dll' = Join-Path $RuntimeArtifactsDir 'projectM-4-playlist.dll'
        'glew32.dll' = Join-Path $RuntimeArtifactsDir 'glew32.dll'
    }
    $cmakeVersion = if (Get-Command cmake -ErrorAction SilentlyContinue) {
        (cmake --version | Select-Object -First 1).Trim()
    }
    else {
        'unavailable'
    }
    $vcpkgCommit = if (-not $ProjectMRef -and -not $RebuildProjectM -and $stampVcpkgCommit) {
        $stampVcpkgCommit
    }
    elseif (Test-Path -LiteralPath (Join-Path $VcpkgDir '.git')) {
        (git -C $VcpkgDir rev-parse HEAD).Trim()
    }
    else {
        ''
    }
    $cmakeFlags = @($InstallerEnv['PROJECTM_CMAKE_FLAGS_WINDOWS'] -split '\s+' | Where-Object { $_ })
    $cmakeOptions = @(
        '-DBUILD_SHARED_LIBS=ON',
        '-DENABLE_SDL_UI=OFF',
        '-DBUILD_TESTING=OFF',
        '-DBUILD_DOCS=OFF',
        '-DENABLE_BOOST_FILESYSTEM=OFF',
        '-DENABLE_SYSTEM_GLM=ON',
        '-DENABLE_SYSTEM_PROJECTM_EVAL=ON'
    )
    $buildSettings = @{
        generator = $InstallerEnv['WIN_VS_GENERATOR']
        architecture = $InstallerEnv['WIN_CMAKE_ARCH']
        cmake_flags = $cmakeFlags
        cmake_options = $cmakeOptions
        cmake_version = $cmakeVersion
        build_configuration = 'Release'
        vcpkg_commit = $vcpkgCommit
        shared_libraries = $true
    }
    $toolchain = if (-not $ProjectMRef -and -not $RebuildProjectM -and $stampToolchain) {
        $stampToolchain
    }
    else {
        "$($InstallerEnv['WIN_VS_GENERATOR']); $cmakeVersion"
    }
    $expectedRef = if ($ProjectMRef) {
        $ProjectMRef
    }
    elseif (-not $RebuildProjectM -and $stampVersion -eq $ProjectMVersion -and
        $stampRenderer -eq $InstallerEnv['PROJECTM_RENDERER'] -and $stampRef) {
        $stampRef
    }
    else {
        "v$ProjectMVersion"
    }
    $projectmSource = $null
    $projectmCommit = if (-not $ProjectMRef -and $expectedRef -eq $stampRef) { $stampCommit } else { '' }
    $sourceType = if ($ProjectMRef -or $projectmCommit) { 'git' } else { 'release-tarball' }
    if ($ProjectMRef) {
        $checkoutJson = Invoke-InstallerCore @(
            'checkout', '--repo', $InstallerEnv['PROJECTM_REPO'], '--ref', $ProjectMRef,
            '--cache', (Join-Path $OutputDir 'runtime\cache\projectm-source')
        )
        $projectmCheckout = $checkoutJson | ConvertFrom-Json
        $projectmSource = $projectmCheckout.path
        $projectmCommit = $projectmCheckout.commit
        $script:ProjectMCommit = $projectmCommit
    }

    if (-not $RebuildProjectM) {
        $reuse = Invoke-ProjectMComponent -Action check -SourceType $sourceType `
            -Ref $expectedRef -Commit $projectmCommit -Toolchain $toolchain `
            -BuildSettings $buildSettings -Artifacts $artifacts -AllowLegacy
        if ($reuse.matches) {
            Write-Verbose "Reusing stamped projectM $ProjectMVersion artifacts."
            Repair-RuntimeArtifactPermissions
            Invoke-ProjectMComponent -Action stamp -SourceType $sourceType `
                -Ref $expectedRef -Commit $projectmCommit -Toolchain $toolchain `
                -BuildSettings $buildSettings -Artifacts $artifacts | Out-Null
            return
        }
    }
    Ensure-MSVC
    Ensure-GlewRuntime
    Ensure-Vcpkg
    $vcpkgCommit = (git -C $VcpkgDir rev-parse HEAD).Trim()
    $buildSettings.vcpkg_commit = $vcpkgCommit
    $toolchain = "$($InstallerEnv['WIN_VS_GENERATOR']); $cmakeVersion; vcpkg $vcpkgCommit"
    Write-Step 'Building projectM libraries'
    if ($ProjectMRef) {
        $ProjectMSourceDir = $projectmSource
        git -C $ProjectMSourceDir submodule update --init --recursive
        if ($LASTEXITCODE -ne 0) { throw 'Failed to initialize projectM git submodules.' }
    }
    else {
        if (-not (Test-Path -LiteralPath $InstallArchivePath)) {
            Invoke-WebRequest -Uri $ProjectMUrl -OutFile $InstallArchivePath -UseBasicParsing
        }

        if (-not (Test-Path -LiteralPath $ProjectMSourceDir)) {
            tar -xzf $InstallArchivePath -C $ThirdPartyDir
            if ($LASTEXITCODE -ne 0) { throw 'Failed to extract projectM source archive.' }
            $extracted = Join-Path $ThirdPartyDir "libprojectM-$ProjectMVersion"
            if (-not (Test-Path -LiteralPath $extracted)) {
                throw 'Unable to find extracted projectM source directory.'
            }
            Rename-Item -Path $extracted -NewName (Split-Path -Leaf $ProjectMSourceDir)
        }
    }

    $buildKey = "$sourceType|$expectedRef|$projectmCommit|$ProjectMVersion|$($InstallerEnv['PROJECTM_RENDERER'])|$toolchain|$($cmakeFlags -join ' ')|$($cmakeOptions -join ' ')|$vcpkgCommit|Release"
    $sha256 = [Security.Cryptography.SHA256]::Create()
    $buildHash = [BitConverter]::ToString(
        $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($buildKey))
    ).Replace('-', '').ToLowerInvariant().Substring(0, 16)
    $ProjectMBuildDir = Join-Path $ThirdPartyDir "projectm-build-$buildHash"
    $toolchainFile = Join-Path $VcpkgDir 'scripts\buildsystems\vcpkg.cmake'
    cmake -G $InstallerEnv['WIN_VS_GENERATOR'] -A $InstallerEnv['WIN_CMAKE_ARCH'] -S $ProjectMSourceDir -B $ProjectMBuildDir -DCMAKE_TOOLCHAIN_FILE="$toolchainFile" @cmakeOptions @cmakeFlags
    if ($LASTEXITCODE -ne 0) { throw 'projectM CMake configuration failed.' }
    cmake --build $ProjectMBuildDir --config Release
    if ($LASTEXITCODE -ne 0) { throw 'projectM build failed.' }

    Set-ManifestComponent -Name 'projectm' -Status 'in_progress'
    Ensure-Directory $RuntimeArtifactsDir
    $installFiles = @('install-files')
    foreach ($name in @('projectM-4.dll', 'projectM-4-playlist.dll')) {
        $builtDll = Get-ChildItem -Path $ProjectMBuildDir -Recurse -Filter $name -File | Select-Object -First 1
        if (-not $builtDll) {
            throw "projectM build did not produce required runtime artifact: $name"
        }
        $destination = Join-Path $RuntimeArtifactsDir $name
        $installFiles += @('--file', "$($builtDll.FullName)=$destination")
    }
    Invoke-InstallerCore $installFiles | Out-Null
    $script:ProjectMCommit = $projectmCommit
    Invoke-ProjectMComponent -Action stamp -SourceType $sourceType `
        -Ref $expectedRef -Commit $script:ProjectMCommit -Toolchain $toolchain `
        -BuildSettings $buildSettings -Artifacts $artifacts | Out-Null
    Repair-RuntimeArtifactPermissions
}

function Get-SourceRepository {
    $resolvedRef = if ($Ref) { $Ref } else { $InstallerEnv['APP_DEFAULT_REF'] }
    $cache = Join-Path $OutputDir 'runtime\cache\wavecymatix'
    $arguments = @(
        'resolve-source', '--ref', $resolvedRef, '--cache', $cache,
        '--output', $OutputDir, '--supported-api', "$SupportedInstallerApi"
    )
    if ($LocalInstall -or $Source) {
        $localPath = if ($Source) { (Resolve-Path $Source).Path } else { $RepoRoot }
        $arguments += @('--source', $localPath)
    }
    else {
        $arguments += @('--repo', $InstallerEnv['APP_REPO'])
    }
    $resolved = (Invoke-InstallerCore $arguments) | ConvertFrom-Json
    $script:ResolvedSourceRef = $resolved.ref
    $script:SourceCommit = $resolved.commit
    if (-not ($LocalInstall -or $Source) -and
        $resolvedRef -ne 'latest' -and $resolvedRef -notmatch '^v\d') {
        Write-Warning "Non-release WaveCymatix source ref selected: $resolvedRef"
    }
    return $resolved.path
}

function Prepare-WaveCymatix([string]$RepoPath) {
    Write-Step 'Preparing WaveCymatix application, content and Python environment'
    $resolvedAssetsRef = if ($AssetsRef) { $AssetsRef } else { $InstallerEnv['ASSETS_DEFAULT_REF'] }
    $arguments = @(
        'prepare-application', '--source', $RepoPath, '--output', $OutputDir,
        '--python', $PythonExe, '--required-python', $InstallerEnv['PYTHON_VERSION'],
        '--supported-api', "$SupportedInstallerApi", '--assets-repo', $InstallerEnv['ASSETS_REPO'],
        '--assets-ref', $resolvedAssetsRef
    )
    if ($ReinstallVenv) { $arguments += '--reinstall-venv' }
    if ($RefreshContent) { $arguments += '--refresh-content' }
    if ($ResetConfig) { $arguments += '--reset-config' }
    $prepared = (Invoke-InstallerCore $arguments) | ConvertFrom-Json
    $script:StageDir = $prepared.stage_dir
    $script:VenvPath = $prepared.venv_path
    $script:VenvPython = $prepared.venv_python
    $script:AssetsCommit = $prepared.assets_commit
    $script:ResolvedAssetsRef = $prepared.assets_ref
    $script:HadUserConfig = $prepared.had_user_config
    if ($prepared.assets_staged) {
        Write-Verbose "Staged visual assets from commit $($prepared.assets_commit)."
    }
    else {
        Write-Verbose "Visual-assets commit $($prepared.assets_commit) is unchanged."
    }
}

function Detect-PerformanceTier {
    $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue

    $maxRamGB = 0

    foreach ($gpu in $gpus) {
        # AdapterRAM is bytes
        if ($gpu.AdapterRAM) {
            $ramGB = [math]::Round($gpu.AdapterRAM / 1GB, 2)
            Write-Verbose "$($gpu.Name): $ramGB GB"
            $maxRamGB = [math]::Max($maxRamGB, $ramGB)
        }
    }

    Write-Verbose "Maximum GPU RAM detected: $maxRamGB GB"

    if ($maxRamGB -ge 4) { return 'high' }
    if ($maxRamGB -ge 2) { return 'medium' }
    if ($maxRamGB -ge 1) { return 'low' }
    return 'very_low'
}


function Configure-WaveCymatix([string]$InstallMode, [bool]$InstallVlcPlugin) {
    Write-Step 'Configuring settings.toml for Windows'

    $confPath = Join-Path $StageDir 'conf\settings.toml'
    if (-not (Test-Path -LiteralPath $confPath)) {
        throw "Configuration file not found: $confPath"
    }

    $settingsArguments = @(
        'configure-settings', '--config', $confPath,
        '--set', 'monitors.audio=false',
        '--set', 'monitors.display=false',
        '--set', 'plugins.airplay=false',
        '--set', 'plugins.bluetooth=false',
        '--set', 'plugins.plexamp=false',
        '--set', 'plugins.spotify=false',
        '--set', "plugins.vlc=$(if ($InstallVlcPlugin) { 'true' } else { 'false' })",
        '--set', 'plugins.windows_media=true'
    )

    if ($InstallMode -eq 'optimized') {
        $tier = Detect-PerformanceTier
        Write-Verbose "Detected performance tier: $tier"
        switch ($tier) {
            'very_low' {
                $settingsArguments += @(
                    '--set', 'projectm.projectM.fps=30',
                    '--set', 'projectm.projectM.meshX=64',
                    '--set', 'projectm.projectM.meshY=40',
                    '--set', 'projectm.window.fullscreen.width=1280',
                    '--set', 'projectm.window.fullscreen.height=720'
                )
            }
            'low' {
                $settingsArguments += @(
                    '--set', 'projectm.projectM.fps=30',
                    '--set', 'projectm.projectM.meshX=96',
                    '--set', 'projectm.projectM.meshY=54',
                    '--set', 'projectm.window.fullscreen.width=1280',
                    '--set', 'projectm.window.fullscreen.height=720'
                )
            }
            'high' {
                $settingsArguments += @(
                    '--set', 'projectm.projectM.fps=60',
                    '--set', 'projectm.projectM.meshX=156',
                    '--set', 'projectm.projectM.meshY=94',
                    '--set', 'projectm.window.fullscreen.width=3840',
                    '--set', 'projectm.window.fullscreen.height=2160'
                )
            }
            default {
                $settingsArguments += @(
                    '--set', 'projectm.projectM.fps=60',
                    '--set', 'projectm.projectM.meshX=64',
                    '--set', 'projectm.projectM.meshY=32',
                    '--set', 'projectm.window.fullscreen.width=1920',
                    '--set', 'projectm.window.fullscreen.height=1080'
                )
            }
        }
    }
    Invoke-InstallerCore $settingsArguments | Out-Null
}

function Invoke-Uninstall {
    Write-Step 'Uninstalling WaveCymatix from output directory'
    $trackManifest = -not $Purge -and (Test-Path -LiteralPath $StateManifest)
    if ($trackManifest) {
        if (-not (Test-Path -LiteralPath $InstallerCore)) {
            throw "Cannot update uninstall manifest: installer helper is missing: $InstallerCore"
        }
        $pythonCandidates = @(
            (Join-Path $OutputDir '.venv\Scripts\python.exe'),
            (Join-Path $OutputDir 'venv\Scripts\python.exe'),
            (Join-Path $OutputDir 'env\Scripts\python.exe')
        )
        $script:PythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $script:PythonExe) {
            $script:PythonExe = (& py "-$($InstallerEnv['PYTHON_VERSION'])" -c 'import sys; print(sys.executable)')
            if ($LASTEXITCODE -ne 0 -or -not $script:PythonExe) {
                throw 'Cannot update uninstall manifest: Python is unavailable.'
            }
        }
        $script:TemporaryManifestHelper = Join-Path $env:TEMP "wavecymatix-installer-core-$PID.py"
        Copy-Item -LiteralPath $InstallerCore -Destination $script:TemporaryManifestHelper -Force
        $script:InstallerCore = $script:TemporaryManifestHelper
        Set-ManifestOperation 'begin'
        $script:ManifestActive = $true
        $manifest = Read-InstallManifest
        Set-ManifestComponent -Name 'application' -Status 'in_progress'
        Set-ManifestComponent -Name 'autostart' -Status 'in_progress'
    }
    if ($TargetProfile) { Set-TargetUserShortcut -Enabled $false -RemoveAll $true }
    Stop-WaveCymatix
    if ($Purge.IsPresent -and (Test-Path -LiteralPath $OutputDir)) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force
    }
    else {
        foreach ($item in @('assets', 'bin', 'core', 'docs', 'lib', 'resources', 'WaveCymatix.py', 'requirements.txt', 'VERSION', '.new', '.prev', '.content-new', '.content-prev', '.app-prev')) {
            $path = Join-Path $OutputDir $item
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
        }
        Write-Host 'User data, configuration, content, runtime and build cache were retained. Use -Purge to remove them.'
    }
    if ($trackManifest) {
        Set-ManifestComponent -Name 'application' -Status 'removed'
        $savedAutostartState = Get-ManifestValue -Manifest $manifest -Path 'components.autostart.status'
        if ($TargetProfile) {
            Set-ManifestComponent -Name 'autostart' -Status 'removed'
        }
        elseif ($savedAutostartState -eq 'installed' -or
            (Get-ManifestValue -Manifest $manifest -Path 'components.autostart.state') -eq 'installed') {
            Set-ManifestComponent -Name 'autostart' -Status 'failed' `
                -FailureReason 'Could not resolve the target user; the autostart shortcut may remain.'
            throw 'The application was removed, but the autostart shortcut could not be verified or removed.'
        }
        else {
            Set-ManifestComponent -Name 'autostart' -Status 'removed'
        }
        Set-ManifestOperation 'succeeded'
        $script:ManifestActive = $false
        Remove-Item -LiteralPath $script:TemporaryManifestHelper -Force
        $script:TemporaryManifestHelper = $null
    }
}

function Stop-WaveCymatix {
    $venvRoots = @(
        (Join-Path $OutputDir '.venv'),
        (Join-Path $OutputDir 'venv'),
        (Join-Path $OutputDir 'env')
    )
    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $command = "$($_.ExecutablePath) $($_.CommandLine)"
        $command -and ($venvRoots | Where-Object { $command.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
    }
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }
}

if ($Help.IsPresent) {
    Show-Usage
    exit 0
}

# Phase 1: preflight
Write-Step 'WaveCymatix Windows installer starting'

if ($Autostart.IsPresent -and $NoAutostart.IsPresent) {
    throw 'Use only one of -Autostart or -NoAutostart.'
}
if ($Purge.IsPresent -and $Mode -and $Mode -ne 'uninstall') {
    throw '-Purge is only valid with -Mode uninstall.'
}

$InstallerEnv = Read-InstallerEnv $InstallerEnvPath
$SupportedInstallerApi = $InstallerEnv['INSTALLER_API']
$StateManifest = Join-Path $OutputDir '.install-state.json'
$manifest = Read-InstallManifest
$wasInstalled = (Test-Path -LiteralPath (Join-Path $OutputDir '.venv\Scripts\wavecymatix.exe')) -or
                (Test-Path -LiteralPath (Join-Path $OutputDir 'WaveCymatix.py')) -or
    (Test-Path -LiteralPath $StateManifest)
$profileWasRequested = $PSBoundParameters.ContainsKey('Profile')
if (-not $Mode) {
    $Mode = if ($wasInstalled) { 'update' } else { 'install' }
}
if ($Mode -ne 'uninstall' -and -not $Profile) {
    $Profile = 'optimized'
}
if ($Purge.IsPresent -and $Mode -ne 'uninstall') {
    throw '-Purge is only valid with -Mode uninstall.'
}
if ($Mode -eq 'uninstall' -and ($Plugins -or $ProjectMRef -or $AssetsRef -or $Ref -or $Autostart -or $NoAutostart -or $Profile -or $LocalInstall -or $Source -or $RebuildProjectM -or $Hyperion -or $Yes)) {
    throw 'Install/update options cannot be combined with -Mode uninstall.'
}
if ($ResetConfig -and $Mode -eq 'uninstall') {
    throw '-ResetConfig is only valid for install or update.'
}
if ($profileWasRequested -and $wasInstalled -and -not $ResetConfig -and $Mode -ne 'uninstall') {
    Write-Warning 'The existing config is being preserved; use -ResetConfig to apply profile defaults.'
}
if ($Mode -eq 'uninstall' -and ($ResetConfig -or $ReinstallVenv -or $RefreshPrereqs -or $RefreshContent)) {
    throw 'Install/update options cannot be combined with -Mode uninstall.'
}

if ($Hyperion.IsPresent) {
    Write-Warning 'Hyperion is Linux-specific and is not supported on Windows. Ignoring --Hyperion.'
}

$installVlcPlugin = $false
if ($Plugins) {
    $requestedPlugins = @($Plugins -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $unsupportedPlugins = @($requestedPlugins | Where-Object { $_ -ine 'vlc' })

    if ($requestedPlugins -icontains 'vlc') {
        $installVlcPlugin = $true
    }

    if ($unsupportedPlugins) {
        Write-Warning "Linux audio plugin installers are not supported on Windows. Ignoring: $($unsupportedPlugins -join ', ')"
    }
}

$savedAutostartState = Get-ManifestValue -Manifest $manifest -Path 'components.autostart.state'
$savedAutostart = if ($null -ne $savedAutostartState) {
    $savedAutostartState -eq 'installed'
}
else {
    [bool](Get-ManifestValue -Manifest $manifest -Path 'options.autostart' -Default $false)
}
$autostartEnabled = if ($Autostart.IsPresent) { $true } elseif ($NoAutostart.IsPresent) { $false } else { $savedAutostart }
if (-not $Plugins) {
    $savedVlcState = Get-ManifestValue -Manifest $manifest -Path 'components.plugin-vlc.status'
    $savedPlugins = Get-ManifestValue -Manifest $manifest -Path 'options.plugins' -Default @()
    $installVlcPlugin = ($savedVlcState -eq 'installed') -or (@($savedPlugins) -icontains 'vlc')
}

if ($Mode -ne 'uninstall') {
    Resolve-TargetUser
}
elseif (Test-Path -LiteralPath $OutputDir) {
    try { Resolve-TargetUser } catch { Write-Warning "Could not resolve the target user; per-user shortcuts may remain: $($_.Exception.Message)" }
}

if ($DryRun) {
    $dryRunRef = if ($Ref) { $Ref } else { $InstallerEnv['APP_DEFAULT_REF'] }
    $refreshNote = if ($RefreshContent) { '; force visual-assets resync' } else { '' }
    Write-Host "Dry run: would run '$Mode' from ref '$dryRunRef' in '$OutputDir'$refreshNote."
    exit 0
}

Assert-Admin

if ($Mode -eq 'uninstall') {
    Invoke-Uninstall
    Write-Step 'Completed'
    exit 0
}

# Phase 2: prerequisites
Ensure-Prerequisites
if (-not (Test-Path -LiteralPath $InstallerCore)) {
    throw "Shared installer helper is missing: $InstallerCore"
}
$PythonExe = (& py "-$($InstallerEnv['PYTHON_VERSION'])" -c 'import sys; print(sys.executable)')
if ($LASTEXITCODE -ne 0 -or -not $PythonExe) {
    throw "Python $($InstallerEnv['PYTHON_VERSION']) could not be resolved after prerequisite installation."
}
Set-ManifestOperation 'begin'
$script:ManifestActive = $true
Install-Fonts

# Phase 3: projectM
if ($Source) { $LocalInstall = $true }
$sourceRepo = Get-SourceRepository
$sourceInstallerEnv = Join-Path $sourceRepo 'bin\installer.env'
if (-not (Test-Path -LiteralPath $sourceInstallerEnv)) {
    throw "Selected source is missing shared installer configuration: $sourceInstallerEnv"
}
$InstallerEnv = Read-InstallerEnv $sourceInstallerEnv
$ProjectMVersion = $InstallerEnv['PROJECTM_VERSION']
$ProjectMSourceDir = Join-Path $ThirdPartyDir "projectm-$ProjectMVersion"
$ProjectMBuildDir = Join-Path $ThirdPartyDir 'projectm-build'
$InstallArchive = "libprojectM-$ProjectMVersion.tar.gz"
$InstallArchivePath = Join-Path $DownloadsDir $InstallArchive
$ProjectMUrl = "$($InstallerEnv['PROJECTM_REPO'] -replace '\.git$', '')/releases/download/v$ProjectMVersion/$InstallArchive"
Stop-WaveCymatix
Build-ProjectM

# Phase 4: WaveCymatix
Prepare-WaveCymatix -RepoPath $sourceRepo
if (-not $HadUserConfig) {
    if ($Profile -eq 'optimized') {
        Configure-WaveCymatix -InstallMode 'optimized' -InstallVlcPlugin $installVlcPlugin
    }
}
$commitArguments = @(
    'commit-application', '--stage', $StageDir, '--output', $OutputDir,
    '--python', $VenvPython, '--source-ref', $ResolvedSourceRef,
    '--assets-ref', $ResolvedAssetsRef,
    '--assets-commit', $AssetsCommit
)
if ($SourceCommit) {
    $commitArguments += @('--source-commit', $SourceCommit)
}
if ($LocalInstall -or $Source) {
    $commitArguments += '--force-app-files'
}
if (-not $HadUserConfig) { $commitArguments += '--configure-default-paths' }
Invoke-InstallerCore $commitArguments | Out-Null

# Phase 5: optional components
if ($installVlcPlugin) {
    Set-ManifestComponent -Name 'plugin-vlc' -Status 'in_progress'
    Install-VlcPlugin
    Set-ManifestComponent -Name 'plugin-vlc' -Status 'installed' -Details @{
        package_manager = 'winget'
    }
}

# Phase 6: autostart
Set-TargetUserShortcut -Enabled $autostartEnabled
if ($autostartEnabled) {
    Set-ManifestComponent -Name 'autostart' -Status 'installed' -Details @{ state = 'installed' }
}
else {
    Set-ManifestComponent -Name 'autostart' -Status 'removed'
}
foreach ($directory in @('data', 'preset_backup')) {
    Ensure-Directory (Join-Path $OutputDir $directory)
}

# Phase 7: finalize
Write-Step 'Installation completed successfully'
Write-Host "Output directory: $OutputDir" -ForegroundColor Green
Set-ManifestOperation 'succeeded'
$script:ManifestActive = $false