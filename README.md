# 🎵 WaveCymatix
WaveCymatix (formerly ProjectM Audio Receiver) is a cross-platform application that is primarily built around the projectM audio visualization library.  While hotkey driven, WaveCymatix also has an optional UI that allows you the flexibility of navigating your audio/visual components.  The UI has a 'Now Playing' feature that integrates directly with plugins, or if your audio capture device does not transmit metadata, there is a Shazam lookup.  The 'Now Playing' feature will display artist - track and album.  If the source provides artwork, it will also be displayed.

## 📢 New projectM Features Coming Soon:
With the release of the upcoming projectM 4.2 release you will be able to add sprites (User controlled visual artifacts that can be animated; great for logos), and 'burn-in' textures.  With texture burn-in, the 'Now Playing' display will burn-into the visualization preset, often creating a dissolve effect.

WaveCymatix is already setup to leverage these features (You can compile the latest code to test).  Once it has been released I will update the base package in the installer.

## 🖼️ Screenshots
![WaveCymatix Screenshot 1](https://github.com/kholbrook1303/RPI5-Bookworm-ProjectM-Audio-Receiver/blob/main/resources/preview1.png)
![WaveCymatix Screenshot 2](https://github.com/kholbrook1303/RPI5-Bookworm-ProjectM-Audio-Receiver/blob/main/resources/preview2.png)
![WaveCymatix Screenshot 3](https://github.com/kholbrook1303/RPI5-Bookworm-ProjectM-Audio-Receiver/blob/main/resources/preview3.png)
![WaveCymatix Screenshot 4](https://github.com/kholbrook1303/RPI5-Bookworm-ProjectM-Audio-Receiver/blob/main/resources/preview4.png)

## 🎞️ Video Preview
[![WaveCymatix Video 1](https://img.youtube.com/vi/8kj53j3EDec/0.jpg)](https://www.youtube.com/watch?v=8kj53j3EDec)

## 💻 Software Requirements:
- Windows (10/11)
- macOS
- Debian-based Linux distributions (e.g., Ubuntu, Debian, Linux Mint, Raspberry Pi OS)

> **📌 Raspberry Pi on Trixie OS**:  Raspberry Pi on Trixie is throwing a V3D GPU hang with some of the default presets.  The current theory is this is due to binner tile-memory (over)allocation race under GPU-memory/tile-count pressure scaling.  Switching to llvmpipe for software rendering resolves the issue but causes diminished fps since it is not utilizing hardware acceleration.  There is a performance feature in the configuration, that when enforced, will automatically transition to the next preset if there is instability.  This can be used on Trixie to ensure you dont encounter prolonged hangs.

## 🔩 Hardware Requirements:

### Windows / macOS / Other Linux
- Any PC/laptop capable of running Windows 10/11, macOS, or a modern Linux desktop
- An audio input (line-in/aux, USB DAC/ADC, or USB microphone) or an audio-casting plugin (Bluetooth, AirPlay/Spotify Connect on Linux, VLC, or Windows media integration using GSMTC on Windows)

### Single Board Computers
### Raspberry Pi:
- Models (2GB is all thats needed)
  - Raspberry Pi 4  **This requires a reduced resolution and fps*
  - Raspberry Pi 5
- 5v/5A USB-C Power Supply
- SD Card (I recommend the SanDisk 32GB Extreme PRO microSD)
- Case with active cooling (The following are my recommendations)
    - Hifiberry Steel case for RP5 w/active cooling and w/DAC+ ADC card for analog input/output
    - Argon NEO 5 BRED Case for Raspberry Pi 5 with built-in fan
- HDMI Cable with Micro HDMI adapter or Micro HDMI to HDMI cable
- Optional Input devices:
    - USB Microphone
    - USB Line in/Aux
    - DAC/ADC

## 🔉 Example Use Cases
The obvious purpose for this is to have visualizations react to sound.  That said there are various use cases for implementation.
- Music player:
  - Use Bluetooth, AirPlay, Spotify Connect, or Plexamp to "cast" to your device
  - VLC support
- Raspberry Pi Specific:
  - Add DAC/ADC board for an analog input (e.g. HiFiBerry DAC+ ADC)
  - Add DAC/DSP board for a digital input (e.g. HiFiBerry DAC+ DSP)
- Monitoring Ambient Sound:
  - Add a USB microphone to capture sound for visualizing

WaveCymatix also offers additional visual backgrounds.  You can switch between projectM, Photo Slideshow, Video Background, or nothing at all if you prefer!

# ⚙️ Installing instructions
For manual and automated installation instructions (Raspberry Pi, other Linux, Windows, and macOS) see [SETUP.md](docs/SETUP.md).

# 🖦 Input Event Handling Guide

This document describes how keyboard, controller, mouse, touch, and window input events are handled in the application.

---

## ⌨️ Keyboard Input

Handles key presses, with support for modifier keys like **Ctrl**.

### Modifier Support

* `Ctrl` (either left or right) enables certain shortcut actions when combined with other keys.

### Key Bindings

| Key                     | With Ctrl? | Action                                                                 |
| ----------------------- | ---------- | ---------------------------------------------------------------------- |
| `F1`                    | ❌         | Show/hide the help overlay                                             |
| `D`                     | ❌         | Toggle **diagnostics** overlay                                         |
| `F`                     | ❌         | Toggle **favorite** for the current visual                             |
| `F`                     | ✅         | Toggle **fullscreen mode**                                             |
| `I`                     | ✅         | Switch projectM to **next audio device**                               |
| `K`                     | ✅         | **Kill** all active sprites                                            |
| `L` / Home              | ❌         | Trigger **logo sprite(s)**                                             |
| `M`                     | ✅         | Toggle **media controls** persistence                                  |
| `N` / Right Arrow       | ❌         | Load **next preset**                                                   |
| `P`                     | ✅         | Toggle **now_playing** persistence (Toggles the track metadata)        |
| `P` / Left Arrow / Back | ❌         | Load **previous preset**                                               |
| `Q`                     | ✅         | **Exit** the application                                               |
| `T`                     | ❌         | Display track info / request audio lookup if plugins inactive          |
| `V`                     | ✅         | Toggle **visual mode** (Toggles the projectM visualizations on/off)    |
| `Y`                     | ✅         | Toggle **playlist shuffle** mode                                       |
| `Delete`                | ❌         | **Delete** current preset                                              |
| `Space`                 | ❌         | Toggle **preset lock**                                                 |
| `Escape`                | ❌         | Close help or popups, else toggle **fullscreen**                       |
| `Arrow Up`              | ❌         | Increase **beat sensitivity** (+0.1)                                   |
| `Arrow Down`            | ❌         | Decrease **beat sensitivity** (−0.1)                                   |
| `0–9`                   | ❌         | Enter **sprite index digits** (triggers on 2-digit entry)              |

---

## 📺 Controller Media Keys

Handles media keys on supported controllers (e.g. Play/Pause, Next/Previous Track).

### Media Key Bindings

| Button / Combo                       | Action                                                        |
| ------------------------------------ | ------------------------------------------------------------- |
| Application                          | Display track info / request audio lookup if plugins inactive |
| `GUIDE`                              | Trigger **logo sprite(s)** (if configured)                    |
| `AUDIO NEXT`                         | Trigger **next track** on all audio plugins                   |
| `AUDIO PREV`                         | Trigger **previous track** on all audio plugins               |
| `AUDIO PLAY`                         | Trigger **play/pause** on all audio plugins                   |
| `AUDIO STOP`                         | Trigger **stop** on all audio plugins                         |

---

## 🎮 Controller Axis Input (Desktop OS only)

Handles analog stick and trigger inputs. Uses a **deadzone threshold** to avoid accidental movements.

### Axis Bindings

| Axis                         | Condition       | Action                               |
| ---------------------------- | --------------- | ------------------------------------ |
| Left Stick X / Trigger Left  | Left / Pressed  | Load **previous preset**             |
| Left Stick X / Trigger Right | Right / Pressed | Load **next preset**                 |
| Left Stick Y                 | Up              | Increase **beat sensitivity** (+0.1) |
| Left Stick Y                 | Down            | Decrease **beat sensitivity** (−0.1) |

---

## 🎮 Controller Button Input (Desktop OS only)

Handles digital controller buttons such as D-Pad and stick clicks.

### Button Bindings

| Button / Combo                       | Action                                     |
| ------------------------------------ | ------------------------------------------ |
| Left Stick Click / Right Stick Click | Toggle **preset lock**                     |
| D-Pad Up                             | Increase **beat sensitivity** (+0.1)       |
| D-Pad Down                           | Decrease **beat sensitivity** (−0.1)       |
| D-Pad Left                           | Load **previous preset**                   |
| D-Pad Right                          | Load **next preset**                       |
| `BACK + B` (pressed together)        | **Delete** current preset                  |
| `GUIDE`                              | Trigger **logo sprite(s)** (if configured) |

---

## 🖱️ Mouse Input

Handles cursor movement, button clicks, and scroll actions.

| Event        | Action                                                   |
| ------------ | -------------------------------------------------------- |
| Mouse motion | Shows cursor and UI elements; updates toolbar visibility |
| Mouse wheel  | Scrolls **sprite box** if popup open                     |
| Left click   | Custom / configurable actions                            |
| Right click  | Toggle **fullscreen mode**                               |

---

## 🤏 Touch Input

Supports multi-touch gestures for UI and preset control.

| Gesture                         | Action                                        |
| ------------------------------- | --------------------------------------------- |
| Two-finger pinch in             | Hide UI                                       |
| Two-finger pinch out            | Show UI                                       |
| Two-finger tap                  | Toggle **preset lock**                        |
| Horizontal swipe (left/right)   | Load **next / previous preset**               |
| Vertical swipe from top edge    | Open **toolbar**                              |
| Vertical swipe to top edge      | Close **toolbar**                             |
| Vertical swipe from bottom edge | Open **UI**                                   |
| Vertical swipe to bottom edge   | Close **UI**                                  |
| Single tap left / right regions | Load **previous / next preset**               |

---

## 🪟 Window Input

Handles application window events.

| Event                | Action                       |
| -------------------- | ---------------------------- |
| Window close         | Set exit flag                |
| Resize / size change | Update rendering window size |
| Minimize / hidden    | Restore and show window      |
| Focus lost           | Log warning                  |
| Focus gained         | Log debug                    |
