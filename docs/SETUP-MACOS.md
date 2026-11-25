# WaveCymatix — macOS Installation Guide

WaveCymatix on macOS the core rendering/audio-capture/UI pipeline is supported, but Linux-only monitors/plugins (Bluetooth, AirPlay, Spotify Connect, PulseAudio device management) are unavailable — see the [Plugin & Monitor Support Matrix](SETUP.md#plugin--monitor-support-matrix). VLC is supported and can be installed/enabled automatically via `-p vlc`.

> See [SETUP.md](SETUP.md) for OS selection and the shared [Configuration guide](SETUP.md#%EF%B8%8F-configuration). Installing on Linux/Raspberry Pi instead? Head to [SETUP-LINUX.md](SETUP-LINUX.md). Installing on Windows instead? Head to [SETUP-WINDOWS.md](SETUP-WINDOWS.md).

<details open>
<summary><b>Automated Installation (bin/install-macos.sh)</b></summary>

### Prerequisites
- macOS with either [Homebrew](https://brew.sh) or [MacPorts](https://www.macports.org/install.php) installed
- Xcode Command Line Tools (the script will prompt to install these if missing — re-run the script once that finishes)

The script installs/updates Git, CMake, Python 3.12, and FFmpeg through the selected package manager. On Intel Macs running macOS Tahoe, automatic selection prefers MacPorts when it is installed. Homebrew remains the default when available on other systems; use `--package-manager` to select explicitly.

Download and extract the source archive from the
[GitHub releases page](https://github.com/kholbrook1303/WaveCymatix/releases),
then open a terminal in the extracted directory. The complete archive is
required; the script cannot run by itself. For updates, download the latest
archive again to get the latest installer.

The default source is the latest stable GitHub release. If none exists, the
installer warns and selects the most recently published prerelease instead.
Once a stable release exists, use `--ref <tag>` to select a prerelease. If no
release has been published, use a complete checkout with `--local-install`.

### What it does
`install-macos.sh`:
1. Installs/updates prerequisites (Git/CMake/Python 3.12/FFmpeg) via Homebrew or MacPorts.
2. Installs the required DejaVu Sans, DejaVu Sans Mono Bold, and Liberation Sans fonts for the current user in `~/Library/Fonts` (skipping fonts already present and verifying the DejaVu archive checksum).
3. Builds libprojectM 4.1.8 from source (OpenGL Core renderer) using CMake. At runtime, the loader checks the standard library lookup and `/usr/local/lib`, `/opt/local/lib`, and Homebrew library directories; the core library is loaded globally before the playlist library.
4. Stages the `src/wavecymatix` package and installs it into the output directory's virtual environment. The install directory keeps configuration, installer files, and user data; UI assets are packaged with the application.
5. Downloads the default presets/textures/sprites.
6. Configures `settings.toml` (paths, performance tier via Apple Silicon/GPU VRAM detection, and forces Linux-only monitors/plugins to `false`).
7. Creates a Python 3.12 virtual environment (`.venv`), installs `requirements.txt`, and installs the WaveCymatix package with its `wavecymatix` launcher. With MacPorts, it installs `llvm-22` and `py312-llvmlite` first and exposes MacPorts Python packages to the venv to avoid building llvmlite from source.
8. Creates `run-wavecymatix.sh`, which configures VLC's native library and plugin paths before starting the application. Use this launcher so MacPorts VLC's bundled dylibs are discoverable.

### Installer Usage
```
install-macos.sh [-m <install|update|uninstall>] [-P <minimal|optimized>] [-p <value>] [-a] [-l] [-s <path>] [-o <path>] [--package-manager <auto|brew|macports>]
```
| Option | Description |
| --- | --- |
| `-m`, `--mode` | `install`, `update`, or `uninstall`. Defaults to update when installed, otherwise install. |
| `-P`, `--profile` | `minimal` or `optimized` performance profile. Defaults to `optimized` for a fresh config. |
| `-o`, `--output-dir` | Install location. Defaults to `$HOME/WaveCymatix`. |
| `-l`, `--local-install` / `-s`, `--source` | Use a local repository checkout instead of cloning from GitHub (useful for development). |
| `--ref` | Application tag, branch, commit, or `latest` (stable preferred; prerelease fallback). |
| `--assets-ref` | Visual-assets ref; defaults to `main`. |
| `-p`, `--plugins` | Comma-separated plugin list. `vlc` installs/updates VLC through the selected package manager (Homebrew cask or MacPorts port) and sets `vlc = true` in `settings.toml`. Other Linux-only plugin names are accepted for CLI parity but ignored with a warning. |
| `--package-manager` | `auto` (default), `brew`, or `macports`. Auto prefers MacPorts on Intel Tahoe when available, otherwise selects an installed manager. |
| `-a`, `--autostart` | Creates and loads a `launchd` user agent (`~/Library/LaunchAgents/com.wavecymatix.app.plist`) that starts WaveCymatix at login. |

#### Example: default optimized install
```bash
bash bin/install-macos.sh
```

#### Example: minimal performance profile to a custom directory
```bash
bash bin/install-macos.sh -m install --profile minimal -o /Users/me/WaveCymatix
```

#### Example: optimized install with the VLC plugin
```bash
bash bin/install-macos.sh -m install --profile optimized -p vlc
```

#### Example: select MacPorts (recommended for Intel Macs on Tahoe)
```bash
bash bin/install-macos.sh -m install --profile optimized --package-manager macports -p vlc
```

#### Example: update to the default release
```bash
bash bin/install-macos.sh --mode update
```

#### Example: install a specific release
Use the matching release archive for the installer:
```bash
bash bin/install-macos.sh --mode install --ref v0.1.0
```

#### Uninstall
```bash
bash bin/install-macos.sh -m uninstall
```

Add `--purge` to uninstall and remove retained user data. Run
`bash bin/install-macos.sh --help` for all options. Visual assets are downloaded
separately and default to their `main` branch.

### Running WaveCymatix
```bash
$HOME/WaveCymatix/run-wavecymatix.sh
```

On MacPorts installs, use this launcher. MacPorts installs VLC's `libvlc.dylib` and `libvlccore.dylib` inside the VLC app bundle. The launcher exports python-vlc's supported `PYTHON_VLC_LIB_PATH` and `PYTHON_VLC_MODULE_PATH` variables (plus `DYLD_LIBRARY_PATH` and `VLC_PLUGIN_PATH`). The VLC plugin also detects the MacPorts bundle before importing python-vlc, so direct Python launches work after the updated application files have been installed.

</details>

## Optional Features

<details>
<summary><b>Setup VLC</b> <i>(macOS)</i></summary>

Run the installer with `-p vlc` to install/update VLC through the selected package manager and automatically set `vlc = true` in `settings.toml`. To install it manually with Homebrew:
```bash
brew install --cask vlc
```
With MacPorts, install it using `sudo port install vlc`.
Then in `settings.toml`, under `[plugins]`, set:
```
vlc = true
```

</details>

<details>
<summary id="setup-plexamp-windowsmacos"><b>Setup Plexamp</b> <i>(Windows/macOS; Requires PlexPass — manual install only)</i></summary>

`install-macos.sh` does not automate Plexamp, but the plugin itself works cross-platform once a Plexamp headless client is registered and reachable. See [SETUP-WINDOWS.md](SETUP-WINDOWS.md#setup-plexamp-windowsmacos) for the general setup/casting instructions, which apply the same way on macOS.

</details>
