#!/usr/bin/env bash

# Extract the Operating System string
OS_INFO=$(hostnamectl 2>/dev/null | grep "Operating System" || true)
IS_TRIXIE="false"

# Check if hostnamectl output contains "trixie" and warn for RPI users
if echo "$OS_INFO" | grep -iq "trixie"; then
    IS_TRIXIE="true"
    echo "=========================================================="
    echo "⚠️  WARNING: DEBIAN TRIXIE DETECTED ⚠️"
    echo "There is a known issue with Mesa/V3d on trixie causing crashes."
    echo ""
    echo "The issue is isolated to specific projectM visualization presets"
    echo "that have complex warp and compositing effects.  If you choose"
    echo "to proceed it is recommended to use the X11 backend for projectM."
    echo "Visual performance policy will also be enabled."
    echo "=========================================================="
    
else
    echo "System compatibility check passed."
fi

INSTALLATION_MODE=""
INSTALLATION_MODE_EXPLICIT="false"
PLUGIN_ONLY="false"
INSTALLATION_PROFILE=""
INSTALLATION_PROFILE_EXPLICIT="false"
INSTALLATION_PLUGINS=""
INSTALLATION_AUTOSTART="preserve"
NO_AUTOSTART="false"
INSTALLATION_HYPERION="false"
INSTALLATION_LOCAL="false"
INSTALLATION_SOURCE=""
INSTALLATION_USER=""
INSTALLATION_LEGACY_PATH="/opt/ProjectMAR"
INSTALLATION_PATH="/opt/WaveCymatix"
OUTPUT_DIR_EXPLICIT="false"
PURGE="false"
REBUILD_PROJECTM="false"
REINSTALL_VENV="false"
REFRESH_PREREQS="false"
REFRESH_CONTENT="false"
RESET_CONFIG="false"
DRY_RUN="false"
YES="false"
VERBOSE="false"
WAVECYMATIX_REF=""
PROJECTM_REF=""
ASSETS_REF=""
INSTALLATION_LOGFILE=""
TARGET_HOME=""
TARGET_UID=""
MANIFEST_ACTIVE="false"
INSTALLATION_PATH_TOUCHED="false"
TEMP_INSTALLER_CORE=""

TMP_BUILDS=""
VIDEO_OUTPUT=""
RASPBERRYPI="false"

LIBPROJECTM_VERSION=""
LIBPROJECTM_RENDERER=""
LIBPROJECTM_RENDERER_MARKER="/usr/local/share/WaveCymatix/libprojectm-renderer"

REQUIRED_PYTHON_VERSION=""
WAVECYMATIX_PYTHON=""
VENV_PATH=""
VENV_PYTHON=""
STAGE_DIR=""
HAD_USER_CONFIG="false"
SOURCE_REPO=""
SOURCE_COMMIT=""
RESOLVED_SOURCE_REF=""
ASSETS_COMMIT=""
RESOLVED_ASSETS_REF=""
INSTALLER_API=""
SUPPORTED_INSTALLER_API=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALLER_CORE="$REPO_ROOT/bin/installer_core.py"
INSTALLER_ENV="$SCRIPT_DIR/installer.env"
APP_REPO=""
APP_DEFAULT_REF=""
ASSETS_REPO=""
ASSETS_DEFAULT_REF=""
PROJECTM_REPO=""
PROJECTM_DEFAULT_REF=""
PROJECTM_CMAKE_FLAGS_LINUX=""
VCPKG_REPO=""
VCPKG_REF=""

MIN_CMAKE_VERSION=""
CMAKE_VERSION=""
NODE_VERSION=""
PLEXAMP_VERSION=""
BLUEZ_VERSION=""
SHAIRPORT_SYNC_VERSION=""
NQPTP_VERSION=""
SPOTIFYD_VERSION=""

PERFORMANCE_TIER_VERY_LOW="very_low"
PERFORMANCE_TIER_LOW="low"
PERFORMANCE_TIER_MEDIUM="medium"
PERFORMANCE_TIER_HIGH="high"

PERFORMANCE_TIER_DEFAULT="$PERFORMANCE_TIER_LOW"

# Raspberry Pi / very-low-performance hardware
PERFORMANCE_VERY_LOW_PATTERNS=(
    'brcm,bcm2710'
    'Raspberry Pi 3'
)

# Low-performance hardware
PERFORMANCE_LOW_PATTERNS=(
    'brcm,bcm2711'
    'Raspberry Pi 4'
)

# Medium-performance hardware
PERFORMANCE_MEDIUM_PATTERNS=(
    'brcm,bcm2712'
    'Raspberry Pi 5'
    'VMware SVGA II Adapter'
)

PERFORMANCE_HIGH_PATTERNS=()

# Command-line interface and logging
usage() {
    cat << EOF
Usage: sudo ./bin/install-linux.sh [options]

The installer must be run as root through sudo. SUDO_USER identifies the
desktop user who owns the installation and receives desktop launchers.

Options:
    -m, --mode <mode>       Operation: install, update, or uninstall.
                            Defaults to update when installed, otherwise install.
    -P, --profile <name>    Performance profile: minimal or optimized
                            (default: optimized for a fresh config).

    -l, --local-install     Install application files from a local checkout.
                            Without --source, the checkout is resolved from
                            the repository root containing this script:
                            <repository>/bin/install-linux.sh -> <repository>.

    -s, --source <path>     Use the specified local repository as the source
                            for WaveCymatix application files. This option
                            automatically enables local-install behavior, so
                            --local-install is not required when --source is
                            supplied.

                            The path must contain pyproject.toml and src/wavecymatix/, and
                            conf/. Relative paths are resolved from the
                            current working directory. Use an absolute path
                            when invoking the installer from another folder.

                            --source affects the WaveCymatix application
                            files only. Presets, textures, and sprites are
                            still downloaded from the visual-assets repository.

    -a, --autostart         Create and globally enable a systemd user service
                            that starts WaveCymatix automatically.
    --no-autostart          Disable the WaveCymatix autostart entry.

    -p, --plugins <list>    Install one or more optional audio plugins.
                            Supply a comma-separated list with no spaces:
                            bluetooth         Bluetooth audio
                            shairport-sync    AirPlay audio
                            spotifyd          Spotify Connect
                            plexamp           Plexamp

                            When used alone without --mode, installs plugins
                            only and requires an existing WaveCymatix install.
                            Combine with --mode update to update the app too.

    --hyperion              Install and configure the Hyperion ambient
                            lighting system.
    -o, --output-dir <path> Installation directory (default: /opt/WaveCymatix).
    --ref <ref|latest>      WaveCymatix source ref (default: latest stable release).
    --projectm-ref <ref>    Select a projectM tag, branch, or commit. When
                            omitted, updates retain the installed source ref.
    --assets-ref <ref>      Visual-assets ref (default: main).
    --user <name>           Target user; defaults to SUDO_USER.
    --rebuild-projectm      Rebuild projectM regardless of its stamp.
    --reinstall-venv        Recreate the application virtual environment.
    --refresh-prereqs       Refresh apt package metadata.
    --refresh-content       Force visual-assets resync even when the commit matches.
    --reset-config          Back up the current config and use release defaults.
    --yes                   Accept supported non-interactive choices; cannot suppress
                            OS authentication or PlexAmp registration.
    --dry-run               Print the planned operation without changing files.
    --verbose               Show detailed, timestamped installer logs on the console.
    --purge                 Remove retained user data during uninstall.

    -h, --help              Display this usage information.

Installation notes:
    -m is optional. It defaults to install or update based on install state,
    except --plugins without --mode runs a plugin-only operation.
    --source implies --local-install; if both are supplied, --source selects
    the repository path.
    Updates preserve the virtual environment, user data, configuration,
    custom content, and runtime artifacts.
    The visual-assets repository is always downloaded separately.

Examples (run from the repository root):
    First install with hardware tuning (normal default profile):
        sudo ./bin/install-linux.sh --mode install --profile optimized

    First install with minimal performance settings:
        sudo ./bin/install-linux.sh --mode install --profile minimal

    Update the installed application and preserve config (default behavior):
        sudo ./bin/install-linux.sh --mode update

    Update and replace config with release defaults (backs up current config):
        sudo ./bin/install-linux.sh --mode update --reset-config

    Enable autostart and install plugins during an install/update:
        sudo ./bin/install-linux.sh --mode update --autostart --plugins bluetooth,shairport-sync

    Install/update with Hyperion:
        sudo ./bin/install-linux.sh --mode update --hyperion

    Use a local checkout for application files:
        sudo ./bin/install-linux.sh --mode update --source /home/user/src/WaveCymatix

    Choose a release and a non-default installation directory:
        sudo ./bin/install-linux.sh --mode update --ref latest --output-dir /srv/WaveCymatix

    Force content and package metadata refresh; show detailed logs:
        sudo ./bin/install-linux.sh --mode update --refresh-content --refresh-prereqs --verbose

    Preview an install without changing files:
        sudo ./bin/install-linux.sh --mode install --profile optimized --dry-run

    Uninstall the application but keep config, data, content, and runtime:
        sudo ./bin/install-linux.sh --mode uninstall

    Uninstall and remove the entire installation directory and retained data:
        sudo ./bin/install-linux.sh --mode uninstall --purge

    Install for a named desktop user when SUDO_USER is unavailable:
        sudo ./bin/install-linux.sh --mode install --user <linux-user>

    Use a specific WaveCymatix branch/tag/commit instead of the latest release:
        sudo ./bin/install-linux.sh --mode update --ref <tag-branch-or-commit>

    Force a projectM rebuild:
        sudo ./bin/install-linux.sh --mode update --rebuild-projectm

    Install plugins on an existing installation without --mode:
        sudo ./bin/install-linux.sh --plugins bluetooth,spotifyd

    Update WaveCymatix and install plugins in the same operation:
        sudo ./bin/install-linux.sh --mode update --plugins bluetooth,spotifyd

    Show all options:
        sudo ./bin/install-linux.sh --help
EOF
}

log() {
  local message
  message="$(date +'%Y-%m-%d %H:%M:%S') - WaveCymatix Installer - $1"
  echo "$message" >> "$INSTALLATION_LOGFILE"
  if [ "$VERBOSE" = "true" ]; then echo "$message"; fi
}

progress() {
    log "$1"
    if [ "$VERBOSE" != "true" ]; then echo "$1"; fi
}

read_installer_env() {
    local path="$1" key value seen="|"
    [ -f "$path" ] || { echo "Missing shared installer configuration: $path" >&2; return 1; }
    while IFS='=' read -r key value || [ -n "$key" ]; do
        key="$(printf '%s' "${key%%#*}" | tr -d '[:space:]')"
        [ -z "$key" ] && continue
        case "$seen" in *"|$key|"*) echo "Duplicate installer.env key: $key" >&2; return 1 ;; esac
        seen="$seen$key|"
        value="${value%%#*}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        case "$key" in
            APP_REPO) APP_REPO="$value" ;;
            APP_DEFAULT_REF) APP_DEFAULT_REF="$value" ;;
            ASSETS_REPO) ASSETS_REPO="$value" ;;
            ASSETS_DEFAULT_REF) ASSETS_DEFAULT_REF="$value" ;;
            PROJECTM_REPO) PROJECTM_REPO="$value" ;;
            PROJECTM_VERSION) LIBPROJECTM_VERSION="$value" ;;
            PROJECTM_RENDERER) LIBPROJECTM_RENDERER="$value" ;;
            PROJECTM_DEFAULT_REF) PROJECTM_DEFAULT_REF="$value" ;;
            PROJECTM_CMAKE_FLAGS_LINUX) PROJECTM_CMAKE_FLAGS_LINUX="$value" ;;
            PYTHON_VERSION) REQUIRED_PYTHON_VERSION="$value" ;;
            MIN_CMAKE_VERSION) MIN_CMAKE_VERSION="$value" ;;
            NODE_VERSION) NODE_VERSION="$value" ;;
            PLEXAMP_VERSION) PLEXAMP_VERSION="$value" ;;
            DEJAVU_FONT_VERSION|DEJAVU_FONT_URL|DEJAVU_FONT_SHA256|LIBERATION_FONT_VERSION|LIBERATION_FONT_URL) ;;
            CMAKE_VERSION) CMAKE_VERSION="$value" ;;
            BLUEZ_VERSION) BLUEZ_VERSION="$value" ;;
            SHAIRPORT_SYNC_VERSION) SHAIRPORT_SYNC_VERSION="$value" ;;
            NQPTP_VERSION) NQPTP_VERSION="$value" ;;
            SPOTIFYD_VERSION) SPOTIFYD_VERSION="$value" ;;
            INSTALLER_API) INSTALLER_API="$value" ;;
            PROJECTM_CMAKE_FLAGS_WINDOWS|PROJECTM_CMAKE_FLAGS_MACOS|VCPKG_REPO|VCPKG_REF|WIN_VS_GENERATOR|WIN_CMAKE_ARCH|WIN_GIT_PACKAGE_ID|WIN_CMAKE_PACKAGE_ID|WIN_PYTHON_PACKAGE_PREFIX|WIN_FFMPEG_PACKAGE_ID|WIN_VLC_PACKAGE_ID) ;;
            *) echo "Unknown installer.env key: $key" >&2; return 1 ;;
        esac
    done < "$path"
    [ -n "$INSTALLER_API" ] && [ -n "$APP_REPO" ] && [ -n "$APP_DEFAULT_REF" ] &&
        [ -n "$ASSETS_REPO" ] && [ -n "$ASSETS_DEFAULT_REF" ] &&
        [ -n "$PROJECTM_REPO" ] && [ -n "$LIBPROJECTM_VERSION" ] &&
        [ -n "$LIBPROJECTM_RENDERER" ] && [ -n "$PROJECTM_CMAKE_FLAGS_LINUX" ] &&
        [ -n "$REQUIRED_PYTHON_VERSION" ] && [ -n "$MIN_CMAKE_VERSION" ] &&
        [ -n "$NODE_VERSION" ] && [ -n "$PLEXAMP_VERSION" ] && [ -n "$CMAKE_VERSION" ] &&
        [ -n "$BLUEZ_VERSION" ] && [ -n "$SHAIRPORT_SYNC_VERSION" ] &&
        [ -n "$NQPTP_VERSION" ] && [ -n "$SPOTIFYD_VERSION" ] || {
            echo "installer.env is missing required values." >&2
            return 1
        }
    [[ "$INSTALLER_API" =~ ^[0-9]+$ ]] || { echo "INSTALLER_API must be an integer." >&2; return 1; }
    [[ "$LIBPROJECTM_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "PROJECTM_VERSION must be a numeric version." >&2; return 1; }
    [[ "$REQUIRED_PYTHON_VERSION" =~ ^[0-9]+\.[0-9]+$ ]] || { echo "PYTHON_VERSION must be a major.minor version." >&2; return 1; }
    [[ "$MIN_CMAKE_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "MIN_CMAKE_VERSION must be a numeric version." >&2; return 1; }
    [[ "$NODE_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "NODE_VERSION must be a numeric version." >&2; return 1; }
    [[ "$PLEXAMP_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "PLEXAMP_VERSION must be a numeric version." >&2; return 1; }
}

run_installer_core() {
    "$WAVECYMATIX_PYTHON" "$INSTALLER_CORE" "$@"
}

manifest_get() {
    run_installer_core manifest-get --output "$INSTALLATION_PATH" --key "$1"
}

record_manifest_operation() {
    local action="$1"
    shift
    run_installer_core manifest-operation --output "$INSTALLATION_PATH" --action "$action" "$@"
}

record_manifest_component() {
    local name="$1" status="$2" details=""
    shift 2
    if [ "$#" -gt 0 ]; then
        details=$(printf '%s\n' "$@" | "$WAVECYMATIX_PYTHON" -c \
            'import json,sys; values=sys.stdin.read().splitlines(); print(json.dumps(dict(zip(values[::2], values[1::2]))))') || return 1
    fi
    local args=(manifest-component --output "$INSTALLATION_PATH" --name "$name" --status "$status")
    [ -n "$details" ] && args+=(--details "$details")
    run_installer_core "${args[@]}"
}

projectm_component() {
    local action="$1" source_type="$2" ref="$3" commit="$4" toolchain="$5"
    local build_settings="$6" allow_legacy="$7"
    shift 7
    local encoded_settings
    encoded_settings=$(printf '%s' "$build_settings" | "$WAVECYMATIX_PYTHON" -c \
        'import base64,sys; print(base64.b64encode(sys.stdin.buffer.read()).decode("ascii"))') || return 1
    local args=(projectm-component --output "$INSTALLATION_PATH" --action "$action"
        --version "$LIBPROJECTM_VERSION" --renderer "$LIBPROJECTM_RENDERER"
        --source-type "$source_type" --ref "$ref" --commit "$commit"
        --toolchain "$toolchain" --build-settings-base64 "$encoded_settings")
    [ "$allow_legacy" = "true" ] && args+=(--allow-legacy)
    local artifact
    for artifact in "$@"; do args+=(--artifact "$artifact"); done
    run_installer_core "${args[@]}"
}

manifest_exit_handler() {
    local exit_status=$1 failed_command="${2:-unknown command}"
    if [ "$MANIFEST_ACTIVE" = "true" ] && [ "$exit_status" -ne 0 ]; then
        record_manifest_operation failed \
            --error "Command failed with status $exit_status: $failed_command" || \
            echo "Failed to record installer failure in the manifest." >&2
    fi
    if [ -n "$TEMP_INSTALLER_CORE" ]; then
        rm -f "$TEMP_INSTALLER_CORE"
        TEMP_INSTALLER_CORE=""
    fi
    if [ "$INSTALLATION_PATH_TOUCHED" = "true" ] &&
        [ -d "$INSTALLATION_PATH" ]; then
        adjust_user_permissions "$INSTALLATION_PATH" || {
            echo "Failed to restore ownership and user permissions for $INSTALLATION_PATH." >&2
            [ "$exit_status" -ne 0 ] || exit_status=1
        }
    fi
    return "$exit_status"
}

begin_uninstall_manifest() {
    [ "$PURGE" != "true" ] || return 0
    [ -f "$INSTALLATION_PATH/.install-state.json" ] || return 0
    [ -f "$INSTALLER_CORE" ] || {
        echo "Cannot update uninstall manifest: installer helper is missing." >&2
        return 1
    }
    WAVECYMATIX_PYTHON="${INSTALLATION_PATH}/.venv/bin/python"
    [ -x "$WAVECYMATIX_PYTHON" ] || WAVECYMATIX_PYTHON="${INSTALLATION_PATH}/venv/bin/python"
    [ -x "$WAVECYMATIX_PYTHON" ] || WAVECYMATIX_PYTHON="${INSTALLATION_PATH}/env/bin/python"
    [ -x "$WAVECYMATIX_PYTHON" ] || WAVECYMATIX_PYTHON="$(command -v python3 || true)"
    [ -n "$WAVECYMATIX_PYTHON" ] || {
        echo "Cannot update uninstall manifest: Python 3 is unavailable." >&2
        return 1
    }
    TEMP_INSTALLER_CORE=$(mktemp "${TMPDIR:-/tmp}/wavecymatix-installer-core.XXXXXX") || return 1
    trap 'manifest_exit_handler "$?" "$BASH_COMMAND"' EXIT
    cp "$INSTALLER_CORE" "$TEMP_INSTALLER_CORE" || return 1
    INSTALLER_CORE="$TEMP_INSTALLER_CORE"
    record_manifest_operation begin || return 1
    MANIFEST_ACTIVE="true"
    record_manifest_component application in_progress || return 1
    record_manifest_component autostart in_progress || return 1
}

finish_uninstall_manifest() {
    [ "$MANIFEST_ACTIVE" = "true" ] || return 0
    record_manifest_component application removed || return 1
    record_manifest_component autostart removed || return 1
    record_manifest_operation succeeded || return 1
    MANIFEST_ACTIVE="false"
}

resolve_target_user() {
    if [ -n "$INSTALLATION_USER" ]; then
        SUDO_USER="$INSTALLATION_USER"
    fi
    if [ -z "${SUDO_USER:-}" ] || [ "$SUDO_USER" = "root" ]; then
        echo "Run the installer with sudo from a desktop user session or specify --user <name>." >&2
        return 1
    fi
    TARGET_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    if [ -z "$TARGET_HOME" ] || [ ! -d "$TARGET_HOME" ]; then
        echo "Unable to resolve home directory for target user '$SUDO_USER'." >&2
        return 1
    fi
    TARGET_UID=$(id -u "$SUDO_USER") || return 1
    INSTALLATION_LOGFILE="$TARGET_HOME/WaveCymatix-installer.log"
}

# Build and dependency helpers
ensure_cmake() {
    log "Checking CMake version"

    if command -v cmake >/dev/null 2>&1; then
        current_version=$(cmake --version | head -n1 | awk '{print $3}')

        if printf '%s\n%s\n' "$MIN_CMAKE_VERSION" "$current_version" | sort -V -C; then
            log "Using system CMake $current_version"
            CMAKE_BIN="$(command -v cmake)"
            return 0
        fi

        log "System CMake $current_version is too old"
    else
        log "CMake not installed"
    fi

    # install_portable_cmake

    if ! install_portable_cmake; then
        log "ERROR: Failed to install portable CMake"
        return 1
    fi

    return 0
}

install_portable_cmake() {
    log "Installing portable CMake $CMAKE_VERSION"

    local arch
    local cmake_arch
    local cmake_tar
    local cmake_archive
    local cmake_dir

    arch=$(uname -m)

    case "$arch" in
        aarch64|arm64)
            cmake_arch="linux-aarch64"
            ;;
        x86_64|amd64)
            cmake_arch="linux-x86_64"
            ;;
        *)
            log "ERROR: Unsupported architecture for portable CMake: $arch"
            return 1
            ;;
    esac

    mkdir -p "$TMP_BUILDS"

    cmake_tar="cmake-${CMAKE_VERSION}-${cmake_arch}.tar.gz"
    cmake_archive="$TMP_BUILDS/$cmake_tar"
    cmake_dir="$TMP_BUILDS/cmake-${CMAKE_VERSION}-${cmake_arch}"

    # Always remove an incomplete previous extraction.
    if [ -d "$cmake_dir" ] && [ ! -x "$cmake_dir/bin/cmake" ]; then
        log "Removing incomplete CMake installation: $cmake_dir"
        rm -rf "$cmake_dir"
    fi

    # Download CMake.
    if [ ! -f "$cmake_archive" ]; then
        log "Downloading CMake archive: $cmake_tar"

        if ! wget \
            "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/${cmake_tar}" \
            -O "$cmake_archive"; then

            log "ERROR: Failed to download CMake archive"
            rm -f "$cmake_archive"
            return 1
        fi
    else
        log "Using existing CMake archive: $cmake_archive"
    fi

    # Extract CMake.
    if [ ! -d "$cmake_dir" ]; then
        log "Extracting CMake archive"

        if ! tar xf "$cmake_archive" -C "$TMP_BUILDS"; then
            log "ERROR: Failed to extract CMake archive"
            return 1
        fi
    fi

    # Verify the expected CMake executable exists.
    if [ ! -f "$cmake_dir/bin/cmake" ]; then
        log "ERROR: CMake archive did not produce expected executable:"
        log "  $cmake_dir/bin/cmake"
        log "Extracted CMake directories:"
        find "$TMP_BUILDS" -maxdepth 2 -type f -name cmake -print >> "$INSTALLATION_LOGFILE"
        return 1
    fi

    # Ensure it is executable.
    if [ ! -x "$cmake_dir/bin/cmake" ]; then
        chmod +x "$cmake_dir/bin/cmake" || {
            log "ERROR: Cannot make CMake executable: $cmake_dir/bin/cmake"
            return 1
        }
    fi

    CMAKE_BIN="$cmake_dir/bin/cmake"

    # Verify CMake actually runs.
    local cmake_version_output

    if ! cmake_version_output=$("$CMAKE_BIN" --version 2>&1); then
        log "ERROR: Portable CMake exists but cannot execute:"
        log "  $CMAKE_BIN"
        log "CMake output: $cmake_version_output"
        return 1
    fi

    log "Using portable CMake: $(printf '%s\n' "$cmake_version_output" | head -n1)"

    return 0
}


is_version_at_least() {
    local current="$1"
    local required="$2"

    if [ -z "$current" ]; then
        return 1
    fi

    printf '%s\n%s\n' "$required" "$current" | sort -V -C
}

set_WaveCymatix_plugin_enabled() {
    local plugin_key="$1"
    local config_path="${STAGE_DIR:-$INSTALLATION_PATH}/conf/settings.toml"

    if [ ! -f "$config_path" ]; then
        log "Unable to update plugin state in config. File not found: $config_path"
        return 1
    fi

    run_installer_core configure-settings --config "$config_path" \
        --set "plugins.$plugin_key=true" || return 1

    log "Set plugin '$plugin_key' to true in settings.toml"
}

enable_WaveCymatix_plugin_from_switch() {
    local plugin_switch="$1"

    case "$plugin_switch" in
        bluetooth)
            set_WaveCymatix_plugin_enabled "bluetooth"
            ;;
        shairport-sync)
            set_WaveCymatix_plugin_enabled "airplay"
            ;;
        spotifyd)
            set_WaveCymatix_plugin_enabled "spotify"
            ;;
        plexamp)
            set_WaveCymatix_plugin_enabled "plexamp"
            ;;
        *)
            log "No WaveCymatix plugin mapping found for switch: $plugin_switch"
            ;;
    esac
}

# Installs the first available package name (names differ across Debian releases, e.g. t64 transition)
install_first_available() {
    local pkg
    for pkg in "$@"; do
        if apt-cache show "$pkg" >/dev/null 2>&1; then
            apt install -y "$pkg" && return 0
        fi
    done
    log "WARNING: none of these packages could be installed: $*"
    return 1
}

# Runtime dependencies shared by the base install and multiple plugins; always installed
install_common_dependencies() {
    log "Installing common dependencies"

    if [ "$REFRESH_PREREQS" = "true" ]; then apt update; fi
    apt install -y pulseaudio python3-dev gcc vlc libopenblas0 libopenblas-dev libsdl2-dev portaudio19-dev default-libmysqlclient-dev fonts-dejavu-core fonts-liberation curl git wget ca-certificates \
        avahi-daemon libpulse0 libdbus-1-3 dbus

    install_first_available libasound2t64 libasound2
    install_first_available libssl3t64 libssl3

    systemctl enable --now avahi-daemon.service >/dev/null 2>&1 || true
}

adjust_user_permissions() {
    local path="$1"
    chown -R "$SUDO_USER":"$(id -gn "$SUDO_USER")" "$path" || {
        log "ERROR: Failed to set owner $SUDO_USER for $path"
        return 1
    }
    chmod -R u+rwX,go+rX "$path" || {
        log "ERROR: Failed to set user permissions for $path"
        return 1
    }
}

# Hardware and platform detection
is_desktop() {
    if command -v systemctl >/dev/null 2>&1; then
        [ "$(systemctl get-default 2>/dev/null)" = "graphical.target" ] && return 0
        systemctl is-enabled display-manager.service >/dev/null 2>&1 && return 0
    fi

    for dm in gdm gdm3 lightdm sddm greetd lxdm xdm; do
        command -v "$dm" >/dev/null 2>&1 && return 0
    done

    return 1
}

detect_performance_tier() {
    local hardware_info=""
    local pattern

    if [ -r /proc/device-tree/model ]; then
        hardware_info+="$(tr -d '\0' < /proc/device-tree/model)"
        hardware_info+=$'\n'
    fi

    if [ -r /proc/device-tree/compatible ]; then
        hardware_info+="$(tr '\0' '\n' < /proc/device-tree/compatible)"
        hardware_info+=$'\n'
    fi

    # PCI graphics hardware.
    if command -v lspci >/dev/null 2>&1; then
        hardware_info+="$(lspci 2>/dev/null | grep -Ei 'vga|3d|display|graphics')"
        hardware_info+=$'\n'
    fi

    log "Detected hardware information: $hardware_info"

    for pattern in "${PERFORMANCE_HIGH_PATTERNS[@]}"; do
        if [[ "$hardware_info" =~ $pattern ]]; then
            PERFORMANCE_TIER="$PERFORMANCE_TIER_HIGH"
            log "High performance GPU identified: $pattern"
            return 0
        fi
    done

    for pattern in "${PERFORMANCE_MEDIUM_PATTERNS[@]}"; do
        if [[ "$hardware_info" =~ $pattern ]]; then
            PERFORMANCE_TIER="$PERFORMANCE_TIER_MEDIUM"
            log "Medium performance GPU identified: $pattern"
            return 0
        fi
    done

    for pattern in "${PERFORMANCE_LOW_PATTERNS[@]}"; do
        if [[ "$hardware_info" =~ $pattern ]]; then
            PERFORMANCE_TIER="$PERFORMANCE_TIER_LOW"
            log "Low performance GPU identified: $pattern"
            return 0
        fi
    done

    for pattern in "${PERFORMANCE_VERY_LOW_PATTERNS[@]}"; do
        if [[ "$hardware_info" =~ $pattern ]]; then
            PERFORMANCE_TIER="$PERFORMANCE_TIER_VERY_LOW"
            log "Very low performance GPU identified: $pattern"
            return 0
        fi
    done

    PERFORMANCE_TIER="$PERFORMANCE_TIER_DEFAULT"

    log "Unable to identify GPU performance class"
    log "Defaulting to $PERFORMANCE_TIER performance tier"

    return 0
}

enforce_python_version() {
    log "Checking Python version..."

    local system_python
    local detected_version
    local uv_bin
    local python_install_dir

    # First, see what python3 the system provides.
    system_python="$(command -v python3 || true)"

    if [ -n "$system_python" ] && [ -x "$system_python" ]; then
        detected_version="$("$system_python" -c \
            'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' \
            2>/dev/null || true)"

        if [ "$detected_version" = "$REQUIRED_PYTHON_VERSION" ]; then
            WAVECYMATIX_PYTHON="$system_python"
            log "Found required Python $REQUIRED_PYTHON_VERSION at $WAVECYMATIX_PYTHON"
            return 0
        fi

        log "System Python is ${detected_version:-unknown}; required Python is $REQUIRED_PYTHON_VERSION"
    else
        log "No usable system python3 was found"
    fi

    # ------------------------------------------------------------------
    # The system Python isn't the required version.
    # Use uv to install an isolated copy without replacing system Python.
    # ------------------------------------------------------------------

    uv_bin="$(command -v uv || true)"

    if [ -z "$uv_bin" ]; then
        log "uv is not installed; installing uv..."

        if ! command -v curl >/dev/null 2>&1; then
            log "curl is required to install uv"
            return 1
        fi

        # Install uv system-wide.
        if ! curl -LsSf https://astral.sh/uv/install.sh | \
            env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh; then
            log "Failed to install uv"
            return 1
        fi

        uv_bin="$(command -v uv || true)"

        if [ -z "$uv_bin" ]; then
            log "uv installation completed but the uv executable was not found"
            return 1
        fi
    fi

    log "Installing Python $REQUIRED_PYTHON_VERSION with uv..."

    # Keep the managed Python installation separate from the system Python.
    #
    # This can be changed to /opt/WaveCymatix/python if you prefer the
    # Python installation to live entirely with WaveCymatix.
    python_install_dir="${INSTALLATION_PATH:-/opt/WaveCymatix}/python"

    mkdir -p "$python_install_dir"

    if ! UV_PYTHON_INSTALL_DIR="$python_install_dir" \
        "$uv_bin" python install "$REQUIRED_PYTHON_VERSION"; then
        log "Failed to install Python $REQUIRED_PYTHON_VERSION"
        return 1
    fi

    # Ask uv where the exact requested Python executable is.
    WAVECYMATIX_PYTHON="$(
        UV_PYTHON_INSTALL_DIR="$python_install_dir" \
        "$uv_bin" python find "$REQUIRED_PYTHON_VERSION" 2>/dev/null
    )"

    if [ -z "$WAVECYMATIX_PYTHON" ] || [ ! -x "$WAVECYMATIX_PYTHON" ]; then
        log "Could not locate installed Python $REQUIRED_PYTHON_VERSION"
        return 1
    fi

    # Verify that we actually got what we requested.
    detected_version="$(
        "$WAVECYMATIX_PYTHON" -c \
        'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' \
        2>/dev/null
    )"

    if [ "$detected_version" != "$REQUIRED_PYTHON_VERSION" ]; then
        log "Python version mismatch: found $detected_version, expected $REQUIRED_PYTHON_VERSION"
        WAVECYMATIX_PYTHON=""
        return 1
    fi

    log "Using Python $detected_version at $WAVECYMATIX_PYTHON"

    return 0
}


is_library_current() {
    ldconfigOutput=$(ldconfig -v)
    if [[ "$ldconfigOutput" =~ $1 ]]; then
        return 0
    else
        return 1
    fi
}

is_libprojectm_renderer_current() {
    if [ -f "$LIBPROJECTM_RENDERER_MARKER" ]; then
        marker_renderer=$(cat "$LIBPROJECTM_RENDERER_MARKER")
        [ "$marker_renderer" = "$LIBPROJECTM_RENDERER" ]
        return $?
    fi

    return 1
}

install_libprojectm() {
    local stamp_version stamp_renderer stamp_ref stamp_commit expected_ref source_dir build_dir archive checkout flags projectm_commit
    local source_type build_settings toolchain stamp_toolchain library_path playlist_path check_result current_cmake compiler_version
    stamp_version=$(manifest_get "components.projectm.version")
    stamp_renderer=$(manifest_get "components.projectm.renderer")
    stamp_ref=$(manifest_get "components.projectm.ref")
    stamp_commit=$(manifest_get "components.projectm.commit")
    stamp_toolchain=$(manifest_get "components.projectm.toolchain")
    expected_ref="v$LIBPROJECTM_VERSION"
    projectm_commit=""
    if [ -n "$PROJECTM_REF" ]; then
        expected_ref="$PROJECTM_REF"
        checkout=$(run_installer_core checkout --repo "$PROJECTM_REPO" --ref "$PROJECTM_REF" \
            --cache "$TMP_BUILDS/projectm-source") || return 1
        source_dir=$(printf '%s' "$checkout" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["path"])')
        projectm_commit=$(printf '%s' "$checkout" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["commit"])')
    elif [ "$REBUILD_PROJECTM" != "true" ] &&
        is_library_current "libprojectM-4.so.$LIBPROJECTM_VERSION" &&
        is_libprojectm_renderer_current &&
        [ "$stamp_version" = "\"$LIBPROJECTM_VERSION\"" ] &&
        [ "$stamp_renderer" = "\"$LIBPROJECTM_RENDERER\"" ] &&
        [ "$stamp_ref" != "null" ]; then
        expected_ref=$(printf '%s' "$stamp_ref" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin))') || return 1
        projectm_commit=$(printf '%s' "$stamp_commit" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin))') || return 1
    fi
    source_type="release-tarball"
    [ -n "$projectm_commit" ] && source_type="git"
    library_path=$(ldconfig -p 2>/dev/null | awk '$1 == "libprojectM-4.so.4" { print $NF; exit }')
    playlist_path=$(ldconfig -p 2>/dev/null | awk '$1 == "libprojectM-4-playlist.so.4" { print $NF; exit }')
    current_cmake=$(cmake --version 2>/dev/null | head -n1)
    [ -n "$current_cmake" ] || current_cmake="$CMAKE_VERSION"
    compiler_version=$(c++ --version 2>/dev/null | head -n1)
    toolchain="$current_cmake; $compiler_version; $(uname -m)"
    if [ -z "$PROJECTM_REF" ] && [ "$REBUILD_PROJECTM" != "true" ] &&
        [ "$stamp_toolchain" != "null" ]; then
        toolchain=$(printf '%s' "$stamp_toolchain" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin))') || return 1
    fi
    build_settings=$(printf '%s' "$PROJECTM_CMAKE_FLAGS_LINUX" | "$WAVECYMATIX_PYTHON" -c \
        'import json,shlex,sys; print(json.dumps({"cmake_flags": shlex.split(sys.stdin.read()), "build_type":"Release", "install_prefix":"/usr/local"}, sort_keys=True))') || return 1
    local artifacts=("libprojectM-4.so.4=$library_path" "libprojectM-4-playlist.so.4=$playlist_path")

    if [ "$REBUILD_PROJECTM" != "true" ] && [ -n "$library_path" ] && [ -n "$playlist_path" ]; then
        check_result=$(projectm_component check "$source_type" "$expected_ref" "$projectm_commit" \
            "$toolchain" "$build_settings" true "${artifacts[@]}") || return 1
    else
        check_result='{"matches": false}'
    fi
    if [ "$REBUILD_PROJECTM" != "true" ] &&
        [ "$(printf '%s' "$check_result" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["matches"])')" = "True" ]; then
        log "libprojectM $LIBPROJECTM_VERSION ($LIBPROJECTM_RENDERER) is current"
        projectm_component stamp "$source_type" "$expected_ref" "$projectm_commit" \
            "$toolchain" "$build_settings" false "${artifacts[@]}" >/dev/null || return 1
        return 0
    fi

    log "Installing libprojectM $LIBPROJECTM_VERSION with the $LIBPROJECTM_RENDERER renderer"
    apt install -y build-essential cmake libgl1-mesa-dev mesa-common-dev libglm-dev mesa-utils flex bison
    ensure_cmake || { log "ERROR: Could not obtain a usable CMake"; return 1; }
    current_cmake=$("$CMAKE_BIN" --version 2>/dev/null | head -n1)
    toolchain="$current_cmake; $compiler_version; $(uname -m)"
    if [ -n "$PROJECTM_REF" ]; then
        PROJECTM_COMMIT="$projectm_commit"
        git -C "$source_dir" submodule update --init --recursive || return 1
        build_dir="$TMP_BUILDS/projectm-git-build"
    else
        archive="$TMP_BUILDS/libprojectM-$LIBPROJECTM_VERSION.tar.gz"
        source_dir="$TMP_BUILDS/libprojectM-$LIBPROJECTM_VERSION"
        if [ ! -f "$archive" ]; then
            wget -O "$archive" "${PROJECTM_REPO%.git}/releases/download/v$LIBPROJECTM_VERSION/libprojectM-$LIBPROJECTM_VERSION.tar.gz" || return 1
        fi
        if [ ! -d "$source_dir" ]; then
            tar xf "$archive" -C "$TMP_BUILDS" || return 1
        fi
        PROJECTM_COMMIT=""
        build_dir="$TMP_BUILDS/projectm-release-build"
    fi

    if [ "$REBUILD_PROJECTM" = "true" ] || [ "$stamp_ref" != "\"$expected_ref\"" ]; then
        rm -rf "$build_dir"
    fi
    if [ "$stamp_commit" != "\"$projectm_commit\"" ]; then
        rm -rf "$build_dir"
    fi
    read -r -a flags <<< "$PROJECTM_CMAKE_FLAGS_LINUX"
    "$CMAKE_BIN" "${flags[@]}" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -S "$source_dir" -B "$build_dir" || return 1
    if grep -q "^ENABLE_GLES:BOOL=ON" "$build_dir/CMakeCache.txt"; then
        log "CMake configuration mismatch: ENABLE_GLES resolved to ON while OpenGL Core is required"
        return 1
    fi
    "$CMAKE_BIN" --build "$build_dir" --parallel "$(nproc)" || return 1
    record_manifest_component projectm in_progress || return 1
    local install_root staged_libdir staged_marker
    install_root=$(mktemp -d "$TMP_BUILDS/projectm-install.XXXXXX") || return 1
    DESTDIR="$install_root" "$CMAKE_BIN" --install "$build_dir" || {
        rm -rf "$install_root"
        return 1
    }
    staged_libdir="$install_root/usr/local/lib"
    local -a install_args=(install-files)
    local -a staged_libraries=("$staged_libdir"/libprojectM-4.so* "$staged_libdir"/libprojectM-4-playlist.so*)
    local artifact
    for artifact in "${staged_libraries[@]}"; do
        if [ -e "$artifact" ] || [ -L "$artifact" ]; then
            install_args+=(--file "$artifact=/usr/local/lib/$(basename "$artifact")")
        fi
    done
    if [ "${#install_args[@]}" -eq 1 ]; then
        rm -rf "$install_root"
        log "ERROR: projectM install did not stage runtime libraries"
        return 1
    fi
    staged_marker="$install_root/libprojectm-renderer"
    printf '%s\n' "$LIBPROJECTM_RENDERER" > "$staged_marker" || {
        rm -rf "$install_root"
        return 1
    }
    install_args+=(--file "$staged_marker=$LIBPROJECTM_RENDERER_MARKER")
    run_installer_core "${install_args[@]}" || {
        rm -rf "$install_root"
        return 1
    }
    rm -rf "$install_root"
    ldconfig || return 1
    library_path=$(ldconfig -p 2>/dev/null | awk '$1 == "libprojectM-4.so.4" { print $NF; exit }')
    playlist_path=$(ldconfig -p 2>/dev/null | awk '$1 == "libprojectM-4-playlist.so.4" { print $NF; exit }')
    artifacts=("libprojectM-4.so.4=$library_path" "libprojectM-4-playlist.so.4=$playlist_path")
    projectm_component stamp "$source_type" "$expected_ref" "${PROJECTM_COMMIT:-}" \
        "$toolchain" "$build_settings" false "${artifacts[@]}" >/dev/null || return 1
}

cleanup_previous_installation() {
    local uninstall="${1:-false}"
    local user_id="$TARGET_UID"
    log "Removing WaveCymatix application files"
    if command -v systemctl >/dev/null 2>&1; then
        if [ -n "$user_id" ]; then
            runuser -u "$SUDO_USER" -- env XDG_RUNTIME_DIR="/run/user/$user_id" \
                systemctl --user disable --now wave-cymatix.service >/dev/null 2>&1 || true
        fi
        systemctl --global disable wave-cymatix.service >/dev/null 2>&1 || true
    fi
    rm -f /etc/systemd/user/wave-cymatix.service || return 1
    rm -f "$TARGET_HOME/.config/systemd/user/wave-cymatix.service" || return 1
    rm -f "$TARGET_HOME/.config/autostart/WaveCymatix.desktop" || return 1
    rm -f "$TARGET_HOME/Desktop/WaveCymatix.sh" || return 1
    stop_wavecymatix

    if [ "$uninstall" = "true" ]; then
        if [ "$PURGE" = "true" ]; then
            rm -rf "$INSTALLATION_PATH" || return 1
        else
            for item in assets bin core docs lib resources WaveCymatix.py requirements.txt VERSION run-wavecymatix.sh .new .prev .content-new .content-prev .app-prev; do
                rm -rf "$INSTALLATION_PATH/$item" || return 1
            done
            log "Retained config, data, content, runtime and build cache. Use --purge to remove them."
        fi
    fi
    log "WaveCymatix application cleanup complete"
}

stop_wavecymatix() {
    local pid command interpreter
    for interpreter in "$INSTALLATION_PATH/.venv/bin/python" "$INSTALLATION_PATH/venv/bin/python" "$INSTALLATION_PATH/env/bin/python"; do
        while read -r pid command; do
            [ -n "$pid" ] || continue
            case "$command" in
                *"$interpreter"*)
                    log "Stopping WaveCymatix process $pid"
                    kill -TERM "$pid" 2>/dev/null || true
                    ;;
            esac
        done < <(ps -eo pid=,args=)
    done
    sleep 1
    for interpreter in "$INSTALLATION_PATH/.venv/bin/python" "$INSTALLATION_PATH/venv/bin/python" "$INSTALLATION_PATH/env/bin/python"; do
        while read -r pid command; do
            [ -n "$pid" ] || continue
            case "$command" in
                *"$interpreter"*) kill -KILL "$pid" 2>/dev/null || true ;;
            esac
        done < <(ps -eo pid=,args=)
    done
}

resolve_source_repository() {
    local requested_ref resolved_source
    local -a source_args
    requested_ref="${WAVECYMATIX_REF:-$APP_DEFAULT_REF}"
    source_args=(resolve-source --ref "$requested_ref" \
        --cache "$INSTALLATION_PATH/runtime/cache/wavecymatix" \
        --output "$INSTALLATION_PATH" --supported-api "$SUPPORTED_INSTALLER_API")
    if [ "$INSTALLATION_LOCAL" = "true" ]; then
        SOURCE_REPO="${INSTALLATION_SOURCE:-$REPO_ROOT}"
        source_args+=(--source "$SOURCE_REPO")
    else
        source_args+=(--repo "$APP_REPO")
    fi
    resolved_source=$(run_installer_core "${source_args[@]}") || return 1
    SOURCE_REPO=$(printf '%s' "$resolved_source" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["path"])') || return 1
    SOURCE_COMMIT=$(printf '%s' "$resolved_source" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["commit"])') || return 1
    RESOLVED_SOURCE_REF=$(printf '%s' "$resolved_source" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["ref"])') || return 1
    if [ "$INSTALLATION_LOCAL" != "true" ] &&
        [ "$requested_ref" != "latest" ] &&
        [[ ! "$requested_ref" =~ ^v[0-9] ]]; then
        log "WARNING: non-release WaveCymatix ref selected: $requested_ref"
    fi
    read_installer_env "$SOURCE_REPO/bin/installer.env" || return 1
}

# Application installation and configuration
install_WaveCymatix() {
    log "Installing WaveCymatix"
    if [ -z "$WAVECYMATIX_PYTHON" ] || [ ! -x "$WAVECYMATIX_PYTHON" ]; then
        log "WaveCymatix Python has not been configured"
        return 1
    fi

    local assets_ref prepare_args prepare_result
    assets_ref="${ASSETS_REF:-$ASSETS_DEFAULT_REF}"
    prepare_args=(prepare-application --source "$SOURCE_REPO" \
        --output "$INSTALLATION_PATH" --python "$WAVECYMATIX_PYTHON" \
        --required-python "$REQUIRED_PYTHON_VERSION" \
        --supported-api "$SUPPORTED_INSTALLER_API" \
        --assets-repo "$ASSETS_REPO" --assets-ref "$assets_ref")
    [ "$REINSTALL_VENV" = "true" ] && prepare_args+=(--reinstall-venv)
    [ "$REFRESH_CONTENT" = "true" ] && prepare_args+=(--refresh-content)
    [ "$RESET_CONFIG" = "true" ] && prepare_args+=(--reset-config)
    prepare_result=$(run_installer_core "${prepare_args[@]}") || return 1
    STAGE_DIR=$(printf '%s' "$prepare_result" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["stage_dir"])') || return 1
    VENV_PATH=$(printf '%s' "$prepare_result" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["venv_path"])') || return 1
    VENV_PYTHON=$(printf '%s' "$prepare_result" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["venv_python"])') || return 1
    ASSETS_COMMIT=$(printf '%s' "$prepare_result" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["assets_commit"])') || return 1
    RESOLVED_ASSETS_REF=$(printf '%s' "$prepare_result" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["assets_ref"])') || return 1
    HAD_USER_CONFIG=$(printf '%s' "$prepare_result" | "$WAVECYMATIX_PYTHON" -c 'import json,sys; print(str(json.load(sys.stdin)["had_user_config"]).lower())') || return 1
    adjust_user_permissions "$INSTALLATION_PATH"

    if is_desktop; then
        printf '%s\n' "#!/bin/sh" "exec \"$INSTALLATION_PATH/.venv/bin/wavecymatix\"" > "$TARGET_HOME/Desktop/WaveCymatix.sh"
        chmod +x "$TARGET_HOME/Desktop/WaveCymatix.sh"
        chown "$SUDO_USER":"$(id -gn "$SUDO_USER")" "$TARGET_HOME/Desktop/WaveCymatix.sh"
    fi
}

configure_WaveCymatix() {
    log "Configuring WaveCymatix"

    local config_file="$STAGE_DIR/conf/settings.toml"
    local settings_args=(configure-settings --config "$config_file")
    settings_args+=(--set projectm.window.fullscreen=true)

    if [ "$VIDEO_OUTPUT" = "composite" ]; then
        settings_args+=(--set projectm.window.fullscreen.width=720)
        settings_args+=(--set projectm.window.fullscreen.height=480)
        settings_args+=(--set projectm.window.width=600)
        settings_args+=(--set projectm.window.height=400)
    fi

    case "$PERFORMANCE_TIER" in
        "$PERFORMANCE_TIER_LOW")
            if [ "$VIDEO_OUTPUT" = "composite" ]; then
                settings_args+=(--set projectm.window.fullscreen.width=720)
                settings_args+=(--set projectm.window.fullscreen.height=576)
                settings_args+=(--set projectm.projectM.fps=30)
                settings_args+=(--set projectm.projectM.meshX=48)
                settings_args+=(--set projectm.projectM.meshY=32)
            else
                settings_args+=(--set projectm.window.fullscreen.width=720)
                settings_args+=(--set projectm.window.fullscreen.height=480)
                settings_args+=(--set projectm.window.width=600)
                settings_args+=(--set projectm.window.height=450)
                settings_args+=(--set projectm.projectM.fps=30)
                settings_args+=(--set projectm.projectM.meshX=48)
                settings_args+=(--set projectm.projectM.meshY=32)
            fi
            ;;
        "$PERFORMANCE_TIER_HIGH")
            if [ "$VIDEO_OUTPUT" != "composite" ]; then
                settings_args+=(--set projectm.window.fullscreen.width=1920)
                settings_args+=(--set projectm.window.fullscreen.height=1080)
                settings_args+=(--set projectm.window.width=1280)
                settings_args+=(--set projectm.window.height=720)
                settings_args+=(--set projectm.projectM.meshX=96)
                settings_args+=(--set projectm.projectM.meshY=54)
            fi
            ;;
    esac

    # Debian trixie has known Mesa/V3D stability issues on Raspberry Pi hardware, so
    # enable the runtime performance safeguards to auto-recover from crashes/stalls.
    if [ "$IS_TRIXIE" = "true" ] && [ "$RASPBERRYPI" = "true" ]; then
        log "Debian trixie on Raspberry Pi detected, enabling performance policy enforcement"
        settings_args+=(--set performance.fps_policy_enabled=true)
        settings_args+=(--set performance.perf_detection_enabled=true)
    fi

    run_installer_core "${settings_args[@]}"
}

configure_WaveCymatix_autostart() {
    log "Configuring WaveCymatix autostart"

    if is_desktop; then
        local autostart_dir="$TARGET_HOME/.config/autostart"
        local autostart_file="$autostart_dir/WaveCymatix.desktop"

        mkdir -p "$autostart_dir"
        cat > "$autostart_file" << EOF
[Desktop Entry]
Type=Application
Name=WaveCymatix
Exec=$INSTALLATION_PATH/.venv/bin/wavecymatix
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
        chown "$SUDO_USER" "$autostart_dir" "$autostart_file"
        log "Configured XDG desktop autostart: $autostart_file"
        return 0
    fi

    local pyopengl_platform=""
    pyopengl_platform="egl"

    local service_file="$TARGET_HOME/.config/systemd/user/wave-cymatix.service"
    mkdir -p "$(dirname "$service_file")"
    cat > "$service_file" << EOF
[Unit]
Description=WaveCymatix
After=default.target pulseaudio.socket
Requires=default.target

[Service]
Type=simple
${pyopengl_platform:+Environment=PYOPENGL_PLATFORM=$pyopengl_platform}
ExecStart=$INSTALLATION_PATH/.venv/bin/wavecymatix
Restart=on-failure

[Install]
WantedBy=default.target
EOF
    chown "$SUDO_USER":"$(id -gn "$SUDO_USER")" "$service_file"
    chmod 644 "$service_file"
    runuser -u "$SUDO_USER" -- env XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user daemon-reload
    runuser -u "$SUDO_USER" -- env XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user enable wave-cymatix.service
}

# Optional audio and ambient-lighting plugins
configure_bluetooth() {
    log "Installing bluetooth plugin"

    # Install distro dependencies first; they can install/replace BlueZ binaries.
    apt install -y pulseaudio-module-bluetooth bluez-tools || return 1

    install_bluez_for_artwork || {
        log "Failed to update BlueZ for Bluetooth artwork support"
        return 1
    }

    # Setup bt mode
    sed -i 's/^#AlwaysPairable = .*/AlwaysPairable = true/' /etc/bluetooth/main.conf
    sed -i 's/^#PairableTimeout = .*/PairableTimeout = 0/' /etc/bluetooth/main.conf
    sed -i 's/^#\(.*DiscoverableTimeout.*\)/\1/' /etc/bluetooth/main.conf
    sed -i 's/^#Experimental = .*/Experimental = true/' /etc/bluetooth/main.conf

    # restart service
    systemctl daemon-reload
    systemctl restart bluetooth.service || return 1

    # OBEX runs in the desktop user's session, separately from bluetoothd.
    runuser -u "$SUDO_USER" -- env XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user daemon-reload || return 1
    runuser -u "$SUDO_USER" -- env XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user restart obex.service || return 1

    log "Waiting for bluetooth to reinitialize..."
    sleep 5

    # Enable bt adapter and turn on pairable
    # Enable bt adapter configurations in a single non-blocking execution
    printf "power on\ndiscoverable on\npairable on\nquit\n" | bluetoothctl
    # bluetoothctl power on
    # bluetoothctl discoverable on
    # bluetoothctl pairable on
    # bluetoothctl agent on

    if systemctl is-active --quiet bt-agent; then
        log "bt-agent is already installed"
    else
        log "Installing bt-agent"

        # Install bt agent service
        if ! [ -f "/etc/systemd/system/bt-agent.service" ];then
            cat > "/etc/systemd/system/bt-agent.service" << EOF
[Unit]
Description=Bluetooth Auth Agent
After=bluetooth.service
PartOf=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bt-agent -c NoInputNoOutput
KillSignal=SIGUSR1

[Install]
WantedBy=bluetooth.service
EOF
        fi

        # Enable and restart service
        systemctl enable bt-agent
        systemctl start bt-agent
    fi
}

install_bluez_for_artwork() {
    local current_bluez current_obexd_package
    local rebuild_bluez=false obexd_stamp="/var/lib/wavecymatix/bluez-obexd-version"
    local stamped_obexd_version=""
    local obexd_is_custom=false
    # Debian's unit and D-Bus files launch the daemons from /usr/libexec/bluetooth.
    current_bluez="$(/usr/libexec/bluetooth/bluetoothd -v 2>/dev/null)"
    current_obexd_package="$(dpkg-query -W -f='${Version}' bluez-obexd 2>/dev/null || true)"

    if ! is_version_at_least "$current_bluez" "$BLUEZ_VERSION"; then
        rebuild_bluez=true
    fi
    if [ -n "$current_obexd_package" ] &&
        ! dpkg --compare-versions "$current_obexd_package" ge "$BLUEZ_VERSION"; then
        if [ -f "$obexd_stamp" ]; then
            stamped_obexd_version="$(cat "$obexd_stamp")"
        fi
        if [ "$stamped_obexd_version" = "$BLUEZ_VERSION" ] &&
            dpkg -V bluez-obexd 2>/dev/null | grep -Fq '/usr/libexec/bluetooth/obexd'; then
            obexd_is_custom=true
        else
            log "bluez-obexd package $current_obexd_package is older than required BlueZ $BLUEZ_VERSION"
            rebuild_bluez=true
        fi
    fi
    [ "$obexd_is_custom" = "true" ] &&
        log "Custom obexd $BLUEZ_VERSION is installed over the older distro package"

    if [ "$rebuild_bluez" = "false" ]; then
        log "BlueZ $current_bluez is already current for artwork support"
    else
        log "Installing BlueZ $BLUEZ_VERSION with experimental support for album artwork"

        apt install -y \
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
            libtool \
            python3-docutils \
            libsystemd-dev || return 1

        mkdir -p "$TMP_BUILDS" || return 1
        wget "https://github.com/bluez/bluez/archive/refs/tags/${BLUEZ_VERSION}.tar.gz" -O "$TMP_BUILDS/${BLUEZ_VERSION}.tar.gz" || return 1
        tar -xzf "$TMP_BUILDS/${BLUEZ_VERSION}.tar.gz" -C "$TMP_BUILDS" || return 1

        local bluez_source="$TMP_BUILDS/bluez-${BLUEZ_VERSION}"
        cd "$bluez_source" || return 1

        ./bootstrap || return 1
        ./configure \
            --prefix=/usr \
            --sysconfdir=/etc \
            --localstatedir=/var \
            --libexecdir=/usr/libexec \
            --mandir=/usr/share/man \
            --enable-experimental \
            --enable-obex || return 1

        make -j"$(nproc)" || return 1
        make install || return 1
        ldconfig || return 1
        mkdir -p "$(dirname "$obexd_stamp")" || return 1
        printf '%s\n' "$BLUEZ_VERSION" > "$obexd_stamp" || return 1
    fi

    if grep -Eq '^#?[[:space:]]*Experimental[[:space:]]*=' /etc/bluetooth/main.conf; then
        sed -i -E 's/^#?[[:space:]]*Experimental[[:space:]]*=.*/Experimental = true/' /etc/bluetooth/main.conf
    else
        echo "Experimental = true" >> /etc/bluetooth/main.conf
    fi

    return 0
}

install_plugin_bluetooth() {
    # Check if Bluetooth hardware path exists in the Linux kernel
    if [ ! -d "/sys/class/bluetooth" ]; then
        log "ERROR: No Bluetooth hardware detected at /sys/class/bluetooth"
        return 1
    fi

    configure_bluetooth
}

# Removes every shairport-sync install and startup file listed in its BUILD.md; the config is backed up first
uninstall_shairport_sync() {
    log "Removing previous shairport-sync installation"

    systemctl disable --now shairport-sync.service >/dev/null 2>&1 || true
    systemctl --global disable shairport-sync.service >/dev/null 2>&1 || true
    pkill -x shairport-sync >/dev/null 2>&1 || true

    local bin attempt conf service_file
    for attempt in 1 2 3 4 5; do
        bin="$(command -v shairport-sync || true)"
        [ -n "$bin" ] || break
        rm -f "$bin"
        hash -r 2>/dev/null || true
    done

    for conf in /etc/shairport-sync.conf /usr/local/etc/shairport-sync.conf; do
        if [ -f "$conf" ]; then
            cp -a "$conf" "$conf.$(date +%Y%m%d%H%M%S).bak"
            rm -f "$conf"
        fi
    done
    rm -f /etc/shairport-sync.conf.sample /usr/local/etc/shairport-sync.conf.sample

    for service_file in \
        /etc/systemd/system/shairport-sync.service \
        /etc/systemd/user/shairport-sync.service \
        /usr/lib/systemd/system/shairport-sync.service \
        /lib/systemd/system/shairport-sync.service \
        /lib/systemd/user/shairport-sync.service \
        /etc/dbus-1/system.d/shairport-sync-dbus.conf \
        /etc/dbus-1/system.d/shairport-sync-mpris.conf \
        /etc/init.d/shairport-sync \
        "$TARGET_HOME/.config/systemd/user/shairport-sync.service"; do
        rm -f "$service_file"
    done

    systemctl daemon-reload
}

uninstall_nqptp() {
    log "Removing previous nqptp installation"

    systemctl disable --now nqptp.service >/dev/null 2>&1 || true
    pkill -x nqptp >/dev/null 2>&1 || true

    local bin attempt service_file
    for attempt in 1 2 3 4 5; do
        bin="$(command -v nqptp || true)"
        [ -n "$bin" ] || break
        rm -f "$bin"
        hash -r 2>/dev/null || true
    done

    for service_file in \
        /lib/systemd/system/nqptp.service \
        /usr/lib/systemd/system/nqptp.service \
        /usr/local/lib/systemd/system/nqptp.service \
        /etc/systemd/system/nqptp.service; do
        rm -f "$service_file"
    done

    systemctl daemon-reload
}

install_nqptp() {
    log "Installing nqptp $NQPTP_VERSION"

    local source_dir="$TMP_BUILDS/nqptp"
    rm -rf "$source_dir"

    git clone --depth 1 --branch "$NQPTP_VERSION" https://github.com/mikebrady/nqptp.git "$source_dir" || return 1
    cd "$source_dir" || return 1

    autoreconf -fi || return 1
    ./configure --with-systemd-startup --with-systemdsystemunitdir=/lib/systemd/system || return 1
    make -j"$(nproc)" || return 1
    local install_root
    install_root=$(mktemp -d "$TMP_BUILDS/nqptp-install.XXXXXX") || return 1
    make install DESTDIR="$install_root" || {
        rm -rf "$install_root"
        return 1
    }
    install_staged_tree "$install_root" || {
        rm -rf "$install_root"
        return 1
    }
    rm -rf "$install_root"

    systemctl daemon-reload
    systemctl enable nqptp.service || return 1
    systemctl restart nqptp.service || return 1

    log "Installed: $(nqptp -V 2>&1)"
}

install_shairport_sync() {
    log "Installing shairport-sync $SHAIRPORT_SYNC_VERSION"

    local source_dir="$TMP_BUILDS/shairport-sync"
    rm -rf "$source_dir"

    git clone --depth 1 --branch "$SHAIRPORT_SYNC_VERSION" https://github.com/mikebrady/shairport-sync.git "$source_dir" || return 1
    cd "$source_dir" || return 1

    autoreconf -fi || return 1
    ./configure --sysconfdir=/etc --with-alsa --with-pulseaudio \
        --with-soxr --with-avahi --with-ssl=openssl --with-airplay-2 \
        --with-dbus-interface --with-systemd-startup \
        --with-systemdsystemunitdir=/lib/systemd/system || return 1
    make -j"$(safe_build_jobs)" || return 1
    local install_root
    install_root=$(mktemp -d "$TMP_BUILDS/shairport-sync-install.XXXXXX") || return 1
    make install DESTDIR="$install_root" || {
        rm -rf "$install_root"
        return 1
    }
    install_staged_tree "$install_root" || {
        rm -rf "$install_root"
        return 1
    }
    rm -rf "$install_root"

    # WaveCymatix reads the native D-Bus interface from the user session bus
    sed -i 's|^[[:space:]]*//[[:space:]]*dbus_service_bus = "system";|\tdbus_service_bus = "session";|' /etc/shairport-sync.conf

    # PulseAudio is a user service, so shairport-sync must run as one; the system unit from make install stays disabled
    cat > "/etc/systemd/user/shairport-sync.service" << EOF
[Unit]
Description=Shairport Sync - AirPlay Audio Receiver
After=sound.target pulseaudio.service nqptp.service
Requires=pulseaudio.service

[Service]
ExecStart=/usr/local/bin/shairport-sync --log-to-syslog -o pulseaudio
Restart=on-failure

[Install]
WantedBy=default.target
EOF

    systemctl daemon-reload
    systemctl --global enable shairport-sync.service || return 1

    log "Installed: $(shairport-sync -V 2>&1)"
}

install_plugin_shairport-sync() {
    log "Installing shairport-sync plugin"

    # Build dependencies from shairport-sync BUILD.md plus libpulse-dev (PulseAudio backend) and libglib2.0-dev (D-Bus interface)
    apt install -y --no-install-recommends build-essential git autoconf automake libtool pkg-config \
        libpopt-dev libconfig-dev libasound2-dev libpulse-dev avahi-daemon libavahi-client-dev libssl-dev libsoxr-dev \
        libplist-dev libsodium-dev uuid-dev libgcrypt-dev xxd libplist-utils \
        libavutil-dev libavcodec-dev libavformat-dev libglib2.0-dev || return 1

    mkdir -p "$TMP_BUILDS"

    # NQPTP must be updated and running before shairport-sync
    install_nqptp || return 1
    install_shairport_sync || return 1
}

install_staged_tree() {
    local source_root="$1" source_path relative_path destination
    local -a install_args=(install-files)
    while IFS= read -r -d '' source_path; do
        relative_path="${source_path#"$source_root"/}"
        destination="/$relative_path"
        if [ "$destination" = "/etc/shairport-sync.conf" ] &&
            [ -e "$destination" ]; then
            continue
        fi
        install_args+=(--file "$source_path=$destination")
    done < <(find "$source_root" \( -type f -o -type l \) -print0)
    [ "${#install_args[@]}" -gt 1 ] || {
        log "ERROR: Staged component install contains no files: $source_root"
        return 1
    }
    run_installer_core "${install_args[@]}"
}

# Parallel build jobs bounded by available memory (about 1 GB per job) so small boards do not run out of RAM
safe_build_jobs() {
    local mem_mb jobs cpus
    mem_mb="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null)"
    cpus="$(nproc)"
    jobs=$(( ${mem_mb:-1024} / 1024 ))
    [ "$jobs" -lt 1 ] && jobs=1
    [ "$jobs" -gt "$cpus" ] && jobs="$cpus"
    echo "$jobs"
}

# Fallback for prebuilt binaries linked against libraries this OS no longer ships (e.g. OpenSSL 1.1)
build_spotifyd_from_source() {
    log "Building spotifyd $SPOTIFYD_VERSION from source"

    apt install -y build-essential pkg-config libssl-dev libasound2-dev libpulse-dev libdbus-1-dev curl || return 1

    # aws-lc-rs is only a dependency on targets other than aarch64 and x86_64
    case "$(uname -m)" in
        aarch64|arm64|x86_64|amd64) ;;
        *) apt install -y libclang-dev cmake || return 1 ;;
    esac

    # Distro Rust is too old for spotifyd's rust-version, so use rustup's stable
    local rust_home="$TMP_BUILDS/rust"
    mkdir -p "$rust_home"

    if ! [ -x "$rust_home/cargo/bin/cargo" ]; then
        curl -fsSL https://sh.rustup.rs -o "$rust_home/rustup-init.sh" || return 1
        RUSTUP_HOME="$rust_home/rustup" CARGO_HOME="$rust_home/cargo" \
            sh "$rust_home/rustup-init.sh" -y --profile minimal --no-modify-path || return 1
    fi

    # spotifyd's release profile sets lto = true, whose link step needs far more RAM than a 2 GB board has
    local install_root="$TMP_BUILDS/spotifyd-install-root"
    rm -rf "$install_root"
    RUSTUP_HOME="$rust_home/rustup" CARGO_HOME="$rust_home/cargo" \
        CARGO_BUILD_JOBS="$(safe_build_jobs)" CARGO_PROFILE_RELEASE_LTO=off \
        nice -n 19 "$rust_home/cargo/bin/cargo" install spotifyd --version "$SPOTIFYD_VERSION" --locked \
        --root "$install_root" || return 1

    local candidate="$install_root/bin/spotifyd"
    [ -x "$candidate" ] || return 1
    "$candidate" --version >/dev/null 2>&1 || return 1
    run_installer_core install-files --file "$candidate=/usr/local/bin/spotifyd" || return 1
    rm -rf "$install_root"
}

install_plugin_spotifyd() {
    log "Installing spotifyd plugin"
    if ! /usr/local/bin/spotifyd --version >/dev/null 2>&1; then
        log "Installing spotifyd"

        local spotifyd_arch
        case "$(uname -m)" in
            x86_64|amd64)  spotifyd_arch="x86_64" ;;
            aarch64|arm64) spotifyd_arch="aarch64" ;;
            armv7l)        spotifyd_arch="armv7" ;;
            *)
                log "ERROR: Unsupported architecture for spotifyd: $(uname -m)"
                return 1
                ;;
        esac
        local spotifyd_archive="spotifyd-linux-${spotifyd_arch}-full.tar.gz"

        # Download and install spotifyd
        mkdir -p /tmp/Builds
        rm -f /tmp/Builds/spotifyd
        wget "https://github.com/Spotifyd/spotifyd/releases/download/v${SPOTIFYD_VERSION}/${spotifyd_archive}" \
            -O "/tmp/Builds/${spotifyd_archive}" || return 1
        tar xzf "/tmp/Builds/${spotifyd_archive}" -C /tmp/Builds/ || return 1
        local candidate="/tmp/Builds/spotifyd"
        [ -f "$candidate" ] || return 1
        chmod +x "$candidate" || return 1
        chown root:root "$candidate" || return 1
        if ! "$candidate" --version >/dev/null 2>&1 ||
            ldd "$candidate" 2>&1 | grep -q "not found"; then
            log "Prebuilt spotifyd cannot run here; trying a source build"
            build_spotifyd_from_source || {
                log "ERROR: Failed to build spotifyd from source"
                return 1
            }
        else
            run_installer_core install-files --file "$candidate=/usr/local/bin/spotifyd" || return 1
        fi

        if ! [ -f "/etc/systemd/user/spotifyd.service" ];then
            cat > "/etc/systemd/user/spotifyd.service" << EOF
[Unit]
Description=A spotify playing daemon
Documentation=https://github.com/Spotifyd/spotifyd
Wants=sound.target
After=sound.target
Wants=network-online.target
After=network-online.target

[Service]
ExecStart=/usr/local/bin/spotifyd --no-daemon
Restart=always
RestartSec=12

[Install]
WantedBy=default.target
EOF
        fi

        systemctl --global enable spotifyd.service || return 1

    else
        log "spotifyd is already installed"
    fi

    if ! [ -f "/etc/spotifyd.conf" ]; then
        # Download spotifyd configuration file
        wget "https://github.com/Spotifyd/spotifyd/archive/refs/tags/v${SPOTIFYD_VERSION}.tar.gz" -P /tmp/Builds
        tar xf "/tmp/Builds/v${SPOTIFYD_VERSION}.tar.gz" -C /tmp/Builds/
        cp "/tmp/Builds/spotifyd-${SPOTIFYD_VERSION}/contrib/spotifyd.conf" /etc/spotifyd.conf

        # Set WaveCymatix config
        sed -i 's/.*#backend.*/backend = "pulseaudio"/' /etc/spotifyd.conf
        sed -i 's/.*#device_name.*/device_name = "WaveCymatix"/' /etc/spotifyd.conf
        sed -i 's/.*#device_type.*/device_type = "a_v_r"/' /etc/spotifyd.conf
        sed -i 's/.*#use_mpris.*/use_mpris = true/' /etc/spotifyd.conf
        sed -i 's/.*#dbus_type.*/dbus_type = "system"/' /etc/spotifyd.conf
    else
        log "spotifyd configuration file already exists"
    fi

    if ! [ -f "/etc/dbus-1/system.d/rs.spotifyd.conf" ]; then
        # Setup spotifyd dbus permissions
        cat > "/etc/dbus-1/system.d/rs.spotifyd.conf" << EOF
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <!-- Allow any user to own the service and receive messages -->
  <policy context="default">
    <!-- Core spotifyd service ownership -->
    <allow own_prefix="rs.spotifyd"/>
    <allow send_destination="rs.spotifyd"/>

    <!-- MPRIS media player service ownership -->
    <allow own_prefix="org.mpris.MediaPlayer2.spotifyd"/>
    <allow send_destination_prefix="org.mpris.MediaPlayer2.spotifyd"/>
  </policy>
</busconfig>
EOF
        systemctl reload dbus.service >/dev/null 2>&1 || true
    else
        log "spotifyd dbus permissions file already exists"
    fi
}

install_plugin_plexamp() {
    log "Installing PlexAmp plugin"

    log "Checking NodeJs"

    case "$(uname -m)" in
        x86_64)
            NODE_ARCH="x64"
            ;;
        aarch64)
            NODE_ARCH="arm64"
            ;;
        armv7l|armv6l)
            NODE_ARCH="armv7l"
            ;;
        *)
            log "Unsupported CPU architecture: $(uname -m)"
            return 1
            ;;
    esac

    NODE_ARCHIVE="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
    NODE_DIR="/opt/node-v${NODE_VERSION}-linux-${NODE_ARCH}"
    NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_ARCHIVE}"

    CURRENT_NODE_VERSION=""

    if command -v node >/dev/null 2>&1; then
        CURRENT_NODE_VERSION="$(node -p 'process.versions.node')"
        log "Found NodeJs v${CURRENT_NODE_VERSION}"
    else
        log "NodeJs is not installed"
    fi

    if [ "$CURRENT_NODE_VERSION" = "$NODE_VERSION" ]; then
        log "NodeJs v${NODE_VERSION} is already installed"
    else
        log "Installing NodeJs v${NODE_VERSION} for ${NODE_ARCH}"

        if command -v apt-get >/dev/null 2>&1; then
            if dpkg -s nodejs >/dev/null 2>&1; then
                log "Removing distro NodeJs package"
                apt-get purge -y nodejs
            fi
        elif command -v dnf >/dev/null 2>&1; then
            if rpm -q nodejs >/dev/null 2>&1; then
                log "Removing distro NodeJs package"
                dnf remove -y nodejs
            fi
        elif command -v yum >/dev/null 2>&1; then
            if rpm -q nodejs >/dev/null 2>&1; then
                log "Removing distro NodeJs package"
                yum remove -y nodejs
            fi
        fi

        mkdir -p /tmp/Builds
        log "Downloading ${NODE_URL}"
        curl -fL "$NODE_URL" -o "/tmp/Builds/${NODE_ARCHIVE}" || {
            log "ERROR: Failed to download NodeJs"
            return 1
        }

        log "Installing NodeJs to ${NODE_DIR}"
        rm -rf "$NODE_DIR"
        tar -xJf "/tmp/Builds/${NODE_ARCHIVE}" -C /opt

        if [ ! -x "${NODE_DIR}/bin/node" ]; then
            log "ERROR: NodeJs installation directory was not found:"
            log "${NODE_DIR}"
            return 1
        fi

        ln -sfn "${NODE_DIR}/bin/node" /usr/bin/node
        ln -sfn "${NODE_DIR}/bin/npm" /usr/bin/npm
        ln -sfn "${NODE_DIR}/bin/npx" /usr/bin/npx
        ln -sfn "${NODE_DIR}/bin/corepack" /usr/bin/corepack
        hash -r 2>/dev/null || true

        INSTALLED_NODE_VERSION="$("${NODE_DIR}/bin/node" -p 'process.versions.node')"
        if [ "$INSTALLED_NODE_VERSION" != "$NODE_VERSION" ]; then
            log "ERROR: NodeJs installation failed"
            log "Expected: v${NODE_VERSION}"
            log "Found: v${INSTALLED_NODE_VERSION}"
            return 1
        fi

        log "NodeJs v${INSTALLED_NODE_VERSION} installed successfully"
    fi

    if ! [ -f "/opt/plexamp/js/index.js" ]; then
        log "Installing PlexAmp"

        # Download and install Plexamp
        mkdir -p /tmp/Builds
        wget "https://plexamp.plex.tv/headless/Plexamp-Linux-headless-v${PLEXAMP_VERSION}.tar.bz2" \
            -P /tmp/Builds || return 1
        tar xvjf "/tmp/Builds/Plexamp-Linux-headless-v${PLEXAMP_VERSION}.tar.bz2" -C /tmp/Builds/ || return 1
        [ -f "/tmp/Builds/plexamp/js/index.js" ] || {
            log "ERROR: PlexAmp archive did not contain the application entry point"
            return 1
        }
        local plexamp_stage="/opt/.plexamp.install.$$"
        rm -rf "$plexamp_stage"
        cp -a /tmp/Builds/plexamp "$plexamp_stage" || return 1
        rm -rf /opt/plexamp || {
            rm -rf "$plexamp_stage"
            return 1
        }
        mv "$plexamp_stage" /opt/plexamp || {
            rm -rf "$plexamp_stage"
            return 1
        }
        if ! [ -f "/etc/systemd/user/plexamp.service" ];then
            cat > "/etc/systemd/user/plexamp.service" << EOF
[Unit]
Description=Plexamp
After=pulseaudio.service
Requires=pulseaudio.service

[Service]
ExecStart=/usr/bin/node /opt/plexamp/js/index.js
Restart=on-failure

[Install]
WantedBy=default.target
EOF
        fi

        systemctl --global enable plexamp.service || return 1
    else
        log "PlexAmp is already installed"
    fi

    # Setup your Plexamp token
    log "Checking for PlexAmp registration"
    if ! [ -f "$TARGET_HOME/.local/share/Plexamp/Settings/%40Plexamp%3Auser%3AsubscriptionActive" ]; then
        echo "PlexAmp has not been registered!"
        echo "Please run 'node /opt/plexamp/js/index.js' in a seperate terminal to register with Plex"
        if [ "$YES" = "true" ]; then
            echo "PlexAmp registration is still required; complete it after installation."
            log "Skipping interactive PlexAmp registration wait because --yes was supplied"
        else
            read -p "Press any key to continue once complete..." complete </dev/tty
        fi
    else
        log "PlexAmp registration is current"
    fi
}

install_hyperion() {
    record_manifest_component hyperion in_progress || return 1
    log "Installing Hyperion"
    curl -sSL https://releases.hyperion-project.org/install | bash
    systemctl disable hyperion@root.service
    systemctl stop hyperion@root.service
    rm /etc/systemd/system/hyperion@.service
    if ! [ -f "/etc/systemd/user/hyperion.service" ];then
        cat > "/etc/systemd/user/hyperion.service" << EOF
[Unit]
Description=Hyperion ambient light systemd service for user %i
Documentation=https://docs.hyperion-project.org
After=default.target pulseaudio.socket
Requires=default.target

[Service]
ExecStart=/usr/bin/hyperiond
WorkingDirectory=/usr/share/hyperion/bin
TimeoutStopSec=5
KillMode=mixed
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
        systemctl --global enable hyperion.service
    else
        log "Hyperion is already installed"
    fi
    record_manifest_component hyperion installed state installed || return 1
}

ARGS=$(getopt -o lm:aP:p:s:o:h \
              -l local-install,mode:,profile:,autostart,no-autostart,plugins:,source:,output-dir:,hyperion,ref:,projectm-ref:,assets-ref:,user:,rebuild-projectm,reinstall-venv,refresh-prereqs,refresh-content,reset-config,yes,dry-run,verbose,purge,help \
              -n "install-linux.sh" -- "$@")

if [ $? -ne 0 ]; then
    usage
    exit 1
fi

eval set -- "$ARGS"

while true; do
    case "$1" in
        -m|--mode)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_MODE="$2"
            INSTALLATION_MODE_EXPLICIT="true"
            shift 2
        ;;
        -P|--profile)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_PROFILE="$2"
            INSTALLATION_PROFILE_EXPLICIT="true"
            shift 2
        ;;
        -a|--autostart)
            INSTALLATION_AUTOSTART="true"
            shift
        ;;
        --no-autostart)
            NO_AUTOSTART="true"
            shift
        ;;
        -l|--local-install)
            INSTALLATION_LOCAL="true"
            shift
        ;;
        -p|--plugins)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_PLUGINS="$2"
            shift 2
        ;;
        -s|--source)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_LOCAL="true"
            INSTALLATION_SOURCE="$2"
            shift 2
        ;;
        -o|--output-dir)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_PATH="$2"
            OUTPUT_DIR_EXPLICIT="true"
            shift 2
        ;;
        --ref)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            WAVECYMATIX_REF="$2"
            shift 2
        ;;
        --projectm-ref)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            PROJECTM_REF="$2"
            shift 2
        ;;
        --assets-ref)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            ASSETS_REF="$2"
            shift 2
        ;;
        --user)
            [ -n "${2:-}" ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_USER="$2"
            shift 2
        ;;
        --rebuild-projectm)
            REBUILD_PROJECTM="true"
            shift
        ;;
        --reinstall-venv)
            REINSTALL_VENV="true"
            shift
        ;;
        --refresh-prereqs)
            REFRESH_PREREQS="true"
            shift
        ;;
        --refresh-content)
            REFRESH_CONTENT="true"
            shift
        ;;
        --reset-config)
            RESET_CONFIG="true"
            shift
        ;;
        --yes)
            YES="true"
            shift
        ;;
        --dry-run)
            DRY_RUN="true"
            shift
        ;;
        --verbose)
            VERBOSE="true"
            shift
        ;;
        --purge)
            PURGE="true"
            shift
        ;;
        --hyperion)
            INSTALLATION_HYPERION="true"
            shift
        ;;
        -h|--help)
            usage
            exit 0
        ;;
        --)
            shift
            break
        ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
        ;;
    esac
done

if [ "$INSTALLATION_AUTOSTART" = "true" ] && [ "$NO_AUTOSTART" = "true" ]; then
    echo "Use only one of --autostart or --no-autostart." >&2
    exit 1
fi
if [ "$PURGE" = "true" ] && [ "$INSTALLATION_MODE" != "uninstall" ]; then
    echo "--purge is only valid with --mode uninstall." >&2
    exit 1
fi
if [ "$INSTALLATION_MODE" = "uninstall" ] &&
    { [ -n "$INSTALLATION_PLUGINS" ] || [ -n "$WAVECYMATIX_REF" ] || [ -n "$PROJECTM_REF" ] || [ -n "$ASSETS_REF" ] || [ "$INSTALLATION_AUTOSTART" = "true" ] || [ "$NO_AUTOSTART" = "true" ] || [ "$RESET_CONFIG" = "true" ] || [ "$REINSTALL_VENV" = "true" ] || [ "$REFRESH_PREREQS" = "true" ] || [ "$REFRESH_CONTENT" = "true" ] || [ "$YES" = "true" ] || [ -n "$INSTALLATION_SOURCE" ] || [ "$INSTALLATION_LOCAL" = "true" ] || [ "$REBUILD_PROJECTM" = "true" ] || [ -n "$INSTALLATION_PROFILE" ] || [ "$INSTALLATION_HYPERION" = "true" ]; }; then
    echo "Install/update options cannot be combined with --mode uninstall." >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ] && [ "$DRY_RUN" != "true" ]; then
    echo "Run the Linux installer as root through sudo." >&2
    exit 1
fi
if [ "$DRY_RUN" != "true" ]; then
    resolve_target_user || exit 1
fi
read_installer_env "$INSTALLER_ENV" || exit 1
SUPPORTED_INSTALLER_API="$INSTALLER_API"
if [ "$INSTALLATION_MODE_EXPLICIT" = "false" ] &&
    [ -n "$INSTALLATION_PLUGINS" ] &&
    [ "$INSTALLATION_PROFILE_EXPLICIT" = "false" ] &&
    [ "$INSTALLATION_AUTOSTART" = "preserve" ] &&
    [ "$NO_AUTOSTART" = "false" ] &&
    [ -z "$WAVECYMATIX_REF" ] &&
    [ -z "$PROJECTM_REF" ] &&
    [ -z "$ASSETS_REF" ] &&
    [ "$REINSTALL_VENV" = "false" ] &&
    [ "$REFRESH_PREREQS" = "false" ] &&
    [ "$REFRESH_CONTENT" = "false" ] &&
    [ "$RESET_CONFIG" = "false" ] &&
    [ "$INSTALLATION_LOCAL" = "false" ] &&
    [ "$REBUILD_PROJECTM" = "false" ] &&
    [ "$REBUILD_PROJECTM" = "false" ] &&
    [ "$INSTALLATION_HYPERION" = "false" ]; then
    PLUGIN_ONLY="true"
    INSTALLATION_MODE="plugins"
fi
if [ -n "$INSTALLATION_MODE" ]; then
    case "$INSTALLATION_MODE" in
        plugins)
            [ "$PLUGIN_ONLY" = "true" ] || {
                echo "Unsupported mode: $INSTALLATION_MODE" >&2
                usage
                exit 1
            }
            ;;
        install|update|uninstall) ;;
        *) echo "Unsupported mode: $INSTALLATION_MODE" >&2; usage; exit 1 ;;
    esac
else
    if [ -f "$INSTALLATION_PATH/.venv/bin/wavecymatix" ] || [ -f "$INSTALLATION_PATH/.install-state.json" ]; then
        INSTALLATION_MODE="update"
    else
        INSTALLATION_MODE="install"
    fi
fi
if [ "$INSTALLATION_MODE" != "uninstall" ] &&
    [ "$INSTALLATION_MODE" != "plugins" ] &&
    [ -z "$INSTALLATION_PROFILE" ]; then
    INSTALLATION_PROFILE="optimized"
fi
if [ -n "$INSTALLATION_PROFILE" ]; then
    case "$INSTALLATION_PROFILE" in minimal|optimized) ;; *) echo "Unsupported profile: $INSTALLATION_PROFILE" >&2; exit 1 ;; esac
fi
if [ "$INSTALLATION_PROFILE_EXPLICIT" = "true" ] &&
    [ -f "$INSTALLATION_PATH/conf/settings.toml" ] &&
    [ "$RESET_CONFIG" != "true" ] &&
    [ "$INSTALLATION_MODE" != "uninstall" ]; then
    echo "The existing config is being preserved; use --reset-config to apply profile defaults." >&2
fi
if [ -n "$INSTALLATION_PLUGINS" ]; then
    IFS=',' read -ra requested_plugins <<< "$INSTALLATION_PLUGINS"
    for requested_plugin in "${requested_plugins[@]}"; do
        requested_plugin="${requested_plugin//[[:space:]]/}"
        case "$requested_plugin" in
            bluetooth|shairport-sync|spotifyd|plexamp) ;;
            *) echo "Unsupported plugin requested: $requested_plugin" >&2; exit 1 ;;
        esac
    done
fi
TMP_BUILDS="$INSTALLATION_PATH/runtime/build-cache"

if [ "$DRY_RUN" = "true" ]; then
    requested_ref="${WAVECYMATIX_REF:-$APP_DEFAULT_REF}"
    refresh_note=""
    [ "$REFRESH_CONTENT" = "true" ] && refresh_note="; force visual-assets resync"
    echo "Dry run: would run '$INSTALLATION_MODE' from ref '$requested_ref' in '$INSTALLATION_PATH'$refresh_note."
    exit 0
fi
if [ "$IS_TRIXIE" = "true" ] && [ "$YES" != "true" ] && [ "$INSTALLATION_MODE" != "uninstall" ]; then
    read -r -p "Do you still want to proceed? (y/N): " response
    case "$response" in
        [yY][eE][sS]|[yY]) echo "Proceeding with caution..." ;;
        *) echo "Operation cancelled by user. Exiting."; exit 1 ;;
    esac
fi

trap 'manifest_exit_handler "$?" "$BASH_COMMAND"' EXIT

# Phase 1: preflight
if [ -e "$INSTALLATION_LOGFILE" ]; then
    idx=1
    while [ -e "${INSTALLATION_LOGFILE}.${idx}" ]; do idx=$((idx + 1)); done
    mv "$INSTALLATION_LOGFILE" "${INSTALLATION_LOGFILE}.${idx}"
fi
INSTALLATION_PATH_TOUCHED="true"
mkdir -p "$TMP_BUILDS"

if [ "$INSTALLATION_MODE" = "uninstall" ]; then
    begin_uninstall_manifest || exit 1
    cleanup_previous_installation true || exit 1
    finish_uninstall_manifest || exit 1
    exit 0
fi

if [ ! -f "$INSTALLER_CORE" ]; then
    echo "Shared installer helper is missing: $INSTALLER_CORE" >&2
    exit 1
fi

if [ "$PLUGIN_ONLY" = "true" ]; then
    if [ ! -f "$INSTALLATION_PATH/.venv/bin/wavecymatix" ] ||
        [ ! -f "$INSTALLATION_PATH/conf/settings.toml" ]; then
        echo "Plugin-only installation requires an existing WaveCymatix install with conf/settings.toml at $INSTALLATION_PATH. Use --mode install or --mode update to install the application." >&2
        exit 1
    fi

    for python_candidate in \
        "$INSTALLATION_PATH/.venv/bin/python" \
        "$INSTALLATION_PATH/venv/bin/python" \
        "$INSTALLATION_PATH/env/bin/python"; do
        if [ -x "$python_candidate" ]; then
            WAVECYMATIX_PYTHON="$python_candidate"
            break
        fi
    done
    if [ -z "$WAVECYMATIX_PYTHON" ]; then
        echo "Plugin-only installation requires the existing WaveCymatix Python environment, but no supported environment was found under $INSTALLATION_PATH." >&2
        exit 1
    fi

    adjust_user_permissions "$INSTALLATION_PATH" || exit 1
    mkdir -p "$TMP_BUILDS" || exit 1
    record_manifest_operation begin || exit 1
    MANIFEST_ACTIVE="true"

    progress "Installing requested plugins without updating WaveCymatix"
    IFS=',' read -ra parts <<< "$INSTALLATION_PLUGINS"
    for part in "${parts[@]}"; do
        part="${part//[[:space:]]/}"
        plugin_function="install_plugin_$part"
        record_manifest_component "plugin-$part" in_progress || exit 1
        "$plugin_function" || {
            log "Plugin installation failed for: $part"
            exit 1
        }
        enable_WaveCymatix_plugin_from_switch "$part" || {
            log "Failed to update configuration for plugin: $part"
            exit 1
        }
        case "$part" in
            bluetooth) plugin_version="$BLUEZ_VERSION" ;;
            shairport-sync) plugin_version="$SHAIRPORT_SYNC_VERSION" ;;
            spotifyd) plugin_version="$SPOTIFYD_VERSION" ;;
            plexamp) plugin_version="$PLEXAMP_VERSION" ;;
        esac
        record_manifest_component "plugin-$part" installed version "$plugin_version" || exit 1
    done
    record_manifest_operation succeeded || exit 1
    MANIFEST_ACTIVE="false"
    log "Requested plugin installation completed successfully."
    exit 0
fi

# Determine the output video mode
VIDEO_OUTPUT="hdmi"

for status in /sys/class/drm/*/status; do
    [ -f "$status" ] || continue

    connector=$(basename "$(dirname "$status")")
    state=$(cat "$status")

    case "$connector" in
        *Composite*)
            if [ "$state" = "connected" ]; then
                log "Composite display mode has been identified"
                VIDEO_OUTPUT="composite"
                break
            fi
            ;;
        *HDMI*)
            if [ "$state" = "connected" ]; then
                log "HDMI display mode has been identified"
                VIDEO_OUTPUT="hdmi"
                break
            fi
            ;;
    esac
done

if [ "$VIDEO_OUTPUT" = "hdmi" ]; then
    log "HDMI output mode selected"
fi

if is_desktop; then
    log "The device is running desktop OS"
else
    log "The device is running headless/lite OS"
fi

detect_performance_tier || {
    log "Failed to detect GPU performance tier"
    exit 1
}

# Determine the Raspberry Pi model
cpuInfo=$(cat /proc/cpuinfo)
if [[ "$cpuInfo" =~ "Raspberry Pi" ]]; then
    log "Raspberry Pi has been detected"
    RASPBERRYPI="true"
fi

# Phase 2: prerequisites
progress "Running WaveCymatix $INSTALLATION_MODE (profile: ${INSTALLATION_PROFILE:-unchanged})"
progress "Installing system prerequisites"
install_common_dependencies || { log "Failed to install common dependencies"; exit 1; }
usermod -aG input "$SUDO_USER"
systemctl --global -q disable pipewire-pulse
systemctl --global -q disable wireplumber
systemctl --global -q enable pulseaudio
if [ -e /etc/alsa/conf.d/99-pipewire-default.conf ]; then rm /etc/alsa/conf.d/99-pipewire-default.conf; fi

enforce_python_version || { log "Failed to obtain Python $REQUIRED_PYTHON_VERSION"; exit 1; }
saved_autostart=$(manifest_get "components.autostart.state")
if [ "$saved_autostart" = "null" ]; then
    saved_autostart=$(manifest_get "options.autostart")
fi
if [ "$INSTALLATION_AUTOSTART" = "preserve" ]; then
    if [ "$NO_AUTOSTART" = "true" ]; then
        INSTALLATION_AUTOSTART="false"
    elif [ "$saved_autostart" = "\"installed\"" ] || [ "$saved_autostart" = "true" ]; then
        INSTALLATION_AUTOSTART="true"
    else
        INSTALLATION_AUTOSTART="false"
    fi
fi
record_manifest_operation begin || exit 1
MANIFEST_ACTIVE="true"
trap 'manifest_exit_handler "$?" "$BASH_COMMAND"' EXIT

# Phase 3: projectM
progress "Resolving WaveCymatix source"
resolve_source_repository || { log "Failed to resolve valid WaveCymatix source"; exit 1; }
stop_wavecymatix
progress "Preparing projectM runtime"
install_libprojectm || { log "Failed to install libprojectM"; exit 1; }

# Phase 4: WaveCymatix
progress "Staging application and visual assets"
install_WaveCymatix || { log "Failed to stage WaveCymatix"; exit 1; }
if [ "$HAD_USER_CONFIG" = "false" ] && [ "$INSTALLATION_PROFILE" = "optimized" ]; then
    configure_WaveCymatix || {
        log "Failed to configure WaveCymatix defaults"
        exit 1
    }
fi
if [ -n "$INSTALLATION_PLUGINS" ]; then
    IFS=',' read -ra parts <<< "$INSTALLATION_PLUGINS"
    for part in "${parts[@]}"; do
        part="${part//[[:space:]]/}"
        enable_WaveCymatix_plugin_from_switch "$part" || {
            log "Failed to update configuration for plugin: $part"
            exit 1
        }
    done
fi
progress "Validating and applying staged application files"
stop_wavecymatix
commit_args=(commit-application --stage "$STAGE_DIR" \
    --output "$INSTALLATION_PATH" --python "$VENV_PYTHON" \
    --source-ref "$RESOLVED_SOURCE_REF" --source-commit "$SOURCE_COMMIT" \
    --assets-ref "$RESOLVED_ASSETS_REF" --assets-commit "$ASSETS_COMMIT")
[ "$INSTALLATION_LOCAL" = "true" ] && commit_args+=(--force-app-files)
[ "$HAD_USER_CONFIG" = "false" ] && commit_args+=(--configure-default-paths)
run_installer_core "${commit_args[@]}" || exit 1

# Phase 5: optional components
if [ -n "$INSTALLATION_PLUGINS" ]; then
    IFS=',' read -ra parts <<< "$INSTALLATION_PLUGINS"
    for part in "${parts[@]}"; do
        part="${part//[[:space:]]/}"
        plugin_function="install_plugin_$part"
        record_manifest_component "plugin-$part" in_progress || exit 1
        "$plugin_function" || {
            log "Plugin installation failed for: $part"
            exit 1
        }
        case "$part" in
            bluetooth) plugin_version="$BLUEZ_VERSION" ;;
            shairport-sync) plugin_version="$SHAIRPORT_SYNC_VERSION" ;;
            spotifyd) plugin_version="$SPOTIFYD_VERSION" ;;
            plexamp) plugin_version="$PLEXAMP_VERSION" ;;
        esac
        record_manifest_component "plugin-$part" installed version "$plugin_version" || exit 1
    done
fi
if [ "$INSTALLATION_HYPERION" = "true" ]; then
    install_hyperion || exit 1
fi

# Phase 6: autostart
if [ "$INSTALLATION_AUTOSTART" = "true" ]; then
    configure_WaveCymatix_autostart
    record_manifest_component autostart installed state installed || exit 1
else
    runuser -u "$SUDO_USER" -- env XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user disable --now wave-cymatix.service >/dev/null 2>&1 || true
    rm -f "$TARGET_HOME/.config/autostart/WaveCymatix.desktop"
    rm -f "$TARGET_HOME/.config/systemd/user/wave-cymatix.service"
    record_manifest_component autostart removed || exit 1
fi

# Phase 7: finalize
# Force the Open GL version.
export MESA_GL_VERSION_OVERRIDE=3.3
if ! grep -q "MESA_GL_VERSION_OVERRIDE=3.3" "/etc/environment"; then
    echo -e "\nMESA_GL_VERSION_OVERRIDE=3.3" >> /etc/environment
fi
if ! is_desktop; then
    export PYOPENGL_PLATFORM=egl
    if ! grep -q "^PYOPENGL_PLATFORM=egl$" "/etc/environment"; then
        echo "PYOPENGL_PLATFORM=egl" >> /etc/environment
    fi
    mkdir -p /etc/systemd/system/getty@tty1.service.d
    cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $SUDO_USER --noclear %I \$TERM
EOF
fi

log "Optional plugin setup completed before application replacement."
record_manifest_operation succeeded || exit 1
MANIFEST_ACTIVE="false"
