#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
BIN_TARGET="$BIN_DIR/whisper-anywhere"
CONFIG_DIR="$HOME/.config/whisper-anywhere"
AUTOSTART_DIR="$HOME/.config/autostart"
SERVICE_DIR="$HOME/.config/systemd/user"
MODEL="${MODEL:-iic/SenseVoiceSmall}"
HOTKEY="${HOTKEY:-}"
PYTHON="${PYTHON:-$(which python3)}"

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
        ydotool

    # wl-clipboard is optional but useful
    if command -v wl-copy &>/dev/null; then
        info "wl-clipboard already installed"
    else
        info "installing wl-clipboard (optional, for clipboard-based typing fallback)"
        pkg_install wl-clipboard || true
    fi
}

step_python_packages() {
    echo ""
    echo "==> Installing Python packages..."
    # sensevoice (default engine) via funasr
    "$PYTHON" -m pip install --user funasr 2>/dev/null \
        || CC=gcc CXX=g++ "$PYTHON" -m pip install --user --break-system-packages funasr
    # faster-whisper is also installed so users can switch with --engine faster-whisper
    "$PYTHON" -m pip install --user faster-whisper 2>/dev/null \
        || "$PYTHON" -m pip install --user --break-system-packages faster-whisper
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
    echo "==> Enabling ydotool systemd user service..."
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

step_vad_model() {
    echo ""
    echo "==> Pre-loading VAD model (fsmn-vad)..."
    "$PYTHON" -c "
from funasr import AutoModel
import sys
sys.stderr.write('Downloading VAD model fsmn-vad...\n')
m = AutoModel(model='fsmn-vad', device='cpu')
sys.stderr.write('VAD model fsmn-vad ready.\n')
" 2>/dev/null || warn "VAD model pre-load skipped (will download on first use)"
}

step_install_package() {
    echo ""
    echo "==> Installing whisper-anywhere package..."
    "$PYTHON" -m pip install --user -e "$REPO_DIR" 2>/dev/null \
        || "$PYTHON" -m pip install --user --break-system-packages -e "$REPO_DIR"
    info "installed as pip package from $REPO_DIR"
}

step_service() {
    echo ""
    echo "==> Setting up systemd user service (autostart + logging)..."
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

    # Migrate away from the old XDG autostart entry if a previous install left one.
    rm -f "$AUTOSTART_DIR/whisper-anywhere.desktop"

    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now whisper-anywhere.service 2>/dev/null || true
    if systemctl --user is-active whisper-anywhere.service &>/dev/null; then
        info "whisper-anywhere service is running"
    else
        warn "service not active yet — after logging in run: systemctl --user enable --now whisper-anywhere.service"
    fi
    info "service installed at $SERVICE_DIR/whisper-anywhere.service"
    info "logs: journalctl --user -u whisper-anywhere -f"
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
#
# VAD engine for live streaming (fsmn-vad):
# vad_engine=fsmn-vad
#
# Set vad=off to disable live streaming (batch mode):
# vad=off
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
    echo "  The daemon runs as a systemd user service and auto-starts on login."
    echo "    start now:  systemctl --user start whisper-anywhere"
    echo "    status:     systemctl --user status whisper-anywhere"
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
    echo "  PYTHON   Python interpreter path  (default: python3 from PATH)"
    exit 0
fi

echo ""
echo "  whisper-anywhere installer"
echo "  ========================="

need_root
step_system_packages
step_bridge_system_packages
step_input_group
step_ydotool_service
step_python_packages
step_install_package
step_model
step_vad_model
step_config
step_service
summary
