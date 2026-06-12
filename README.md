# whisper-anywhere

Hold a hotkey, speak, release — text appears in the focused window.

Offline, local voice dictation for Linux using faster-whisper (CTranslate2). No cloud API, no data leaves your machine.

## How it works

1. Hold a hotkey (default: `Ctrl+Super+Space`, configurable to a single key like `F12`)
2. Speak — audio is recorded via PulseAudio
3. Release — faster-whisper transcribes locally, `ydotool` types the text

## Requirements

- **Ubuntu** (or Debian-based distro with `apt`)
- **PulseAudio or PipeWire** (for `parec`)
- **GNOME or KDE Plasma on Wayland** (for `ydotool`)

## Quick install

```bash
git clone https://github.com/misiekhardcore/whisper-anywhere
cd whisper-anywhere
bash install.sh
```

Or manually, step by step:

```bash
# system dependencies
sudo apt install pulseaudio-utils python3-evdev python3-pip ydotool

# Python package
pip3 install --user faster-whisper

# input group for keyboard access
sudo usermod -a -G input $USER
# log out and back in

# ydotool daemon
systemctl --user enable --now ydotool.service
```

## Usage

```bash
whisper-anywhere
```

Then hold the hotkey, speak, release. Text appears wherever your cursor is.

### Configuration

Edit `~/.config/whisper-anywhere/config`:

```ini
# Single-key mode (F12 — no app conflicts)
hotkey=KEY_F12

# Or omit for Ctrl+Super+Space combo
# hotkey=

# Model size
model=distil-large-v3
```

### Command-line options

```bash
whisper-anywhere --hotkey KEY_F12     # single-key mode
whisper-anywhere --hotkey KEY_GRAVE   # use backtick key
whisper-anywhere --model distil-small.en
```

## Models

Downloaded automatically from HuggingFace on first use (by [faster-whisper](https://github.com/SYSTRAN/faster-whisper)):

| Model | Size | Quality |
|---|---|---|
| `distil-large-v3` | 1.5 GB | Best (default) |
| `distil-medium.en` | 300 MB | Better |
| `distil-small.en` | 94 MB | Good |

Set via config or `--model`.

> **Performance**: faster-whisper uses CTranslate2 with int8 quantization, typically 2-4x faster than whisper.cpp on CPU with comparable accuracy.

## Project layout

```
whisper-anywhere/
├── whisper-anywhere    # the daemon (single Python script)
├── install.sh          # one-shot installer
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

## License

MIT
