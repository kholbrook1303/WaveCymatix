#!/usr/bin/env bash
set -euo pipefail

# WaveCymatix macOS installer.
#
# This script installs prerequisites via Homebrew or MacPorts, builds
# libprojectM from source, copies the WaveCymatix application files, downloads
# presets/textures/sprites, and configures settings.toml for macOS.

INSTALLATION_MODE=""
INSTALLATION_PROFILE=""
INSTALLATION_PROFILE_EXPLICIT="false"
PACKAGE_MANAGER="auto"
INSTALLATION_PLUGINS=""
INSTALLATION_AUTOSTART="preserve"
NO_AUTOSTART="false"
INSTALLATION_LOCAL="false"
INSTALLATION_SOURCE=""
INSTALLATION_PATH="$HOME/WaveCymatix"
OUTPUT_DIR_EXPLICIT="false"
INSTALLATION_USER=""
TARGET_USER=""
TARGET_HOME=""
INSTALLATION_LOGFILE="$HOME/WaveCymatix-installer.log"
REBUILD_PROJECTM="false"
REINSTALL_VENV="false"
REFRESH_PREREQS="false"
REFRESH_CONTENT="false"
PURGE="false"
RESET_CONFIG="false"
DRY_RUN="false"
YES="false"
VERBOSE="false"
WAVECYMATIX_REF=""
PROJECTM_REF=""
ASSETS_REF=""

TMP_BUILDS=""
LIBPROJECTM_VERSION=""

REQUIRED_PYTHON_VERSION=""
BREW_BIN=""
PORT_BIN=""
PYTHON_BIN=""
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
PROJECTM_RENDERER=""
PROJECTM_DEFAULT_REF=""
PROJECTM_CMAKE_FLAGS_MACOS=""
VCPKG_REPO=""
VCPKG_REF=""
DEJAVU_FONT_VERSION=""
DEJAVU_FONT_URL=""
DEJAVU_FONT_SHA256=""
LIBERATION_FONT_VERSION=""
LIBERATION_FONT_URL=""
VENV_PATH=""
VENV_PYTHON=""
STAGE_DIR=""
HAD_USER_CONFIG="false"
RESOLVED_SOURCE_REF=""
SOURCE_COMMIT=""
ASSETS_COMMIT=""
RESOLVED_ASSETS_REF=""
MANIFEST_ACTIVE="false"
TEMP_INSTALLER_CORE=""
REQUIRED_FONTS=("DejaVuSans.ttf" "DejaVuSansMono-Bold.ttf" "LiberationSans-Regular.ttf" "LiberationSans-Bold.ttf")

usage() {
    cat << EOF
Usage: ./bin/install-macos.sh [options]

Options:
    -m, --mode <mode>       Operation: install, update, or uninstall.
                            Defaults to update when installed, otherwise install.
    -P, --profile <name>    Performance profile: minimal or optimized
                            (default: optimized for a fresh config).

    -l, --local-install     Install application files from a local checkout.
                            Without --source, the checkout is resolved from
                            the repository root containing this script:
                            <repository>/bin/install-macos.sh -> <repository>.

    -s, --source <path>     Use the specified local repository as the source
                            for WaveCymatix application files. This option
                            automatically enables local-install behavior, so
                            --local-install is not required when --source is
                            supplied.

    -o, --output-dir <path> Installation and application-data directory.
                            Default: \$HOME/WaveCymatix

    --package-manager <name> Select brew, macports, or auto (default).
                             Auto prefers MacPorts on Intel macOS Tahoe when
                             MacPorts is installed; otherwise it uses the
                             available package manager.

    -p, --plugins <list>    Install one or more optional plugins. Supply a
                            comma-separated list with no spaces:
                            vlc    Installs the latest VLC via the selected
                                package manager and sets vlc = true in
                                settings.toml.

                            Other Linux-only plugins (bluetooth,
                            shairport-sync, spotifyd) are accepted for CLI
                            parity but ignored with a warning.

    -a, --autostart         Create and load a launchd user agent that starts
                            WaveCymatix automatically at login.
    --no-autostart          Remove the launchd agent. Omitted on update means
                            preserve its previous setting.

    --rebuild-projectm      Rebuild projectM even if its stamp is current.
    --reinstall-venv        Recreate the application virtual environment.
    --refresh-prereqs       Refresh package-manager metadata and dependencies.
    --refresh-content       Force visual-assets resync even when the commit matches.
    --reset-config          Back up the current config and use release defaults.
    --yes                   Accept MacPorts' non-interactive choices; OS prompts
                            (including Xcode tools) may still appear.
    --dry-run               Print the planned operation without changing files.
    --verbose               Show detailed, timestamped installer logs on the console.
    --ref <ref|latest>      Source ref (default: latest stable release, or
                            latest published prerelease if no stable release exists).
    --projectm-ref <ref>    Select a projectM tag, branch, or commit. When
                            omitted, updates retain the installed source ref.
    --assets-ref <ref>      Visual-assets ref (default: main).
    --user <name>           Target user for per-user autostart files.
    --purge                 Remove retained user data during uninstall.

    -h, --help              Display this usage information.

Examples (run from the repository root):
    First install with hardware tuning (normal default profile):
        ./bin/install-macos.sh --mode install --profile optimized

    First install with minimal performance settings:
        ./bin/install-macos.sh --mode install --profile minimal

    Update the installed application and preserve config (default behavior):
        ./bin/install-macos.sh --mode update

    Update and replace config with release defaults (backs up current config):
        ./bin/install-macos.sh --mode update --reset-config

    Enable autostart and install VLC during an install/update:
        ./bin/install-macos.sh --mode update --autostart --plugins vlc

    Use a local checkout for application files:
        ./bin/install-macos.sh --mode update --source /Users/me/src/WaveCymatix

    Select MacPorts instead of the automatically selected package manager:
        ./bin/install-macos.sh --mode install --profile optimized --package-manager macports

    Choose a release and a non-default installation directory:
        ./bin/install-macos.sh --mode update --ref latest --output-dir /Applications/WaveCymatix

    Force content and package metadata refresh; show detailed logs:
        ./bin/install-macos.sh --mode update --refresh-content --refresh-prereqs --verbose

    Preview an install without changing files:
        ./bin/install-macos.sh --mode install --profile optimized --dry-run

    Use non-interactive MacPorts choices where supported:
        ./bin/install-macos.sh --mode update --package-manager macports --yes

    Uninstall the application but keep config, data, content, and runtime:
        ./bin/install-macos.sh --mode uninstall

    Uninstall and remove the entire installation directory and retained data:
        ./bin/install-macos.sh --mode uninstall --purge

    Install for a named user (for that user's launch agent):
        ./bin/install-macos.sh --mode install --user <macos-user>

    Use a specific WaveCymatix branch/tag/commit instead of the latest release:
        ./bin/install-macos.sh --mode update --ref <tag-branch-or-commit>

    Rebuild projectM from a specific ref:
        ./bin/install-macos.sh --mode update --projectm-ref <tag>

    Show all options:
        ./bin/install-macos.sh --help
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
        key="${key%%#*}"
        key="$(printf '%s' "$key" | tr -d '[:space:]')"
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
            PROJECTM_RENDERER) PROJECTM_RENDERER="$value" ;;
            PROJECTM_DEFAULT_REF) PROJECTM_DEFAULT_REF="$value" ;;
            PROJECTM_CMAKE_FLAGS_MACOS) PROJECTM_CMAKE_FLAGS_MACOS="$value" ;;
            PYTHON_VERSION) REQUIRED_PYTHON_VERSION="$value" ;;
            MIN_CMAKE_VERSION|NODE_VERSION|PLEXAMP_VERSION) ;;
            DEJAVU_FONT_VERSION) DEJAVU_FONT_VERSION="$value" ;;
            DEJAVU_FONT_URL) DEJAVU_FONT_URL="$value" ;;
            DEJAVU_FONT_SHA256) DEJAVU_FONT_SHA256="$value" ;;
            LIBERATION_FONT_VERSION) LIBERATION_FONT_VERSION="$value" ;;
            LIBERATION_FONT_URL) LIBERATION_FONT_URL="$value" ;;
            VCPKG_REPO) VCPKG_REPO="$value" ;;
            VCPKG_REF) VCPKG_REF="$value" ;;
            INSTALLER_API) INSTALLER_API="$value" ;;
            PROJECTM_CMAKE_FLAGS_WINDOWS|PROJECTM_CMAKE_FLAGS_LINUX|WIN_VS_GENERATOR|WIN_CMAKE_ARCH|WIN_GIT_PACKAGE_ID|WIN_CMAKE_PACKAGE_ID|WIN_PYTHON_PACKAGE_PREFIX|WIN_FFMPEG_PACKAGE_ID|WIN_VLC_PACKAGE_ID|CMAKE_VERSION|BLUEZ_VERSION|SHAIRPORT_SYNC_VERSION|NQPTP_VERSION|SPOTIFYD_VERSION) ;;
            *) echo "Unknown installer.env key: $key" >&2; return 1 ;;
        esac
        case "$key" in
            APP_REPO|APP_DEFAULT_REF|ASSETS_REPO|ASSETS_DEFAULT_REF|PROJECTM_REPO|PROJECTM_VERSION|PROJECTM_RENDERER|PROJECTM_DEFAULT_REF|PROJECTM_CMAKE_FLAGS_MACOS|PYTHON_VERSION|MIN_CMAKE_VERSION|NODE_VERSION|PLEXAMP_VERSION|DEJAVU_FONT_VERSION|DEJAVU_FONT_URL|DEJAVU_FONT_SHA256|LIBERATION_FONT_VERSION|LIBERATION_FONT_URL|VCPKG_REPO|VCPKG_REF|INSTALLER_API|PROJECTM_CMAKE_FLAGS_WINDOWS|PROJECTM_CMAKE_FLAGS_LINUX|WIN_VS_GENERATOR|WIN_CMAKE_ARCH|WIN_GIT_PACKAGE_ID|WIN_CMAKE_PACKAGE_ID|WIN_PYTHON_PACKAGE_PREFIX|WIN_FFMPEG_PACKAGE_ID|WIN_VLC_PACKAGE_ID|CMAKE_VERSION|BLUEZ_VERSION|SHAIRPORT_SYNC_VERSION|NQPTP_VERSION|SPOTIFYD_VERSION) ;;
            *) echo "Unsupported installer.env key: $key" >&2; return 1 ;;
        esac
    done < "$path"

    [ -n "$INSTALLER_API" ] && [ -n "$APP_REPO" ] && [ -n "$APP_DEFAULT_REF" ] &&
        [ -n "$ASSETS_REPO" ] && [ -n "$ASSETS_DEFAULT_REF" ] &&
        [ -n "$PROJECTM_REPO" ] && [ -n "$LIBPROJECTM_VERSION" ] &&
        [ -n "$PROJECTM_RENDERER" ] && [ -n "$PROJECTM_CMAKE_FLAGS_MACOS" ] &&
        [ -n "$REQUIRED_PYTHON_VERSION" ] &&
        [ -n "$DEJAVU_FONT_VERSION" ] && [ -n "$DEJAVU_FONT_URL" ] &&
        [ -n "$DEJAVU_FONT_SHA256" ] && [ -n "$LIBERATION_FONT_VERSION" ] &&
        [ -n "$LIBERATION_FONT_URL" ] || {
            echo "installer.env is missing required values." >&2
            return 1
        }
    [[ "$INSTALLER_API" =~ ^[0-9]+$ ]] || { echo "INSTALLER_API must be an integer." >&2; return 1; }
    [[ "$LIBPROJECTM_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "PROJECTM_VERSION must be a numeric version." >&2; return 1; }
    [[ "$REQUIRED_PYTHON_VERSION" =~ ^[0-9]+\.[0-9]+$ ]] || { echo "PYTHON_VERSION must be a major.minor version." >&2; return 1; }
    [[ "$DEJAVU_FONT_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "DEJAVU_FONT_VERSION must be a numeric version." >&2; return 1; }
    [[ "$LIBERATION_FONT_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "LIBERATION_FONT_VERSION must be a numeric version." >&2; return 1; }
}

run_installer_core() {
    "$PYTHON_BIN" "$INSTALLER_CORE" "$@"
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
        details=$(printf '%s\n' "$@" | "$PYTHON_BIN" -c \
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
    encoded_settings=$(printf '%s' "$build_settings" | "$PYTHON_BIN" -c \
        'import base64,sys; print(base64.b64encode(sys.stdin.buffer.read()).decode("ascii"))') || return 1
    local args=(projectm-component --output "$INSTALLATION_PATH" --action "$action"
        --version "$LIBPROJECTM_VERSION" --renderer "$PROJECTM_RENDERER"
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
}

begin_uninstall_manifest() {
    [ "$PURGE" != "true" ] || return 0
    [ -f "$INSTALLATION_PATH/.install-state.json" ] || return 0
    [ -f "$INSTALLER_CORE" ] || {
        echo "Cannot update uninstall manifest: installer helper is missing." >&2
        return 1
    }
    PYTHON_BIN="${INSTALLATION_PATH}/.venv/bin/python"
    [ -x "$PYTHON_BIN" ] || PYTHON_BIN="${INSTALLATION_PATH}/venv/bin/python"
    [ -x "$PYTHON_BIN" ] || PYTHON_BIN="${INSTALLATION_PATH}/env/bin/python"
    [ -x "$PYTHON_BIN" ] || PYTHON_BIN="$(command -v python3 || true)"
    [ -n "$PYTHON_BIN" ] || {
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

require_macos() {
    if [ "$(uname -s)" != "Darwin" ]; then
        echo "This installer must be run on macOS." >&2
        exit 1
    fi
}

find_package_managers() {
    BREW_BIN="$(command -v brew || true)"
    if [ -z "$BREW_BIN" ]; then
        for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
            if [ -x "$candidate" ]; then
                BREW_BIN="$candidate"
                break
            fi
        done
    fi

    PORT_BIN="$(command -v port || true)"
    if [ -z "$PORT_BIN" ] && [ -x /opt/local/bin/port ]; then
        PORT_BIN=/opt/local/bin/port
    fi
}

select_package_manager() {
    find_package_managers

    if [ "$PACKAGE_MANAGER" = "auto" ]; then
        local arch os_major
        arch=$(uname -m)
        os_major=$(sw_vers -productVersion | cut -d. -f1)

        if [ "$arch" = "x86_64" ] && [ "$os_major" -ge 26 ] && [ -n "$PORT_BIN" ]; then
            PACKAGE_MANAGER="macports"
        elif [ -n "$BREW_BIN" ]; then
            PACKAGE_MANAGER="brew"
        elif [ -n "$PORT_BIN" ]; then
            PACKAGE_MANAGER="macports"
        else
            echo "Neither Homebrew nor MacPorts was found." >&2
            echo "Install Homebrew from https://brew.sh or MacPorts from https://www.macports.org/install.php." >&2
            return 1
        fi
    fi

    case "$PACKAGE_MANAGER" in
        brew)
            if [ -z "$BREW_BIN" ]; then
                echo "Homebrew was selected but was not found. Install it from https://brew.sh." >&2
                return 1
            fi
            local brew_prefix
            brew_prefix=$("$BREW_BIN" --prefix)
            PATH="$brew_prefix/bin:$brew_prefix/sbin:$PATH"
            export PATH
            ;;
        macports)
            if [ -z "$PORT_BIN" ]; then
                echo "MacPorts was selected but was not found. Install it from https://www.macports.org/install.php." >&2
                return 1
            fi
            PATH="/opt/local/bin:/opt/local/sbin:$PATH"
            export PATH
            ;;
        *)
            echo "Unsupported package manager: $PACKAGE_MANAGER (choose auto, brew, or macports)." >&2
            return 1
            ;;
    esac

    log "Using package manager: $PACKAGE_MANAGER"
}

macports_run() {
    local noninteractive=()
    if [ "$YES" = "true" ]; then noninteractive+=(-y); fi
    if [ "$(id -u)" -eq 0 ]; then
        "$PORT_BIN" "${noninteractive[@]}" "$@"
    else
        sudo "$PORT_BIN" "${noninteractive[@]}" "$@"
    fi
}

require_xcode_clt() {
    if ! xcode-select -p >/dev/null 2>&1; then
        log "Xcode Command Line Tools are not installed"
        echo "Installing Xcode Command Line Tools (a GUI prompt may appear)..."
        xcode-select --install || true
        echo "Re-run this script once the Xcode Command Line Tools installation completes."
        exit 1
    fi
}

install_fonts() {
    local fonts_dir="$HOME/Library/Fonts"
    local work_dir="$TMP_BUILDS/fonts"
    local deja_vu_archive="$work_dir/dejavu-fonts-ttf-$DEJAVU_FONT_VERSION.zip"
    local liberation_archive="$work_dir/liberation-fonts-ttf-$LIBERATION_FONT_VERSION.tar.gz"
    local deja_vu_dir="$work_dir/dejavu"
    local liberation_dir="$work_dir/liberation"
    local font_name source_file
    local missing_fonts="false"

    for font_name in "${REQUIRED_FONTS[@]}"; do
        if [ ! -f "$fonts_dir/$font_name" ]; then
            missing_fonts="true"
            break
        fi
    done

    if [ "$missing_fonts" = "false" ]; then
        log "All required fonts are already installed"
        return 0
    fi

    log "Installing required DejaVu and Liberation fonts for the current user"
    mkdir -p "$fonts_dir" "$deja_vu_dir" "$liberation_dir"

    curl -fL "$DEJAVU_FONT_URL" -o "$deja_vu_archive"
    local actual_dejavu_sha256
    actual_dejavu_sha256=$(shasum -a 256 "$deja_vu_archive" | awk '{print toupper($1)}')
    if [ "$actual_dejavu_sha256" != "$DEJAVU_FONT_SHA256" ]; then
        log "DejaVu font archive checksum verification failed"
        return 1
    fi
    unzip -q -o "$deja_vu_archive" -d "$deja_vu_dir"

    curl -fL "$LIBERATION_FONT_URL" -o "$liberation_archive"
    tar -xzf "$liberation_archive" -C "$liberation_dir"

    for font_name in "${REQUIRED_FONTS[@]}"; do
        if [ -f "$fonts_dir/$font_name" ]; then
            continue
        fi

        source_file=$(find "$deja_vu_dir" "$liberation_dir" -type f -name "$font_name" -print -quit)
        if [ -z "$source_file" ]; then
            log "Required font was not found in downloaded archives: $font_name"
            return 1
        fi

        cp "$source_file" "$fonts_dir/$font_name"
    done

    rm -rf "$work_dir"
    log "Installed required fonts in $fonts_dir"
}

ensure_prerequisites() {
    if [ "$PACKAGE_MANAGER" = "brew" ]; then
        log "Installing/updating Homebrew prerequisites"
        if [ "$REFRESH_PREREQS" = "true" ]; then "$BREW_BIN" update; fi
        "$BREW_BIN" install git cmake ffmpeg glm pkgconf "python@$REQUIRED_PYTHON_VERSION"
        PYTHON_BIN="$("$BREW_BIN" --prefix "python@$REQUIRED_PYTHON_VERSION")/bin/python$REQUIRED_PYTHON_VERSION"
    else
        log "Installing/updating MacPorts prerequisites"
        if [ "$REFRESH_PREREQS" = "true" ]; then macports_run selfupdate; fi
        macports_run install git cmake ffmpeg python312 py312-pip glm pkgconfig llvm-22 py312-llvmlite
        PYTHON_BIN="/opt/local/bin/python$REQUIRED_PYTHON_VERSION"
    fi

    if [ ! -x "$PYTHON_BIN" ]; then
        echo "Python $REQUIRED_PYTHON_VERSION was not found at $PYTHON_BIN." >&2
        return 1
    fi
}

detect_performance_tier() {
    local arch
    arch=$(uname -m)

    if [ "$arch" = "arm64" ]; then
        # Apple Silicon integrated GPUs are consistently capable.
        PERFORMANCE_TIER="high"
        log "Apple Silicon detected, using performance tier: $PERFORMANCE_TIER"
        return 0
    fi

    local vram_mb
    vram_mb=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -Eo 'VRAM \(.*\): [0-9]+' | grep -Eo '[0-9]+' | sort -rn | head -n1 || true)

    if [ -n "$vram_mb" ] && [ "$vram_mb" -ge 4096 ]; then
        PERFORMANCE_TIER="high"
    elif [ -n "$vram_mb" ] && [ "$vram_mb" -ge 2048 ]; then
        PERFORMANCE_TIER="medium"
    else
        PERFORMANCE_TIER="low"
    fi

    log "Intel Mac detected, using performance tier: $PERFORMANCE_TIER"
}

install_libprojectm() {
    local stamp_version stamp_renderer stamp_ref stamp_commit library_path playlist_path source_dir build_dir checkout projectm_commit expected_ref
    local source_type build_settings toolchain stamp_toolchain cmake_prefix cmake_version compiler_version check_result
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
        source_dir=$(printf '%s' "$checkout" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["path"])')
        projectm_commit=$(printf '%s' "$checkout" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["commit"])')
    fi
    library_path=""
    for candidate in /usr/local/lib/libprojectM-4.dylib /opt/homebrew/lib/libprojectM-4.dylib /opt/local/lib/libprojectM-4.dylib; do
        if [ -f "$candidate" ]; then library_path="$candidate"; break; fi
    done
    if [ -z "$PROJECTM_REF" ] && [ "$REBUILD_PROJECTM" != "true" ] &&
        [ -n "$library_path" ] &&
        [ "$stamp_version" = "\"$LIBPROJECTM_VERSION\"" ] &&
        [ "$stamp_renderer" = "\"$PROJECTM_RENDERER\"" ] &&
        [ "$stamp_ref" != "null" ]; then
        expected_ref=$(printf '%s' "$stamp_ref" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin))') || return 1
        projectm_commit=$(printf '%s' "$stamp_commit" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin))') || return 1
    fi
    source_type="release-tarball"
    [ -n "$projectm_commit" ] && source_type="git"
    playlist_path="${library_path%/*}/libprojectM-4-playlist.dylib"
    cmake_version=$(cmake --version 2>/dev/null | head -n1)
    compiler_version=$(c++ --version 2>/dev/null | head -n1)
    toolchain="$cmake_version; $compiler_version; $(uname -m)"
    if [ -z "$PROJECTM_REF" ] && [ "$REBUILD_PROJECTM" != "true" ] &&
        [ "$stamp_toolchain" != "null" ]; then
        toolchain=$(printf '%s' "$stamp_toolchain" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin))') || return 1
    fi
    cmake_prefix=""
    [ "$PACKAGE_MANAGER" = "macports" ] && cmake_prefix="/opt/local"
    build_settings=$(printf '%s' "$PROJECTM_CMAKE_FLAGS_MACOS" | "$PYTHON_BIN" -c \
        'import json,shlex,sys; print(json.dumps({"cmake_flags": shlex.split(sys.stdin.read()), "build_type":"Release", "install_prefix":"/usr/local", "package_manager":sys.argv[1], "cmake_prefix_path":sys.argv[2]}, sort_keys=True))' \
        "$PACKAGE_MANAGER" "$cmake_prefix") || return 1
    local artifacts=("libprojectM-4.dylib=$library_path" "libprojectM-4-playlist.dylib=$playlist_path")

    if [ "$REBUILD_PROJECTM" != "true" ] && [ -n "$library_path" ] && [ -f "$playlist_path" ]; then
        check_result=$(projectm_component check "$source_type" "$expected_ref" "$projectm_commit" \
            "$toolchain" "$build_settings" true "${artifacts[@]}") || return 1
    else
        check_result='{"matches": false}'
    fi
    if [ "$REBUILD_PROJECTM" != "true" ] &&
        [ "$(printf '%s' "$check_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["matches"])')" = "True" ]; then
        log "Reusing stamped libprojectM $LIBPROJECTM_VERSION"
        projectm_component stamp "$source_type" "$expected_ref" "$projectm_commit" \
            "$toolchain" "$build_settings" false "${artifacts[@]}" >/dev/null || return 1
        return 0
    fi

    log "Building libprojectM $LIBPROJECTM_VERSION from source"

    mkdir -p "$TMP_BUILDS"
    if [ -n "$PROJECTM_REF" ]; then
        PROJECTM_COMMIT="$projectm_commit"
        git -C "$source_dir" submodule update --init --recursive
    else
        local archive="$TMP_BUILDS/libprojectM-$LIBPROJECTM_VERSION.tar.gz"
        source_dir="$TMP_BUILDS/libprojectM-$LIBPROJECTM_VERSION"
        if [ ! -f "$archive" ]; then
            curl -fL "${PROJECTM_REPO%.git}/releases/download/v$LIBPROJECTM_VERSION/libprojectM-$LIBPROJECTM_VERSION.tar.gz" -o "$archive"
        fi
        if [ ! -d "$source_dir" ]; then
            tar xf "$archive" -C "$TMP_BUILDS"
        fi
        PROJECTM_COMMIT=""
    fi
    build_dir="$TMP_BUILDS/projectm-build"
    if [ "$REBUILD_PROJECTM" = "true" ] || [ "$stamp_ref" != "\"$expected_ref\"" ] ||
        [ "$stamp_commit" != "\"$projectm_commit\"" ]; then
        rm -rf "$build_dir"
    fi

    read -r -a projectm_flags <<< "$PROJECTM_CMAKE_FLAGS_MACOS"
    local -a cmake_prefix_args=()
    [ -n "$cmake_prefix" ] && cmake_prefix_args+=("-DCMAKE_PREFIX_PATH=$cmake_prefix")
    cmake "${projectm_flags[@]}" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local "${cmake_prefix_args[@]}" -S "$source_dir" -B "$build_dir"
    cmake --build "$build_dir" --parallel "$(sysctl -n hw.ncpu)"
    record_manifest_component projectm in_progress || return 1
    local install_root staged_libdir artifact
    local -a install_args=(install-files)
    install_root=$(mktemp -d "$TMP_BUILDS/projectm-install.XXXXXX") || return 1
    cmake --install "$build_dir" --prefix "$install_root" || {
        rm -rf "$install_root"
        return 1
    }
    staged_libdir="$install_root/lib"
    for artifact in "$staged_libdir"/libprojectM-4*.dylib; do
        if [ -e "$artifact" ] || [ -L "$artifact" ]; then
            install_args+=(--file "$artifact=/usr/local/lib/$(basename "$artifact")")
        fi
    done
    if [ "${#install_args[@]}" -eq 1 ]; then
        rm -rf "$install_root"
        echo "projectM install did not stage runtime libraries" >&2
        return 1
    fi
    sudo "$PYTHON_BIN" "$INSTALLER_CORE" "${install_args[@]}" || {
        rm -rf "$install_root"
        return 1
    }
    rm -rf "$install_root"
    library_path=""
    for candidate in /usr/local/lib/libprojectM-4.dylib /opt/homebrew/lib/libprojectM-4.dylib /opt/local/lib/libprojectM-4.dylib; do
        if [ -f "$candidate" ]; then library_path="$candidate"; break; fi
    done
    playlist_path="${library_path%/*}/libprojectM-4-playlist.dylib"
    artifacts=("libprojectM-4.dylib=$library_path" "libprojectM-4-playlist.dylib=$playlist_path")
    projectm_component stamp "$source_type" "$expected_ref" "${PROJECTM_COMMIT:-}" \
        "$toolchain" "$build_settings" false "${artifacts[@]}" >/dev/null
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
    SOURCE_REPO=$(printf '%s' "$resolved_source" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["path"])')
    SOURCE_COMMIT=$(printf '%s' "$resolved_source" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["commit"])')
    RESOLVED_SOURCE_REF=$(printf '%s' "$resolved_source" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["ref"])')
    if [ "$INSTALLATION_LOCAL" != "true" ] &&
        [ "$requested_ref" != "latest" ] &&
        [[ ! "$requested_ref" =~ ^v[0-9] ]]; then
        log "WARNING: non-release WaveCymatix ref selected: $requested_ref"
    fi
    read_installer_env "$SOURCE_REPO/bin/installer.env" || return 1
    if [ -z "$PROJECTM_REF" ] && [ -n "$PROJECTM_DEFAULT_REF" ]; then
        PROJECTM_REF="$PROJECTM_DEFAULT_REF"
    fi
}

install_wavecymatix() {
    log "Installing WaveCymatix to $INSTALLATION_PATH"
    local asset_ref prepare_result
    local -a prepare_args
    asset_ref="${ASSETS_REF:-$ASSETS_DEFAULT_REF}"
    prepare_args=(prepare-application --source "$SOURCE_REPO" \
        --output "$INSTALLATION_PATH" --python "$PYTHON_BIN" \
        --required-python "$REQUIRED_PYTHON_VERSION" \
        --supported-api "$SUPPORTED_INSTALLER_API" \
        --assets-repo "$ASSETS_REPO" --assets-ref "$asset_ref")
    [ "$REINSTALL_VENV" = "true" ] && prepare_args+=(--reinstall-venv)
    [ "$REFRESH_CONTENT" = "true" ] && prepare_args+=(--refresh-content)
    [ "$RESET_CONFIG" = "true" ] && prepare_args+=(--reset-config)
    prepare_result=$(run_installer_core "${prepare_args[@]}") || return 1
    STAGE_DIR=$(printf '%s' "$prepare_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["stage_dir"])') || return 1
    VENV_PATH=$(printf '%s' "$prepare_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["venv_path"])') || return 1
    VENV_PYTHON=$(printf '%s' "$prepare_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["venv_python"])') || return 1
    ASSETS_COMMIT=$(printf '%s' "$prepare_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["assets_commit"])') || return 1
    RESOLVED_ASSETS_REF=$(printf '%s' "$prepare_result" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["assets_ref"])') || return 1
    HAD_USER_CONFIG=$(printf '%s' "$prepare_result" | "$PYTHON_BIN" -c 'import json,sys; print(str(json.load(sys.stdin)["had_user_config"]).lower())') || return 1
}

configure_wavecymatix() {
    log "Configuring settings.toml for macOS"

    local settings_args=(configure-settings --config "$STAGE_DIR/conf/settings.toml")
    settings_args+=(--set projectm.window.fullscreen=true)
    settings_args+=(--set monitors.audio=false --set monitors.display=false)
    settings_args+=(--set plugins.airplay=false --set plugins.bluetooth=false)
    settings_args+=(--set plugins.spotify=false --set plugins.windows_media=false)
    if [ "$INSTALL_VLC_PLUGIN" = "true" ]; then
        settings_args+=(--set plugins.vlc=true)
    else
        settings_args+=(--set plugins.vlc=false)
    fi

    if [ "$INSTALLATION_PROFILE" = "optimized" ]; then
        detect_performance_tier
        case "$PERFORMANCE_TIER" in
            low)
                settings_args+=(--set projectm.projectM.fps=30)
                settings_args+=(--set projectm.projectM.meshX=48)
                settings_args+=(--set projectm.projectM.meshY=32)
                ;;
            medium)
                settings_args+=(--set projectm.projectM.fps=60)
                settings_args+=(--set projectm.projectM.meshX=64)
                settings_args+=(--set projectm.projectM.meshY=32)
                ;;
            high)
                settings_args+=(--set projectm.projectM.fps=60)
                settings_args+=(--set projectm.projectM.meshX=96)
                settings_args+=(--set projectm.projectM.meshY=54)
                ;;
        esac
    fi

    run_installer_core "${settings_args[@]}"
}

install_vlc_plugin() {
    if [ "$PACKAGE_MANAGER" = "brew" ]; then
        log "Installing/updating VLC via Homebrew"
        if "$BREW_BIN" list --cask vlc >/dev/null 2>&1; then
            "$BREW_BIN" upgrade --cask vlc || true
        else
            "$BREW_BIN" install --cask vlc
        fi
    else
        log "Installing/updating VLC via MacPorts"
        if "$PORT_BIN" installed vlc 2>/dev/null | grep -q '(active)'; then
            macports_run upgrade vlc
        else
            macports_run install vlc
        fi
    fi
}

configure_vlc_runtime() {
    local vlc_app_root=""
    local vlc_library_dir=""
    local vlc_plugin_dir=""
    local candidate

    for candidate in \
        "/Applications/MacPorts/VLC.app/Contents/MacOS" \
        "/Applications/VLC.app/Contents/MacOS" \
        "/opt/local/libexec/vlc3"; do
        if [ -f "$candidate/lib/libvlc.dylib" ]; then
            vlc_app_root="$candidate"
            vlc_library_dir="$candidate/lib"
            break
        elif [ -f "$candidate/libvlc.dylib" ]; then
            vlc_app_root="$candidate"
            vlc_library_dir="$candidate"
            break
        fi
    done

    if [ -n "$vlc_app_root" ]; then
        if [ -d "$vlc_app_root/plugins" ]; then
            vlc_plugin_dir="$vlc_app_root/plugins"
        elif [ -d "$(dirname "$vlc_app_root")/plugins" ]; then
            vlc_plugin_dir="$(dirname "$vlc_app_root")/plugins"
        fi
        log "Configuring VLC runtime library path: $vlc_library_dir"
    elif [ "$INSTALL_VLC_PLUGIN" = "true" ]; then
        echo "VLC was requested but libvlc.dylib was not found after installation." >&2
        echo "Check the VLC installation, then rerun with --plugins vlc." >&2
        return 1
    fi

    cat > "$INSTALLATION_PATH/run-wavecymatix.sh" << EOF
#!/usr/bin/env bash
set -e
EOF

    if [ -n "$vlc_library_dir" ]; then
        cat >> "$INSTALLATION_PATH/run-wavecymatix.sh" << EOF
export PYTHON_VLC_LIB_PATH="$vlc_library_dir/libvlc.dylib"
export DYLD_LIBRARY_PATH="$vlc_library_dir\${DYLD_LIBRARY_PATH:+:\$DYLD_LIBRARY_PATH}"
EOF
    fi

    if [ -n "$vlc_plugin_dir" ]; then
        printf 'export PYTHON_VLC_MODULE_PATH=%q\n' "$vlc_plugin_dir" >> "$INSTALLATION_PATH/run-wavecymatix.sh"
        printf 'export VLC_PLUGIN_PATH=%q\n' "$vlc_plugin_dir" >> "$INSTALLATION_PATH/run-wavecymatix.sh"
    fi

    cat >> "$INSTALLATION_PATH/run-wavecymatix.sh" << EOF
exec "$INSTALLATION_PATH/.venv/bin/wavecymatix" "\$@"
EOF
    chmod +x "$INSTALLATION_PATH/run-wavecymatix.sh"
}

configure_autostart() {
    log "Configuring launchd autostart agent"

    local agents_dir="$TARGET_HOME/Library/LaunchAgents"
    local plist_path="$agents_dir/com.wavecymatix.app.plist"
    mkdir -p "$agents_dir"

    cat > "$plist_path" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wavecymatix.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$INSTALLATION_PATH/run-wavecymatix.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

    launchctl bootout "gui/$(id -u "$TARGET_USER")" "$plist_path" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u "$TARGET_USER")" "$plist_path"
}

cleanup_previous_installation() {
    local uninstall="${1:-false}"

    if [ "$uninstall" = "true" ]; then
        local plist_path="$TARGET_HOME/Library/LaunchAgents/com.wavecymatix.app.plist"
        launchctl bootout "gui/$(id -u "$TARGET_USER")" "$plist_path" >/dev/null 2>&1 || true
        rm -f "$plist_path"
        stop_wavecymatix
        if [ "$PURGE" = "true" ]; then
            rm -rf "$INSTALLATION_PATH"
        else
            for item in assets bin core docs lib resources WaveCymatix.py requirements.txt VERSION run-wavecymatix.sh .new .prev .content-new .content-prev .app-prev; do
                rm -rf "$INSTALLATION_PATH/$item"
            done
            log "Retained config, data, content, runtime and build cache. Use --purge to remove them."
        fi
        return 0
    fi
}

stop_wavecymatix() {
    local pattern="$INSTALLATION_PATH/([.]venv|venv|env)/bin/python"
    local pids
    pids=$(pgrep -f "$pattern" || true)
    if [ -n "$pids" ]; then
        log "Stopping WaveCymatix processes using the installation virtual environment"
        while IFS= read -r pid; do
            [ -n "$pid" ] && kill -TERM "$pid"
        done <<< "$pids"
        sleep 2
        while IFS= read -r pid; do
            [ -n "$pid" ] && kill -KILL "$pid" 2>/dev/null || true
        done <<< "$(pgrep -f "$pattern" || true)"
    fi
}

# Argument parsing
while [ $# -gt 0 ]; do
    case "$1" in
        -m|--mode)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_MODE="$2"
            shift 2
            ;;
        -P|--profile)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_PROFILE="$2"
            INSTALLATION_PROFILE_EXPLICIT="true"
            shift 2
            ;;
        -l|--local-install)
            INSTALLATION_LOCAL="true"
            shift
            ;;
        -s|--source)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_LOCAL="true"
            INSTALLATION_SOURCE="$2"
            shift 2
            ;;
        -o|--output-dir)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_PATH="$2"
            OUTPUT_DIR_EXPLICIT="true"
            shift 2
            ;;
        --package-manager)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            PACKAGE_MANAGER="$2"
            shift 2
            ;;
        -p|--plugins)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            INSTALLATION_PLUGINS="$2"
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
        --ref)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            WAVECYMATIX_REF="$2"
            shift 2
            ;;
        --projectm-ref)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            PROJECTM_REF="$2"
            shift 2
            ;;
        --assets-ref)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
            ASSETS_REF="$2"
            shift 2
            ;;
        --user)
            [ $# -ge 2 ] || { echo "$1 requires a value." >&2; exit 1; }
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
            echo "Hyperion is Linux-only and is not supported on macOS." >&2
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

require_macos
read_installer_env "$INSTALLER_ENV"
SUPPORTED_INSTALLER_API="$INSTALLER_API"

if [ "$INSTALLATION_AUTOSTART" = "true" ] && [ "$NO_AUTOSTART" = "true" ]; then
    echo "Use only one of --autostart or --no-autostart." >&2
    exit 1
fi

TARGET_USER="${INSTALLATION_USER:-${SUDO_USER:-$(id -un)}}"
if [ "$TARGET_USER" = "$(id -un)" ]; then
    TARGET_HOME="$HOME"
else
    TARGET_HOME=$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
    [ -n "$TARGET_HOME" ] && [ -d "$TARGET_HOME" ] || {
        echo "Unable to resolve a home directory for target user '$TARGET_USER'." >&2
        exit 1
    }
fi
if [ "$OUTPUT_DIR_EXPLICIT" != "true" ]; then
    INSTALLATION_PATH="$TARGET_HOME/WaveCymatix"
fi
TMP_BUILDS="$INSTALLATION_PATH/runtime/build-cache"
INSTALLATION_LOGFILE="$TARGET_HOME/WaveCymatix-installer.log"

case "$INSTALLATION_MODE" in
    install|update|uninstall) ;;
    "")
        if [ -e "$INSTALLATION_PATH/.install-state.json" ] || [ -f "$INSTALLATION_PATH/.venv/bin/wavecymatix" ]; then
            INSTALLATION_MODE="update"
        else
            INSTALLATION_MODE="install"
        fi
        ;;
    *)
        echo "Unsupported installation mode: $INSTALLATION_MODE" >&2
        usage
        exit 1
        ;;
esac
if [ "$INSTALLATION_MODE" != "uninstall" ] && [ -z "$INSTALLATION_PROFILE" ]; then
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
if [ "$PURGE" = "true" ] && [ "$INSTALLATION_MODE" != "uninstall" ]; then
    echo "--purge is only valid with --mode uninstall." >&2
    exit 1
fi
if [ "$INSTALLATION_MODE" = "uninstall" ] && { [ -n "$INSTALLATION_PLUGINS" ] || [ -n "$WAVECYMATIX_REF" ] || [ -n "$PROJECTM_REF" ] || [ -n "$ASSETS_REF" ] || [ "$INSTALLATION_AUTOSTART" = "true" ] || [ "$NO_AUTOSTART" = "true" ] || [ "$RESET_CONFIG" = "true" ] || [ "$REINSTALL_VENV" = "true" ] || [ "$REFRESH_PREREQS" = "true" ] || [ "$REFRESH_CONTENT" = "true" ] || [ "$YES" = "true" ] || [ -n "$INSTALLATION_SOURCE" ] || [ "$INSTALLATION_LOCAL" = "true" ] || [ "$REBUILD_PROJECTM" = "true" ] || [ -n "$INSTALLATION_PROFILE" ]; }; then
    echo "Install/update options cannot be combined with --mode uninstall." >&2
    exit 1
fi
if [ "$DRY_RUN" = "true" ]; then
    requested_ref="${WAVECYMATIX_REF:-$APP_DEFAULT_REF}"
    refresh_note=""
    [ "$REFRESH_CONTENT" = "true" ] && refresh_note="; force visual-assets resync"
    echo "Dry run: would run '$INSTALLATION_MODE' from ref '$requested_ref' in '$INSTALLATION_PATH'$refresh_note."
    exit 0
fi

# Phase 1: preflight
if [ "$INSTALLATION_MODE" = "uninstall" ]; then
    begin_uninstall_manifest
    log "Running uninstallation..."
    cleanup_previous_installation true
    finish_uninstall_manifest
    log "WaveCymatix has been removed from $INSTALLATION_PATH"
    exit 0
fi

# Phase 2: prerequisites
select_package_manager

INSTALL_VLC_PLUGIN="false"
if [ -n "$INSTALLATION_PLUGINS" ]; then
    IFS=',' read -ra parts <<< "$INSTALLATION_PLUGINS"
    for part in "${parts[@]}"; do
        part="${part//[[:space:]]/}"
        case "$part" in
            vlc)
                INSTALL_VLC_PLUGIN="true"
                ;;
            *)
                log "Plugin '$part' is not supported on macOS, ignoring"
                ;;
        esac
    done
fi

progress "Checking macOS prerequisites"
require_xcode_clt
ensure_prerequisites
install_fonts
PYTHON_BIN=$(command -v "python$REQUIRED_PYTHON_VERSION" || command -v python3)
[ -n "$PYTHON_BIN" ] || { echo "Python $REQUIRED_PYTHON_VERSION is unavailable." >&2; exit 1; }
if [ ! -f "$INSTALLER_CORE" ]; then
    echo "Shared installer helper is missing: $INSTALLER_CORE" >&2
    exit 1
fi
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
record_manifest_operation begin
MANIFEST_ACTIVE="true"
trap 'manifest_exit_handler "$?" "$BASH_COMMAND"' EXIT

# Phase 3: projectM
progress "Resolving WaveCymatix source"
resolve_source_repository

stop_wavecymatix
progress "Preparing projectM runtime"
install_libprojectm

# Phase 4: WaveCymatix
progress "Staging application and visual assets"
install_wavecymatix

if [ "$HAD_USER_CONFIG" = "false" ]; then
    if [ "$INSTALLATION_PROFILE" = "optimized" ]; then
        configure_wavecymatix
    fi
fi

progress "Validating and applying staged application files"
stop_wavecymatix
commit_args=(commit-application --stage "$STAGE_DIR" \
    --output "$INSTALLATION_PATH" --python "$VENV_PYTHON" \
    --source-ref "$RESOLVED_SOURCE_REF" --source-commit "$SOURCE_COMMIT" \
    --assets-ref "$RESOLVED_ASSETS_REF" --assets-commit "$ASSETS_COMMIT")
[ "$INSTALLATION_LOCAL" = "true" ] && commit_args+=(--force-app-files)
[ "$HAD_USER_CONFIG" = "false" ] && commit_args+=(--configure-default-paths)
run_installer_core "${commit_args[@]}"

# Phase 5: optional components
if [ "$INSTALL_VLC_PLUGIN" = "true" ]; then
    record_manifest_component plugin-vlc in_progress
    install_vlc_plugin
    record_manifest_component plugin-vlc installed package_manager "$PACKAGE_MANAGER"
fi
configure_vlc_runtime

# Phase 6: autostart
if [ "$INSTALLATION_AUTOSTART" = "true" ]; then
    configure_autostart
    record_manifest_component autostart installed state installed
else
    launchctl bootout "gui/$(id -u "$TARGET_USER")" "$TARGET_HOME/Library/LaunchAgents/com.wavecymatix.app.plist" >/dev/null 2>&1 || true
    rm -f "$TARGET_HOME/Library/LaunchAgents/com.wavecymatix.app.plist"
    record_manifest_component autostart removed
fi

# Phase 7: finalize
log "Installation completed successfully"
record_manifest_operation succeeded
MANIFEST_ACTIVE="false"
echo "Output directory: $INSTALLATION_PATH"
echo "Package manager: $PACKAGE_MANAGER"
echo "Run WaveCymatix with: $INSTALLATION_PATH/run-wavecymatix.sh"
