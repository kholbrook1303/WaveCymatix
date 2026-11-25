# WaveCymatix — Linux Installation Guide

This guide applies to any Debian/apt-based Linux (Raspberry Pi OS, Debian, Ubuntu, etc.). Steps that are Raspberry Pi specific are called out in their own **Raspberry Pi** callouts/subsections.

> See [SETUP.md](SETUP.md) for the OS picker and the shared [Configuration guide](SETUP.md#%EF%B8%8F-configuration) (including the [Plugin & Monitor Support Matrix](SETUP.md#plugin--monitor-support-matrix)). Installing on Windows instead? Head to [SETUP-WINDOWS.md](SETUP-WINDOWS.md).

<details open>
<summary><b>Raspberry Pi: Initial Setup</b></summary>

For help getting Raspberry Pi OS setup refer to: [Install Raspberry Pi OS using Raspberry Pi Imager](https://www.raspberrypi.com/software/)
</details>

## Update the System
Make sure the OS is up-to-date before proceeding!
```
sudo apt update
sudo apt upgrade -y
```

<details>
<summary><b>Automated Installation</b></summary>

### Install WaveCymatix

Download and extract the source archive from the
[GitHub releases page](https://github.com/kholbrook1303/WaveCymatix/releases),
then open a terminal in the extracted directory. The installer needs the
complete archive, including `bin/installer.env` and `bin/installer_core.py`;
do not pipe the script directly into a shell.

By default, the installer selects the latest stable GitHub release. If none
exists, it warns and selects the most recently published prerelease instead.
Once a stable release exists, use `--ref <tag>` to select a prerelease.
For an update, download the appropriate release archive again so that you also
have its installer. If no release has been published, use a complete checkout
with `--local-install` instead.

The installer operation is selected with `--mode` (`install`, `update`, or
`uninstall`). The performance profile is a separate `--profile` option:
`minimal` leaves performance settings at their defaults, while `optimized`
applies hardware-aware performance tuning.

The installer also supports the following optional plugins (all Linux-only, see the [Plugin & Monitor Support Matrix](SETUP.md#plugin--monitor-support-matrix) for platform availability):
- bluetooth: Bluetooth audio
- shairport-sync: Airplay casting support
- plexamp: PlexAmp casting support and web UI for library control (Requires Plex Pass)
- spotifyd: Spotify Connect (Requires premium subscription)

When plugins are enabled via the installer `-p` switch, the matching values in `/opt/WaveCymatix/conf/settings.toml` under `[plugins]` are automatically set to `true`.

The installer also auto-detects a GPU/hardware performance tier (Raspberry Pi 3/4/5 are explicitly recognized; other hardware defaults to the `low` tier) and tunes `projectM.fps`/`meshX`/`meshY` accordingly when run with `--profile optimized`.

**Reinstalling / upgrading:** the installer replaces the application package and retires legacy root-level code while preserving configuration, presets, textures, sprites, custom content, preset backups, and the media library database. It also removes the legacy `/etc/xdg/autostart/projectm.desktop` entry and old Python virtual environment when appropriate.

See below for usage instructions and examples.

#### Common commands

```bash
# Install with hardware-aware settings and autostart
sudo bash bin/install-linux.sh --mode install --profile optimized --autostart

# Install with minimal performance settings
sudo bash bin/install-linux.sh --mode install --profile minimal

# Install with selected audio plugins
sudo bash bin/install-linux.sh --mode install --autostart --plugins bluetooth,shairport-sync,spotifyd,plexamp

# Update to the default release, preserving configuration and user data
sudo bash bin/install-linux.sh --mode update

# Install a specific release using its matching installer archive
sudo bash bin/install-linux.sh --mode install --ref v0.1.0

# Uninstall while retaining user data; add --purge to remove it
sudo bash bin/install-linux.sh --mode uninstall
```

For development, `--local-install` uses the extracted checkout's application
files instead of downloading a release. `--ref` can select another tag, branch,
or commit; visual assets are downloaded separately and default to their `main`
branch. Run `bash bin/install-linux.sh --help` for all options.

Run `/opt/WaveCymatix/.venv/bin/wavecymatix` to launch WaveCymatix.
</details>

<details>
<summary><b>Manual Installation</b></summary></br>

Lets add a directory to store our builds so we dont clutter the home directory
```
mkdir -p /tmp/Builds
```

### Building ProjectM and Dependencies
It is advised to only use the releases tested here as they are version controlled to ensure a seamless experience.

<details>
<summary><b>Building libprojectM</b></summary>

### Install the build tools and dependencies
Get the mandatory packages:
```
sudo apt install build-essential cmake libgl1-mesa-dev mesa-common-dev libglm-dev mesa-utils flex bison openssl libssl-dev git
```

### Download/extract/build libprojectM
The current build this project uses is 4.1.7, built with the OpenGL Core renderer (`-DENABLE_GLES=OFF`). Older/newer releases may not perform well on lower-end hardware such as the Raspberry Pi, so it is advised to stick to this version unless you know what you're doing.
```
cd /tmp/Builds
wget https://github.com/projectM-visualizer/projectm/releases/download/v4.1.7/libprojectM-4.1.7.tar.gz
tar xf libprojectM-4.1.7.tar.gz
cd /tmp/Builds/libprojectM-4.1.7/
mkdir build
cd build
cmake -DENABLE_GLES=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local ..
cmake --build . --parallel && sudo cmake --build . --target install
```

</details>

<details>
<summary><b>Installing WaveCymatix</b></summary>

### Install the dependencies
Install WaveCymatix dependencies
```
sudo apt install pulseaudio python3-dev gcc vlc
```

Ensure that your account has permissions to input
```
sudo usermod -aG input $USER
```

> **Raspberry Pi:** Check to ensure your device is configured for PulseAudio by going to `sudo raspi-config`, then select Advanced Options - Audio Config - PulseAudio (Reboot if you made any changes). Other Linux distributions should already default to PulseAudio (Pipewire's `pipewire-pulse` compatibility shim is *not* currently supported and should be disabled in favor of PulseAudio).

### Download and setup WaveCymatix from source
Pull the sources from Github and copy files to installation directory (Make sure you replace $GROUP:$USER with the appropriate user and group)
```
cd /tmp/Builds
git clone https://github.com/kholbrook1303/RPI5-Bookworm-ProjectM-Audio-Receiver.git
sudo mkdir /opt/WaveCymatix
sudo cp -r /tmp/Builds/RPI5-Bookworm-ProjectM-Audio-Receiver/* /opt/WaveCymatix/
sudo chown $GROUP:$USER /opt/WaveCymatix/ -R
sudo chmod 777 -R /opt/WaveCymatix
```

### Setup Python virtual environment
Install the virtual environment
```
cd /opt/WaveCymatix/
python3 -m venv .venv
```

### Get all Python dependencies
Install all Python dependencies
```
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install --no-deps .
```

### Force the Open GL version

Open the '/etc/environment' file to set environment variables
```
sudo nano /etc/environment
```

Add the following entry
```
MESA_GL_VERSION_OVERRIDE=3.3
```

## Environment Specific Startup Instructions
The automated installer always configures autostart via a `systemd --user` service (this replaced the older desktop-only `/etc/xdg/autostart/projectm.desktop` entry, which reinstalls now remove automatically). The manual steps below match that approach and work the same for Desktop and Lite Raspberry Pi OS, as well as other Linux desktops.

<details>
<summary><b>Systemd user service (Desktop and Lite)</b></summary>

### Create a startup service
Create a service by running
```
sudo nano /etc/systemd/user/projectm.service
```

```
[Unit]
Description=WaveCymatix
After=default.target pulseaudio.socket
Requires=default.target

[Service]
Type=simple
ExecStart=/opt/WaveCymatix/.venv/bin/wavecymatix
Restart=on-failure

[Install]
WantedBy=default.target
```

Enable and start the service
```
systemctl --global enable projectm.service
systemctl --user start projectm
```
</details>

<details>
<summary><b>Raspberry Pi: Lite OS Auto-Login</b></summary>

A `systemd --user` service only starts once a user session exists, so Lite OS (no desktop environment) needs auto-login enabled for the target user.

Run the following command and then navigate to System Options -> Boot / Auto Logon -> Console Auto Logon
```
sudo raspi-config
```
</details>

</details>


<details>
<summary><b>Setup ProjectM Presets and Textures</b></summary></br>

***Note:** If you ran the automated installation you already have my presets applied.  Proceed if you would like to add or change anything.*

The preset files define the visualizations via pixel shaders and Milkdrop-style equations and parameters.  The projectM library does not ship with any presets or textures so you want to grab them and deploy them.

There are many options available to you for presets and textures.  In the following I have outlined 3 options:
<details>
<summary><b>GitHub Repo - WaveCymatix-Visuals</b> <i>My hand selected presets and textures for the latest libprojectM release for the Raspberry Pi 5</i></summary>

### Download and move the presets and textures
```
mkdir -p /tmp/Builds
cd /tmp/Builds
git clone https://github.com/kholbrook1303/WaveCymatix-Visuals.git
cp /tmp/Builds/WaveCymatix-Visuals/presets/ /opt/WaveCymatix/ -R
cp /tmp/Builds/WaveCymatix-Visuals/textures/ /opt/WaveCymatix/ -R
```

</details>

<details>
<summary><b>GitHub Repo - projectM-presets-rpi5</b> <i>Presets and textures repository managed by mickabrig7, and benchmarked for the Raspberry Pi 5</i></summary>

### Download and move the presets and textures
*Special thank you to [mickabrig7](https://github.com/mickabrig7/projectM-presets-rpi5) for benchmarking 11,233 presets to narrow down a package specially for the Raspberry Pi 5!*
```
mkdir -p /tmp/Builds
cd /tmp/Builds
git clone https://github.com/mickabrig7/projectM-presets-rpi5.git
cp /tmp/Builds/projectM-presets-rpi5/presets/ /opt/WaveCymatix/ -R
cp /tmp/Builds/projectM-presets-rpi5/textures/ /opt/WaveCymatix/ -R
```

Adjust /opt/WaveCymatix/conf/settings.toml to include the preset and texture directories
```
"projectM.presetPath" = "/opt/WaveCymatix/presets"
"projectM.texturePath" = "/opt/WaveCymatix/textures"
```

</details>


<details>
<summary><b>Manual Method</b> <i>Resources to obtain community presets and textures</i></summary>

### General Presets and Textures:
Textures:
- [Base Milkdrop texture pack](https://github.com/projectM-visualizer/presets-milkdrop-texture-pack) - Recommended for
  use with _any_ preset pack!

Presets:
- [Cream of the Crop Pack](https://github.com/projectM-visualizer/presets-cream-of-the-crop) - A collection of about 10K
  presets compiled by Jason Fletcher. Currently, projectM's default preset pack.
- [Classic projectM Presets](https://github.com/projectM-visualizer/presets-projectm-classic) - A bit over 4K presets
  shipped with previous versions of projectM.
- [Milkdrop 2 Presets](https://github.com/projectM-visualizer/presets-milkdrop-original) - The original preset
  collection shipped with Milkdrop and Winamp.
- [En D Presets](https://github.com/projectM-visualizer/presets-en-d) - About 50 presets created by "En D".

</br></details>

> Presets and textures are just data files, so any of the packs above can also be used on a Windows install — just copy them into the `presets`/`textures` folders under your WaveCymatix install directory (`%ProgramData%/WaveCymatix` by default) instead of `/opt/WaveCymatix`. The two GitHub repos above were specifically curated/benchmarked for the Raspberry Pi 5; the "Manual Method" packs are OS-agnostic. See [SETUP-WINDOWS.md](SETUP-WINDOWS.md) for the Windows installer.

</details>

</details>

</details>

## Optional Features
The following plugins are Linux-only unless noted otherwise — see the [Plugin & Monitor Support Matrix](SETUP.md#plugin--monitor-support-matrix).

<details>
<summary><b>Setup Bluetooth audio</b> <i>(Linux only)</i></summary>

### Get Bluetooth dependencies

Acquire all the necessary dependecies
```
sudo apt-get install pulseaudio-module-bluetooth
```

### Upgrade BlueZ for album artwork support

WaveCymatix Bluetooth artwork support requires BlueZ experimental AVRCP/BIP features and the matching `obexd` daemon. Install the Bluetooth runtime dependencies before building BlueZ; installing them afterward can replace the custom OBEX daemon with Debian's older package version.

Install the required build dependencies:
```
sudo apt install -y \
  pulseaudio-module-bluetooth \
  bluez-tools \
  build-essential \
  pkg-config \
  libglib2.0-dev \
  libdbus-1-dev \
  libudev-dev \
  libreadline-dev \
  libical-dev \
  libell-dev \
  libelf-dev \
  libdw-dev \
  libcap-ng-dev \
  libjson-c-dev \
  wget \
  tar \
  autoconf \
  automake \
  libtool
```

Build and install:
```
mkdir -p /tmp/Builds
cd /tmp/Builds
wget https://github.com/bluez/bluez/archive/refs/tags/5.87.tar.gz
tar -xzf 5.87.tar.gz
cd bluez-5.87
./bootstrap

./configure \
  --prefix=/usr \
  --sysconfdir=/etc \
  --localstatedir=/var \
  --libexecdir=/usr/libexec \
  --mandir=/usr/share/man \
  --enable-experimental \
  --enable-obex

make -j"$(nproc)"

# Validation; Expected: 0
echo $?

sudo make install
sudo ldconfig
```

Enable experimental mode in `/etc/bluetooth/main.conf` under `[General]`:
```
Experimental = true
```

Then restart Bluetooth:
```
sudo systemctl restart bluetooth
```

Restart the OBEX service in the desktop user's session so it uses the newly installed `obexd`:
```
systemctl --user daemon-reload
systemctl --user restart obex.service
```

### Configure Bluetooth functionality
Make the Pi permanently discoverable as a Bluetooth audio sink.
```
sudo nano /etc/bluetooth/main.conf
```

And add / uncomment / change
```
Class = 0x41C

DiscoverableTimeout = 0
```

```
sudo systemctl restart bluetooth
```

```
bluetoothctl power on
bluetoothctl discoverable on
bluetoothctl pairable on
bluetoothctl agent on
```

Auto pairing / trusting / no PIN
```
sudo apt-get install bluez-tools
```

### Configure Bluetooth agent service
```
sudo nano /etc/systemd/system/bt-agent.service
```

```
[Unit]
Description=Bluetooth Auth Agent
After=bluetooth.service
PartOf=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bt-agent -c NoInputNoOutput
KillSignal=SIGUSR1

[Install]
WantedBy=bluetooth.target
```

Enable and start the Bluetooth service
```
sudo systemctl enable bt-agent
sudo systemctl start bt-agent
```

Reboot
```
sudo reboot
```

If installed with the setup script and `-p bluetooth`, plugin booleans are updated automatically in `settings.toml`.

For manual setup, open `/opt/WaveCymatix/conf/settings.toml`, navigate to `[plugins]`, and ensure:
```
bluetooth = true
```

</details>

<details>
<summary><b>Setup AirPlay</b> <i>(Linux only)</i></summary>


### Setup and build Shairport Sync

* It is advised to follow the most recent build steps from https://github.com/mikebrady/shairport-sync/blob/master/BUILD.md

### Get Shairport-Sync dependencies
Install required dependencies
```
sudo apt install --no-install-recommends build-essential git autoconf automake libtool libpulse-dev \
    libpopt-dev libconfig-dev libasound2-dev avahi-daemon libavahi-client-dev libssl-dev libsoxr-dev \
    libplist-dev libsodium-dev libavutil-dev libavcodec-dev libavformat-dev uuid-dev libgcrypt-dev xxd
```

### Obtain the latest source
Clone and build shairport-sync
```
mkdir -p /tmp/Builds
cd /tmp/Builds
wget https://github.com/mikebrady/shairport-sync/archive/refs/tags/4.3.7.tar.gz
tar xf 4.3.7.tar.gz
cd /tmp/Builds/shairport-sync-4.3.7/
autoreconf -fi
./configure --sysconfdir=/etc --with-alsa \
    --with-soxr --with-avahi --with-ssl=openssl --with-systemd --with-airplay-2 --with-pa --with-metadata --with-dbus-interface --with-mpris-interface --with-mqtt-client
make
sudo make install
```

### Setup and build NQPTP
* It is advised to follow the most recent build steps from https://github.com/mikebrady/nqptp

Clone and build nqptp
```
mkdir -p /tmp/Builds
cd /tmp/Builds
wget https://github.com/mikebrady/nqptp/archive/refs/tags/1.2.4.tar.gz
tar xf 1.2.4.tar.gz
cd /tmp/Builds/nqptp-1.2.4
autoreconf -fi
./configure --with-systemd-startup
make
sudo make install
```

### Enable Services
```
sudo systemctl enable nqptp
sudo systemctl start nqptp
```

## Startup Instructions
If installed with the setup script and `-p shairport-sync`, plugin booleans are updated automatically in `settings.toml`.

For manual setup, open `/opt/WaveCymatix/conf/settings.toml`, navigate to `[plugins]`, and ensure:
```
airplay = true
```

</details>

<details>
<summary><b>Setup Plexamp</b> <i>(Requires PlexPass; automated on Linux by `install-linux.sh`)</i></summary>

### Get PlexAmp and NodeJS

```
mkdir -p /tmp/Builds
cd /tmp/Builds
wget https://plexamp.plex.tv/headless/Plexamp-Linux-headless-v4.11.5.tar.bz2
tar -xvjf Plexamp-Linux-headless-v4.11.5.tar.bz2
sudo cp /tmp/Builds/plexamp/ /opt/ -r
cd /opt/plexamp
sudo apt-get install -y ca-certificates curl gnupg && sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
NODE_MAJOR=20
echo deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update && sudo apt-get install -y nodejs
```

### Setup your Plexamp token

Initialize Plexamp for the first time
```
node /opt/plexamp/js/index.js
```

Obtain your claim token.  In a seperate browser goto:
https://plex.tv/claim

Paste the claim code in the terminal window and proceed with naming your player

## Startup Instructions

If installed with the setup script and `-p plexamp`, plugin booleans are updated automatically in `settings.toml`.

For manual setup, open `/opt/WaveCymatix/conf/settings.toml`, navigate to `[plugins]`, and ensure:
```
plexamp = true
```

> Plexamp is also supported on Windows (see [SETUP-WINDOWS.md](SETUP-WINDOWS.md#setup-plexamp-windowsmacos)), but only the Linux installer automates its installation.

## Instructions for casting
Once running goto PlexAmp on your mobile device and select the cast button.  In the menu of systems select the hostname of your Raspberry Pi to broadcast music.

## Instructions for using without casting
On a system with a web browser navigate to your Plexamp system
```
http://<RaspberryPi_IP>:32500
```

Login with your PlexPass credentials and you can now control PlexAmp music on your pi

</details>

<details>
<summary><b>Setup Spotify Connect</b> <i>(Requires Spotify Premium; Linux only)</i></summary>

### Get Spotifyd

```
mkdir -p /tmp/Builds
cd /tmp/Builds
wget https://github.com/Spotifyd/spotifyd/releases/download/v0.4.0/spotifyd-linux-aarch64-default.tar.gz
tar xzf spotifyd-linux-aarch64-default.tar.gz
chmod +x spotifyd
sudo chown root:root spotifyd
sudo mv spotifyd /usr/local/bin/spotifyd
```

### Advanced Configurations

Spotify should work out of the box with defaults but you can also fine tune your setup.  To do so first create a configuration file in /etc/
```
sudo nano /etc/spotifyd.conf
```

Goto the following site and you can see an example confirguration to copy and paste.  Any configurations you want to customize, just uncomment the parameter.

https://docs.spotifyd.rs/configuration/index.html

## Startup Instructions

If installed with the setup script and `-p spotifyd`, plugin booleans are updated automatically in `settings.toml`.

For manual setup, open `/opt/WaveCymatix/conf/settings.toml`, navigate to `[plugins]`, and ensure:
```
spotify = true
```

## Instructions for casting
Once running goto Spotify on your mobile device and select the devices button.  In the menu of systems select the hostname of your Raspberry Pi to broadcast music.

</details>

<details>
<summary><b>Setup VLC</b> <i>(Linux only)</i></summary>

VLC is installed automatically by `install-linux.sh` (`apt install vlc`) and its plugin is enabled (`vlc = true`) by default in `settings.toml`, so there is normally nothing else to install.

### Audio listener (optional)
The VLC plugin includes an optional "audio listener" that watches a local directory (or a mounted USB drive) for audio files and automatically queues/plays them — useful if you want a plug-and-play music player without any casting plugin. Configure it under `[vlc]` in `settings.toml`:
```
listener_enabled=true
listener_source=local
listener_path = "/home/<user>/Music"
listener_shuffle = true
```

</details>

##  Hyperion Ambient Lighting <i>(Linux only, requires X11)</i>
Hyperion can be installed allongside WaveCymatix to control LEDs for more imersive visualizations (via USB Capture Card or Screen Capture).

### Caveats
Screen capture only works on a Desktop environment running X11.  Because of this you have to go into `raspi-config` -> `Advanced Options` -> `Wayland` and choose `x11`.

USB capture cards in my experience have only worked when setting USB to maximum voltage.  You can do that by editing the `/boot/firmware/config.txt` with a line at the end for `usb_max_current_enable=1`.  Reboot when done.

Capture picture decimation should be set at minimum of 4, and the refresh rate should not exceed 30 to ensure you dont overload the system.

### Installation
First run the Hyperion installer to obtain the latest version:
```
curl -sSL https://releases.hyperion-project.org/install | bash
```

Once done you will need to disable the system service if you want to enable screen :
```
sudo systemctl disable hyperion@.service
```

Now create an XDG autostart entry so that when hyperion runs it inherits the user environment allowing QT screen capture.  

Run `sudo nano /etc/xdg/autostart/hyperion.desktop` and add the following execution details:
```
[Desktop Entry]
Name=Hyperion
Exec=/usr/bin/hyperiond
Type=Application
```

Reboot the application and you should be able to load the hyperion web UI at http://<SYSTEM_IP>:8090/

## Composite Video <i>(Raspberry Pi specific)</i>

### Video overscan
If you notice that the composite display is wider that your screen, you can set the kernel parameters to adjust the margins of the screen to fit your display.  To do this edit the /boot/firmware/cmdline.txt and add the following to the end of the first line:
```
sudo nano /boot/firmware/cmdline.txt
```

#### Composite:
```
video=Composite-1:720x576@60,margin_left=10,margin_right=18,margin_top=10,margin_bottom=20
```

#### HDMI with composite video conversion adapter:
```
video=HDMI-A-1:720x576@60,margin_left=10,margin_right=18,margin_top=10,margin_bottom=20
```
***Note:** This is just an example.  Ensure you are specifying the device/resolution you have chosen for your setup.*

---

Next: [Configuration](SETUP.md#%EF%B8%8F-configuration) in [SETUP.md](SETUP.md).
