#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="$HOME/.config/whisper-anywhere"
AUTOSTART_DIR="$HOME/.config/autostart"
SERVICE_DIR="$HOME/.config/systemd/user"
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICON_THEME_DIR="$HOME/.local/share/icons/hicolor"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-$HOME/.cache}/whisper-anywhere"
PYTHON="${PYTHON:-$(which python3)}"

info() { echo "  [INFO]  $*"; }

echo ""
echo "  whisper-anywhere uninstaller"
echo "  ============================"

# Stop and disable both systemd user units.
systemctl --user disable --now whisper-anywhere.service whisper-anywhere-tray.service 2>/dev/null || true
rm -f "$SERVICE_DIR/whisper-anywhere.service"
rm -f "$SERVICE_DIR/whisper-anywhere-tray.service"
systemctl --user daemon-reload 2>/dev/null || true
info "removed systemd user units"

# The launcher starts both units through systemctl; its icon lives in the theme.
rm -f "$APPLICATIONS_DIR/whisper-anywhere.desktop"
rm -f "$ICON_THEME_DIR"/*x*/apps/whisper-anywhere.png
info "removed the desktop launcher and its icon"

# The daemon's status socket; the lock and temporary audio belong to a run.
rm -f "$RUNTIME_DIR/state.sock"
info "removed the status socket"

# Remove the legacy XDG autostart entry, if an older install left one.
rm -f "$AUTOSTART_DIR/whisper-anywhere.desktop"

# Uninstall the Python package.
"$PYTHON" -m pip uninstall -y whisper-anywhere 2>/dev/null \
    || "$PYTHON" -m pip uninstall -y --break-system-packages whisper-anywhere 2>/dev/null \
    || true
info "uninstalled whisper-anywhere package"

# Config is the user's data — ask before removing.
if [ -d "$CONFIG_DIR" ]; then
    read -r -p "  Remove config at $CONFIG_DIR? [y/N] " ans
    case "${ans:-}" in
        y|Y) rm -rf "$CONFIG_DIR"; info "removed $CONFIG_DIR" ;;
        *)   info "kept $CONFIG_DIR" ;;
    esac
fi

echo ""
echo "  Done. Left in place (remove manually if you want them gone):"
echo "    - faster-whisper and other pip dependencies"
echo "    - HuggingFace model cache (~/.cache/huggingface)"
echo "    - 'input' group membership  (sudo gpasswd -d \"\$USER\" input)"
echo ""
