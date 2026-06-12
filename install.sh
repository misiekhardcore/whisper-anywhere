#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON="$REPO_DIR/whisper-anywhere"
BIN_DIR="$HOME/.local/bin"
BIN_TARGET="$BIN_DIR/whisper-anywhere"
CONFIG_DIR="$HOME/.config/whisper-anywhere"
AUTOSTART_DIR="$HOME/.config/autostart"
MODEL="${MODEL:-distil-large-v3}"
HOTKEY="${HOTKEY:-}"

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
    pip3 install --user faster-whisper 2>/dev/null \
        || pip3 install --user --break-system-packages faster-whisper
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
    echo "==> Pre-loading whisper model ($MODEL)..."
    # faster-whisper auto-downloads on first use; this pre-warms the cache
    python3 -c "
from faster_whisper import WhisperModel
import sys
sys.stderr.write('Downloading model $MODEL...\n')
m = WhisperModel('$MODEL', device='cpu', compute_type='int8')
sys.stderr.write('Model $MODEL ready.\n')
"
}

step_install_daemon() {
    echo ""
    echo "==> Installing whisper-anywhere script..."
    mkdir -p "$BIN_DIR"
    cp "$DAEMON" "$BIN_TARGET"
    chmod +x "$BIN_TARGET"
    info "installed to $BIN_TARGET"
}

step_autostart() {
    echo ""
    echo "==> Setting up autostart..."
    mkdir -p "$AUTOSTART_DIR"

    HOTKEY_ARG=""
    if [ -n "$HOTKEY" ]; then
        HOTKEY_ARG=" --hotkey $HOTKEY"
    fi

    cat > "$AUTOSTART_DIR/whisper-anywhere.desktop" << EOF
[Desktop Entry]
Type=Application
Name=whisper-anywhere
Comment=Voice dictation daemon — hold hotkey, speak, release
Exec=$BIN_TARGET$HOTKEY_ARG
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    info "autostart entry created at $AUTOSTART_DIR/whisper-anywhere.desktop"
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
# Uncomment to use a different model:
# model=distil-large-v3
# model=distil-medium.en
# model=distil-small.en
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
    echo "  The daemon will auto-start on next login."
    echo "  To start now:"
    echo "    $ whisper-anywhere &"
    echo ""
    echo "  Note: The first run downloads the model — may take a moment."
    echo ""
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

echo ""
echo "  whisper-anywhere installer"
echo "  ========================="

need_root
step_system_packages
step_input_group
step_ydotool_service
step_python_packages
step_model
step_install_daemon
step_autostart
step_config
summary
