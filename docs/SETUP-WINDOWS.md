# WaveCymatix — Windows Installation Guide

WaveCymatix on Windows the core rendering/audio-capture/UI pipeline is fully supported, but Linux-only monitors/plugins (Bluetooth, AirPlay, Spotify Connect, PulseAudio device management) are unavailable — see the [Plugin & Monitor Support Matrix](SETUP.md#plugin--monitor-support-matrix). Windows instead gets native **Windows Media Transport Controls** (SMTC) integration for Now Playing metadata. VLC is also supported and can be installed/enabled automatically via `-Plugins vlc`.

> See [SETUP.md](SETUP.md) for OS selection and the shared [Configuration guide](SETUP.md#%EF%B8%8F-configuration). Installing on Linux/Raspberry Pi instead? Head to [SETUP-LINUX.md](SETUP-LINUX.md).

<details open>
<summary><b>Automated Installation (bin/install-windows.ps1)</b></summary>

### Prerequisites
- Windows 10/11
- [winget](https://learn.microsoft.com/windows/package-manager/winget/) (install "App Installer" from the Microsoft Store if missing)
- Visual Studio Build Tools with the **Desktop development with C++** workload (MSVC v143 toolset + Windows 10/11 SDK) — required to build libprojectM from source
- An elevated (**Run as Administrator**) PowerShell session

The script itself installs/updates Git, CMake, Python 3.12, and FFmpeg via `winget`, so you do not need to install those manually.

Download and extract the source archive from the
[GitHub releases page](https://github.com/kholbrook1303/WaveCymatix/releases).
In an elevated PowerShell session, change to the extracted directory before
running the examples. The complete archive is required; the script cannot run
by itself. For updates, download the latest archive again to get the latest
installer.

The default source is the latest stable GitHub release. If none exists, the
installer warns and selects the most recently published prerelease instead.
Once a stable release exists, use `-Ref <tag>` to select a prerelease. If no
release has been published, use a complete checkout with `-LocalInstall`.

### What it does
`install-windows.ps1`:
1. Installs prerequisites (Git/CMake/Python 3.12/FFmpeg) via `winget`.
2. Detects the MSVC toolchain and builds libprojectM from source (via `vcpkg`) into `bin\third_party`.
3. Installs fonts used by the UI.
4. Stages the `src/wavecymatix` package and installs it into the output directory's virtual environment. The install directory keeps `conf`, installer files, and `requirements.txt`; UI assets are packaged with the application.
5. Downloads the default presets/textures/sprites.
6. Configures `settings.toml` (paths, performance tier via GPU VRAM detection, and forces Linux-only monitors/plugins to `false` while enabling `windows_media`).
7. Creates a Python 3.12 virtual environment (`.venv`), installs `requirements.txt`, and installs the WaveCymatix package with its `wavecymatix` launcher.

### Installer Usage
```
install-windows.ps1 [-Mode <install|update|uninstall>] [-Profile <minimal|optimized>] [-Plugins <value>] [-Autostart] [-LocalInstall] [-Source <path>] [-OutputDir <path>] [-Hyperion]
```
| Parameter | Description |
| --- | --- |
| `-Mode` (`-m`) | `install`, `update`, or `uninstall`. Defaults to update when installed, otherwise install. |
| `-Profile` | `minimal` or `optimized` performance profile. Defaults to `optimized` for a fresh config. |
| `-OutputDir` (`-o`) | Install location. Defaults to `%ProgramData%\WaveCymatix`. |
| `-LocalInstall` (`-l`) / `-Source` (`-s`) | Use a local repository checkout instead of cloning from GitHub (useful for development). |
| `-Ref` | Application tag, branch, commit, or `latest` (stable preferred; prerelease fallback). |
| `-AssetsRef` | Visual-assets ref; defaults to `main`. |
| `-Plugins` (`-p`) | Comma-separated plugin list. `vlc` installs the latest VLC media player via `winget` and sets `vlc = true` in `settings.toml`. Any other Linux-only plugin name is accepted for CLI parity but ignored with a warning. |
| `-Autostart` / `-NoAutostart` | Enable or disable the user's Startup shortcut. |
| `-Hyperion` | Accepted for CLI parity but ignored on Windows. |

#### Example: default optimized install
```powershell
.\bin\install-windows.ps1
```

#### Example: minimal performance profile to a custom directory
```powershell
.\bin\install-windows.ps1 -Mode install -Profile minimal -OutputDir 'D:\WaveCymatix'
```

#### Example: update from a local checkout without rebuilding libprojectM
```powershell
.\bin\install-windows.ps1 -Mode update -LocalInstall
```

#### Example: update to the default release
```powershell
.\bin\install-windows.ps1 -Mode update
```

#### Example: install a specific release
Use the matching release archive for the installer:
```powershell
.\bin\install-windows.ps1 -Mode install -Ref v0.1.0
```

#### Example: optimized install with the VLC plugin
```powershell
.\bin\install-windows.ps1 -Mode install -Profile optimized -Plugins vlc
```

#### Uninstall
```powershell
.\bin\install-windows.ps1 -Mode uninstall
```

Add `-Purge` to uninstall and remove retained user data. Run
`.\bin\install-windows.ps1 -Help` for all options.

**Reinstalling / upgrading:** The installer replaces the application package and installer files while preserving user configuration, data, presets, textures, sprites, and the virtual environment (the venv is only recreated if it's missing/incomplete). Legacy root-level application files are removed during migration. Visual assets are downloaded separately and default to their `main` branch.

### Running WaveCymatix
```powershell
& "$env:ProgramData\WaveCymatix\.venv\Scripts\wavecymatix.exe"
```

</details>

<details>
<summary><b>Manual Installation</b></summary>

Manual installation on Windows mirrors what `install-windows.ps1` automates:
1. Install Git, CMake, Python 3.12, and FFmpeg (via `winget` or manually).
2. Install Visual Studio Build Tools with the Desktop C++ workload.
3. Build libprojectM 4.1.8 from source (OpenGL Core renderer) using CMake/vcpkg; compatible stamped artifacts are reused automatically.
4. Copy the repository checkout (including `src`, `pyproject.toml`, `conf`, and `requirements.txt`) to your chosen install directory (e.g. `C:\ProgramData\WaveCymatix`).
5. Download presets/textures/sprites from [WaveCymatix-Visuals](https://github.com/kholbrook1303/WaveCymatix-Visuals) into that same directory.
6. Create a Python 3.12 virtual environment and install `requirements.txt`:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m pip install --no-deps .
   ```
   Launch with `.\.venv\Scripts\wavecymatix.exe`.
7. In `conf\settings.toml`, set `audio = false` and `display = false` in `[monitors]` (unsupported on Windows), and set `windows_media = true` in `[plugins]` (leave the Linux-only plugins `false`; set `vlc = true` if you install VLC yourself).

Given the amount of native-build tooling involved, using `install-windows.ps1` (optionally with `-LocalInstall` for iterative development) is strongly recommended over doing this by hand.

</details>

## Optional Features

<details>
<summary><b>Setup Windows Media Transport Controls</b> <i>(Windows only)</i></summary>

WaveCymatix can read Now Playing metadata/album art from any app that reports through the Windows System Media Transport Controls (SMTC) — e.g. Spotify, Media Player, browsers playing audio/video, etc. This is enabled by default (`windows_media = true`) by `install-windows.ps1` and requires no additional installation; it uses the `winsdk` package already installed as part of `requirements.txt`.

For manual setup, open `%ProgramData%\WaveCymatix\conf\settings.toml`, navigate to `[plugins]`, and ensure:
```
windows_media = true
```

</details>

<details>
<summary id="setup-plexamp-windowsmacos"><b>Setup Plexamp</b> <i>(Windows/macOS; Requires PlexPass — manual install only)</i></summary>

`install-windows.ps1` does not automate Plexamp on Windows, but the plugin itself works cross-platform once a Plexamp headless client is registered and reachable.

1. Download the Plexamp from https://www.plex.tv/media-server-downloads/?cat=computer&plat=windows#plex-plexamp and proceed with the setup and initial registration).
4. In `settings.toml`, set your Plex server name (this will be your computer name; run 'hostname' in cmd to get the system name) under `[plexamp]`, and set `plexamp = true` under `[plugins]`.  If the hostname does not connect, check the logs which should log a warning and provide you the active clients.  Often times it replaces '-' in he hostname with a space.

### Instructions for casting
Once running, you can either use Plexamp in a seperate window (dual monitor) or go to Plexamp on your mobile device and select the cast button. In the menu of systems, select the hostname of your PC to broadcast music.

### Instructions for using without casting
On a system with a web browser, navigate to:
```
http://<PC_IP>:32500
```
Login with your PlexPass credentials and you can now control Plexamp music on your PC.

</details>
