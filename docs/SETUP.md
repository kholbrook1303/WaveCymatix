# WaveCymatix Installation Guide

WaveCymatix supports **Linux** (Raspberry Pi OS is the primary/reference platform), **Windows**, and **macOS**. Pick the guide that matches your OS:

- **[Linux Installation](SETUP-LINUX.md)** (includes Raspberry Pi specific callouts)
- **[Windows Installation](SETUP-WINDOWS.md)**
- **[macOS Installation](SETUP-MACOS.md)**

When upgrading to a release that stores its installer compatibility marker in
`bin/VERSION`, download and run the installer from that release. Older
installers expect the marker at the repository root and cannot install it.
The new installer also accepts the root marker in older releases.
This change raises the installer API level to 2; it does not change the
application version.

Once installed, see [⚙️ Configuration](#%EF%B8%8F-configuration) below — it applies to all OSes, with OS-specific notes called out per section.

---

## ⚙️ Configuration

All configuration lives in the `conf/` folder of your install directory. The primary file is `settings.toml`:
- **Linux** `/opt/WaveCymatix/conf/settings.toml`
- **Windows** `%ProgramData%\WaveCymatix\conf\settings.toml`
- **macOS** `$HOME/WaveCymatix/conf/settings.toml`

Application settings and audio-device configuration use TOML. ProjectM sprite
definitions remain in `conf/sprites.ini`.

During an application update, the installer adds settings and tables present in
the shipped TOML defaults but missing from your files. Existing values and
comments are left unchanged, so new settings become available without requiring
manual config edits.

<details>
<summary><b>WaveCymatix Configuration</b></summary>

### `[general]`
| Key | Applies to | Description |
| --- | --- | --- |
| `log_level` | All | Python logging level (`10`=DEBUG … `50`=CRITICAL). |
| `touch_rotation_degrees` | All (touch panels) | Rotates touch input (`0`/`90`/`180`/`270`) to match a physically rotated panel; also controls which screen edge is used for swipe/tap preset navigation. |
| `playlistDbPath` | All | SQLite file used to persist playlists/favorites. Set automatically by the installers. |
| `pcm_cache_seconds` | All | Seconds of PCM audio retained for the audio-lookup (Shazam) feature. |

### `[ui]`
Window styling options include selected and deselected header colors, window and floating-overlay border colors, and background alpha. Colors use familiar RGB channel values from `0` to `255` (for example, red is `[255, 0, 0]`); background alpha ranges from `0.0` (transparent) to `1.0` (opaque).

Toggles for each overlay: `visuals_enabled`/`default_visual_mode` (`projectm`, `slideshow`, `video_background`, or `none`), `media_ui_enabled`/`media_ui_persistent`, `now_playing_enabled`/`now_playing_persistent`, `toolbar_ui_enabled`, `diagnostics_ui_enabled`. These apply on all OSes.

`ui_scale_factor` is the overall UI scale; `toolbar_ui_scale_factor`, `media_ui_scale_factor`, `now_playing_ui_scale_factor`, and `diagnostics_ui_scale_factor` independently scale each overlay relative to it. All default to `1.0` (100%); values greater than `0` and at most `1.0` reduce the corresponding UI. For example, set `media_ui_scale_factor=0.8` to make the media controls 80% of their overall UI scale.

The UI safe region uses a maximum aspect ratio of 16:9: widescreen layouts such as 4K UHD use the full 16:9 region, ultrawide layouts center within a 16:9 region, and narrower layouts such as 4:3 CRTs use the full display area.

### `[monitors]` — **Linux only**
```
audio = true
display = true
```
Both monitors require Linux-specific dependencies (`pulsectl`/PulseAudio for `audio`, `evdev` + X11/Wayland tooling for `display`) and are automatically disabled on Windows (the Windows installer forces both to `False`). Leave these as `True` on Linux unless you are managing audio devices/resolution yourself.

### `[audio_ctrl]`, `[automatic]`, `[manual]` — **Linux only (PulseAudio)**
Controls how WaveCymatix selects/route PulseAudio sources and sinks. Only relevant when `audio = true` in `[monitors]`. `audio_mode = "automatic"` (default) picks devices heuristically; `audio_mode = "manual"` requires you to define devices explicitly in `audio_cards.toml`, `audio_sources.toml`, and `audio_sinks.toml`. Not applicable on Windows.

### `[plugins]`
Enables/disables each audio-source/media-control plugin. See the [Plugin & Monitor Support Matrix](#plugin--monitor-support-matrix) below for which plugins are available on which OS — setting an unsupported plugin to `True` is a no-op (the plugin reports itself unsupported and is skipped).
```
plexamp = false        # Universal (Linux/Windows/macOS)
windows_media = false  # Windows only
airplay = false        # Linux only
bluetooth = false      # Linux only
spotify = false        # Linux only
vlc = true             # Linux only
```

### `[vlc]`, `[plexamp]` — plugin-specific settings
`[vlc]` optionally enables the built-in "audio listener" (`listener_enabled`), which watches a local directory or USB path for new audio files and queues/shuffles them for playback — handy for a plug-and-play music player without any casting plugin. `[plexamp]` holds your Plex server URL/token/client name used to control an already-registered Plexamp client.

### `[audio_lookup]`
Enables ShazamIO-based track recognition/metadata lookup (used to populate Now Playing when no plugin is actively reporting track info). Cross-platform; only needs network access.

### `[visuals]`, `[slideshow]`, `[video_background]`
Enable/configure the three visual modes (`projectm`, `slideshow` of local images, and `video_background`). Cross-platform; paths should point at directories that exist on your system.

### `[projectm]`
projectMSDL/libprojectM window and rendering settings (fullscreen, resolution, preset/texture paths, FPS, mesh size, transitions, etc.). See the inline comments in `settings.toml` for details on each key.

> **Raspberry Pi resolution guidance:**
> - Raspberry Pi 5 (HDMI): `width=1280 height=720`
> - Raspberry Pi 4 (HDMI): `window.fullscreen.width = 720`, `window.fullscreen.height = 576`, `"projectM.fps" = 30`
> - Raspberry Pi 4/5 (Composite): `window.fullscreen.width = 720`, `window.fullscreen.height = 480` (Pi 4) or `576` (Pi 5), `"projectM.fps" = 30`
>
> The automated installers (`install-linux.sh --mode install --profile optimized`, `install-windows.ps1 -Mode install -Profile optimized`, `install-macos.sh --mode install --profile optimized`) auto-detect your GPU/hardware performance tier and set `"projectM.fps"`/`"projectM.meshX"`/`"projectM.meshY"` accordingly, so manual tuning is normally only needed for custom setups.

### `[performance]`
Runtime stability/auto-skip tuning (FPS policy and frame-time instability detection) that can automatically advance off of a preset that's tanking performance. Disabled by default (`fps_policy_enabled = false`, `perf_detection_enabled = false`); the section is still measured/reported in the Diagnostics overlay even when disabled. Applies to all OSes; the defaults are conservative enough for Raspberry Pi 4/5.

</details>

<details>
<summary><b>PulseAudio Configuration</b></summary></br>

**Linux only.** To enable higher sample rates in Pulseaudio (Specifically for various DACs) ensure you add the following to Pulseaudio daemon config (/etc/pulse/daemon.conf)
```
resample-method = soxr-vhq
avoid-resampling = true
default-sample-format = s24le
default-sample-rate = 44100
alternate-sample-rate = 48000
```

Either restart or you can run 
```
systemctl --user restart pulseaudio.socket
systemctl --user restart pulseaudio.service

```
</details>

### Global Configurations

### Linux Configurations

<details>
<summary><b>Plugin & Monitor Support Matrix</b></summary>

| Feature | Linux | Windows | macOS | Requires | Config Key |
| --- | :---: | :---: | :---: | --- | --- |
| Audio device monitor | ✅ | ❌ | ❌ | PulseAudio + `pulsectl` | `[monitors] audio` |
| Display/resolution monitor | ✅ | ❌ | ❌ | X11/Wayland + `evdev` | `[monitors] display` |
| Bluetooth (A2DP sink) | ✅ | ❌ | ❌ | BlueZ, `pulseaudio-module-bluetooth` | `[plugins] bluetooth` |
| AirPlay (shairport-sync) | ✅ | ❌ | ❌ | `shairport-sync`, `nqptp` | `[plugins] airplay` |
| Spotify Connect (spotifyd) | ✅ | ❌ | ❌ | `spotifyd` (Premium account) | `[plugins] spotify` |
| VLC | ✅ | ✅ | ✅ | `vlc`, `python-vlc` | `[plugins] vlc` |
| Plexamp | ✅ | ⚠️ Manual only | ⚠️ Manual only | Node.js + Plexamp headless client (Plex Pass) | `[plugins] plexamp` |
| Windows Media Transport Controls | ❌ | ✅ | ❌ | `winsdk` (GSMTC) | `[plugins] windows_media` |
| Audio track lookup (ShazamIO) | ✅ | ✅ | ✅ | Network access | `[audio_lookup] enabled` |

Notes:
- ❌ entries are automatically disabled/no-op on that OS; you do not need to manually set them to `False`.
- Plexamp's plugin code itself is cross-platform, but only the Linux installer (`install-linux.sh`) automates installing Node.js/Plexamp; on Windows/macOS you would install/register Plexamp headless manually and then set `plexamp = true` yourself — see [SETUP-WINDOWS.md](SETUP-WINDOWS.md#setup-plexamp-windowsmacos).
- Bluetooth, AirPlay, and Spotify Connect rely on Linux-only daemons/DBus integrations and are not available on Windows/macOS. VLC is supported on all three OSes; `install-linux.sh` installs it via `apt`, `install-windows.ps1 -Plugins vlc` installs the latest release via `winget`, and `install-macos.sh -p vlc` installs it via Homebrew or MacPorts.
- Per-plugin setup steps live in the OS-specific guides: [SETUP-LINUX.md](SETUP-LINUX.md#optional-features), [SETUP-WINDOWS.md](SETUP-WINDOWS.md#optional-features), and [SETUP-MACOS.md](SETUP-MACOS.md#optional-features).

</details>