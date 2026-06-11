# whisper-anywhere

Hold a hotkey, speak, release — text appears in the focused window.

Offline, local voice dictation for Linux using `whisper.cpp`. No cloud API, no data leaves your machine.

## How it works

1. Hold a hotkey (default: `Ctrl+Super+Space`, configurable to a single key like `F12`)
2. Speak — audio is recorded via PulseAudio
3. Release — `whisper-cli` transcribes locally, `ydotool` types the text

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
# dependencies
sudo apt install whisper.cpp pulseaudio-utils python3-evdev ydotool

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
model=ggml-base.en.bin
```

### Command-line options

```bash
whisper-anywhere --hotkey KEY_F12     # single-key mode
whisper-anywhere --hotkey KEY_GRAVE   # use backtick key
whisper-anywhere --model ggml-small.en.bin
```

## Models

Downloaded automatically from [whisper.cpp](https://github.com/ggerganov/whisper.cpp) on first run:

| Model | Size | Quality |
|---|---|---|
| `ggml-base.en.bin` | 142 MB | Good (default) |
| `ggml-small.en.bin` | 466 MB | Better |
| `ggml-medium.en.bin` | 1.5 GB | Best |

Set via config or `--model`.

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
