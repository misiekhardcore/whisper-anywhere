#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
BIN_TARGET="$BIN_DIR/whisper-anywhere"
TRAY_TARGET="$BIN_DIR/whisper-anywhere-tray"
CONFIG_DIR="$HOME/.config/whisper-anywhere"
AUTOSTART_DIR="$HOME/.config/autostart"
SERVICE_DIR="$HOME/.config/systemd/user"
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICON_THEME_DIR="$HOME/.local/share/icons/hicolor"
MODEL="${MODEL:-iic/SenseVoiceSmall}"
HOTKEY="${HOTKEY:-}"
PYTHON="${PYTHON:-}"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

info()  { echo "  [INFO]  $*"; }
warn()  { echo "  [WARN]  $*"; }
error() { echo "  [ERROR] $*"; exit 1; }

need_root() {
    if command -v sudo &>/dev/null; then
        SUDO="sudo"
    elif command -v pkexec &>/dev/null; then
        SUDO="pkexec"
    else
        error "neither sudo nor pkexec found — can't install system packages"
    fi
}

pkg_install() {
    if command -v apt-get &>/dev/null; then
        $SUDO apt-get update -qq && $SUDO apt-get install -y "$@"
    else
        error "unsupported package manager (only apt-get is supported)"
    fi
}

# torchaudio publishes no cp315 wheels, so the full stack runs on Python 3.10-3.14.
supported_python_version() {
    local path="$1" version
    version="$("$path" --version 2>&1)" || return 1
    case "$version" in
        "Python 3.10"*|"Python 3.11"*|"Python 3.12"*|"Python 3.13"*|"Python 3.14"*) return 0 ;;
        *) return 1 ;;
    esac
}

supported_python() {
    supported_python_version "$1" || return 1
    "$1" -c "import evdev" 2>/dev/null
}

select_python() {
    local candidate path
    for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 /usr/bin/python3; do
        path="$(type -P "$candidate" 2>/dev/null)" || continue
        supported_python "$path" || continue
        printf '%s' "$path"
        return 0
    done
    return 1
}

# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------

step_system_packages() {
    echo ""
    echo "==> Installing system packages..."
    pkg_install \
				pulseaudio-utils \
				python3-evdev \
				python3-pip \
				python3-gi \
				gir1.2-ayatanaappindicator3-0.1 \
				gir1.2-dbusmenu-glib-0.4 \
				ydotool \
				pkg-config \
				ffmpeg \
				libavformat-dev \
				libavcodec-dev \
				libavdevice-dev \
				libavutil-dev \
				libavfilter-dev \
				libswscale-dev \
				libswresample-dev
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        info "Wayland detected — also installing the clipboard backend (wl-clipboard)"
        pkg_install wl-clipboard
    fi
}

step_python_packages() {
    echo ""
    echo "==> Installing Python packages..."
    # SenseVoice runs on CPU and requires PyTorch.
    "$PYTHON" -m pip install --user torch torchaudio \
        --index-url https://download.pytorch.org/whl/cpu 2>/dev/null \
        || "$PYTHON" -m pip install --user --break-system-packages \
            torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    # sensevoice (default engine) via funasr
    "$PYTHON" -m pip install --user funasr 2>/dev/null \
        || CC=gcc CXX=g++ "$PYTHON" -m pip install --user --break-system-packages funasr
    # faster-whisper currently needs PyAV below 19 for audio decoding.
    "$PYTHON" -m pip install --user faster-whisper "av<19" 2>/dev/null \
        || "$PYTHON" -m pip install --user --break-system-packages faster-whisper "av<19"
}

step_bridge_system_packages() {
    "$PYTHON" -c "import evdev" 2>/dev/null && return
    echo /usr/lib/python3/dist-packages > "$("$PYTHON" -c "import sysconfig; print(sysconfig.get_path('purelib'))")/system_dist_packages.pth"
    info "bridged evdev from system dist-packages"
}

step_input_group() {
    echo ""
    echo "==> Adding user to 'input' group (needed for keyboard event access)..."
    if groups "$USER" | grep -q input; then
        info "already in input group"
    else
        $SUDO usermod -a -G input "$USER"
        info "added to input group — you'll need to log out and back in (or reboot)"
    fi
}

step_ydotool_service() {
    echo ""
    echo "==> Enabling ydotool systemd user service (paste chord injector)..."
    systemctl --user enable --now ydotool.service 2>/dev/null || true
    if systemctl --user is-active ydotool.service &>/dev/null; then
        info "ydotool service is running"
    else
        warn "ydotool service not running — try: systemctl --user start ydotool.service"
    fi
}

step_model() {
    echo ""
    echo "==> Pre-loading default model ($MODEL)..."
    # funasr/SenseVoice auto-downloads on first use; this pre-warms the cache.
    # Non-fatal: the model will download on first daemon run if skipped here.
    "$PYTHON" -c "
from funasr import AutoModel
import sys
sys.stderr.write('Downloading model $MODEL...\n')
m = AutoModel(model='$MODEL', device='cpu')
sys.stderr.write('Model $MODEL ready.\n')
" 2>/dev/null || warn "model pre-load skipped (will download on first use)"
}

step_install_package() {
    echo ""
    echo "==> Installing whisper-anywhere package..."
    "$PYTHON" -m pip install --user -e "$REPO_DIR" 2>/dev/null \
        || "$PYTHON" -m pip install --user --break-system-packages -e "$REPO_DIR"
    info "installed as pip package from $REPO_DIR"
}

step_units() {
    echo ""
    echo "==> Setting up systemd user services (autostart + logging)..."
    mkdir -p "$SERVICE_DIR"

    # Hotkey/model/language are read from the config file, so the unit never
    # needs regenerating when those change — just edit config and restart.
    cat > "$SERVICE_DIR/whisper-anywhere.service" << EOF
[Unit]
Description=whisper-anywhere voice dictation daemon
After=ydotool.service graphical-session.target
Wants=ydotool.service

[Service]
ExecStart=$BIN_TARGET
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF

    # The tray follows the graphical session and never restarts on its own: a
    # headless or hostless desktop must not restart-storm it.
    cat > "$SERVICE_DIR/whisper-anywhere-tray.service" << EOF
[Unit]
Description=whisper-anywhere tray indicator
After=graphical-session.target

[Service]
ExecStart=$TRAY_TARGET
Restart=no

[Install]
WantedBy=graphical-session.target
EOF

    # Migrate away from the old XDG autostart entry if a previous install left one.
    rm -f "$AUTOSTART_DIR/whisper-anywhere.desktop"
}

step_autostart() {
    local start_at_login="$1"
    systemctl --user daemon-reload 2>/dev/null || true
    if [ "$start_at_login" = "1" ]; then
        systemctl --user enable whisper-anywhere.service whisper-anywhere-tray.service 2>/dev/null || true
        info "autostart enabled for both units"
    else
        systemctl --user disable whisper-anywhere.service whisper-anywhere-tray.service 2>/dev/null || true
        info "autostart disabled — start it from the menu or: systemctl --user start whisper-anywhere"
    fi
}

step_start() {
    systemctl --user start whisper-anywhere.service whisper-anywhere-tray.service 2>/dev/null || true
    if systemctl --user is-active whisper-anywhere.service &>/dev/null; then
        info "whisper-anywhere service is running"
    else
        warn "service not active yet — run: systemctl --user start whisper-anywhere"
    fi
    info "units installed at $SERVICE_DIR"
    info "logs: journalctl --user -u whisper-anywhere -f"
}

resolve_autostart() {
    # Prints 1 or 0: enabled by default, one question on a TTY, AUTOSTART when scripted.
    local start_at_login=1
    if [ -t 0 ]; then
        local answer=""
        # EOF or Ctrl-D means the documented default: yes.
        read -r -p "  Start whisper-anywhere at login? [Y/n] " answer || true
        case "$answer" in
            n|N|no|No|NO) start_at_login=0 ;;
        esac
    elif [ -n "${AUTOSTART:-}" ]; then
        case "$AUTOSTART" in
            0|no|false) start_at_login=0 ;;
        esac
    fi
    printf '%s' "$start_at_login"
}

step_launcher() {
    echo ""
    echo "==> Adding the desktop launcher..."
    mkdir -p "$APPLICATIONS_DIR"
    # Launcher and login autostart both start the units through systemctl --user,
    # so they share one supervisor; each unit keeps its own journald log.
    cat > "$APPLICATIONS_DIR/whisper-anywhere.desktop" << EOF
[Desktop Entry]
Type=Application
Name=whisper-anywhere
GenericName=Voice dictation
Comment=Hold a hotkey, speak, release - text appears wherever the cursor is
Exec=systemctl --user start whisper-anywhere.service whisper-anywhere-tray.service
Icon=whisper-anywhere
Keywords=dictation;speech;voice;transcription;microphone;speech-to-text;
Terminal=false
Categories=Utility;
EOF

    # The menu lets the icon theme resolve the entry's Icon= by name.
    local source size target
    for source in "$REPO_DIR"/whisper_anywhere/icons/launcher/whisper-anywhere-*.png; do
        size="$(basename "$source" .png)"
        size="${size##*-}"
        target="$ICON_THEME_DIR/${size}x${size}/apps"
        mkdir -p "$target"
        cp "$source" "$target/whisper-anywhere.png"
    done

    # Some menus cache desktop entries; refresh it when the tool is present.
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$APPLICATIONS_DIR" 2>/dev/null || true
    fi
    info "launcher installed at $APPLICATIONS_DIR/whisper-anywhere.desktop"
}

step_config() {
    echo ""
    echo "==> Setting up config..."
    mkdir -p "$CONFIG_DIR"
    if [ ! -f "$CONFIG_DIR/config" ]; then
        cat > "$CONFIG_DIR/config" << 'EOF'
# whisper-anywhere config
# Uncomment and set the hotkey you want:
# hotkey=KEY_F12
# hotkey=KEY_F7
# hotkey=KEY_GRAVE
#
# Engine (sensevoice or faster-whisper):
# engine=sensevoice
#
# Uncomment to use a different model:
# model=iic/SenseVoiceSmall
#
# Uncomment to force a language (default: auto-detect):
# language=en
EOF
        if [ -n "$HOTKEY" ]; then
            echo "hotkey=$HOTKEY" >> "$CONFIG_DIR/config"
        fi
        info "config created at $CONFIG_DIR/config"
    else
        info "config already exists at $CONFIG_DIR/config (not overwritten)"
    fi
}

summary() {
    local start_at_login="$1"
    echo ""
    echo "============================================"
    echo "  whisper-anywhere is installed!"
    echo "============================================"
    echo ""
    if groups "$USER" | grep -q input; then
        echo "  You're in the 'input' group ✓"
    else
        echo "  ⚠  Log out and back in for 'input' group to take effect"
    fi
    echo ""
    echo "  Usage:"
    echo "    $ whisper-anywhere"
    echo ""
    if [ -n "$HOTKEY" ]; then
        echo "    Hotkey: $HOTKEY (hold to record, release to transcribe)"
    else
        echo "    Hotkey: Ctrl+Super+Space (hold to record, release to transcribe)"
        echo "           (or set hotkey=KEY_F12 in $CONFIG_DIR/config)"
    fi
    echo ""
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        echo "  Insertion: transcript written to the clipboard, one Ctrl+V paste chord"
        echo "    (wl-clipboard backend, ydotool chord injector)"
    else
        echo "  Insertion: typing through ydotool (no clipboard backend on this session)"
    fi
    echo ""
    if [ "$start_at_login" = "1" ]; then
        echo "  The daemon and the tray run as systemd user services and auto-start on login."
    else
        echo "  The daemon and the tray run as systemd user services but will not start at login."
        echo "  Launch them from the menu, or enable autostart: systemctl --user enable whisper-anywhere whisper-anywhere-tray"
    fi
    echo "    start now:  systemctl --user start whisper-anywhere whisper-anywhere-tray"
    echo "    status:     systemctl --user status whisper-anywhere whisper-anywhere-tray"
    echo "    logs:       journalctl --user -u whisper-anywhere -f"
    echo "    after edits: systemctl --user restart whisper-anywhere"
    echo ""
    echo "  Note: The first run downloads the model — may take a moment."
    echo ""
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "Usage: bash install.sh"
    echo ""
    echo "Installs whisper-anywhere and its dependencies."
    echo ""
    echo "Environment variables:"
    echo "  MODEL    SenseVoice model name  (default: iic/SenseVoiceSmall)"
    echo "  HOTKEY   Single key like KEY_F12  (default: none → Ctrl+Super+Space combo)"
    echo "  PYTHON   Python 3.10-3.14 interpreter path  (default: auto-detected)"
    echo "  AUTOSTART  1 to enable login autostart, 0 to leave it off  (default: 1; only read when stdin is not a terminal)"
    exit 0
fi

echo ""
echo "  whisper-anywhere installer"
echo "  ========================="

if [ -n "$PYTHON" ]; then
    # Explicit overrides are version-checked here; the evdev bridge runs later.
    supported_python_version "$PYTHON" ||
        error "PYTHON=$PYTHON is not a supported Python (need 3.10-3.14); set it to a supported interpreter or unset it to auto-detect"
fi

need_root
step_system_packages
if [ -z "$PYTHON" ]; then
    PYTHON="$(select_python)" || error "no supported Python found (need 3.10-3.14 with python3-evdev); install python3-evdev or set PYTHON to a supported interpreter"
    info "using $PYTHON ($("$PYTHON" --version 2>&1))"
fi
step_bridge_system_packages
step_input_group
step_ydotool_service
step_python_packages
step_install_package
step_model
step_config
start_at_login="$(resolve_autostart)"
step_units
step_autostart "$start_at_login"
step_start
step_launcher
summary "$start_at_login"
