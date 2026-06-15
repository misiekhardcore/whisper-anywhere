# whisper-anywhere

Hold a hotkey, speak, release — text appears in the focused window.

Offline, local voice dictation for Linux using SenseVoice (FunASR) by default, with faster-whisper and Vosk as alternative engines. No cloud API, no data leaves your machine.

> **Language support**: SenseVoice supports explicit language codes `zh`, `en`, `yue`, `ja`, `ko` only (or `auto` for auto-detect). Other languages (e.g. Polish, German) are **not** supported with explicit codes — use the faster-whisper engine for non-English languages that aren't in SenseVoice's limited set.

## How it works

**Batch mode** (default, no VAD):
1. Hold a hotkey (default: `Ctrl+Super+Space`, configurable to a single key like `F12`)
2. Speak — audio is recorded via PulseAudio
3. Release — the engine transcribes everything at once, `ydotool` types the text

**Live mode** (`--vad` or `vad_engine=fsmn-vad`):
1. Hold the hotkey and speak — VAD detects speech segments in real-time
2. Each utterance is transcribed incrementally, with partial results replacing the previous text on screen
3. Release the hotkey — remaining audio is transcribed and typed

## Requirements

- **Ubuntu** (or Debian-based distro with `apt`)
- **PulseAudio or PipeWire** (for `parec`)
- **A Wayland or X11 desktop** — `ydotool` injects keystrokes via the kernel `uinput`
  device, so it works under either (tested on GNOME and KDE Plasma)
- **systemd** (the daemon installs as a `systemd --user` service)

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

# Python packages (default: sensevoice via funasr)
python3 -m pip install --user funasr
# Optional: faster-whisper for alternative engine
python3 -m pip install --user faster-whisper
# Optional: Vosk for lightweight multilingual transcription
python3 -m pip install --user vosk

# install whisper-anywhere itself
python3 -m pip install --user -e .

# input group for keyboard access
sudo usermod -a -G input $USER
# log out and back in

# ydotool daemon
systemctl --user enable --now ydotool.service
```

## Usage

`install.sh` sets the daemon up as a `systemd --user` service that auto-starts on login:

```bash
systemctl --user status whisper-anywhere      # check it's running
journalctl --user -u whisper-anywhere -f       # follow logs
systemctl --user restart whisper-anywhere      # apply config changes
```

Or run it in the foreground (useful for debugging):

```bash
whisper-anywhere
```

Either way: hold the hotkey, speak, release. Text appears wherever your cursor is.

### Configuration

Edit `~/.config/whisper-anywhere/config`, then `systemctl --user restart whisper-anywhere`:

```ini
# Single-key mode (F12 — no app conflicts)
hotkey=KEY_F12

# Or omit for Ctrl+Super+Space combo
# hotkey=

# Engine (sensevoice, faster-whisper, or vosk)
# engine=sensevoice

# Model name (default: iic/SenseVoiceSmall)
# model=iic/SenseVoiceSmall

# Force a language (e.g. zh, en, yue, ja, ko). SenseVoice supports
# only zh, en, yue, ja, ko — other codes are ignored (auto-detected).
# With faster-whisper, any ISO 639-1 code works.
# language=en
#
# VAD engine for live streaming (fsmn-vad):
# vad_engine=fsmn-vad
#
# Disable live streaming and use batch mode:
# vad=off
```

### Command-line options

```bash
whisper-anywhere --hotkey KEY_F12       # single-key mode
whisper-anywhere --hotkey KEY_GRAVE     # use backtick key
whisper-anywhere --engine faster-whisper
whisper-anywhere --engine vosk
whisper-anywhere --model vosk-model-small-en-us-0.15
whisper-anywhere --model distil-small.en
whisper-anywhere --language en          # force language (SenseVoice: zh/en/yue/ja/ko; faster-whisper: any ISO 639-1; Vosk: any ISO 639-1)
whisper-anywhere --vad                  # live mode with FSMN-VAD
whisper-anywhere --vad=off              # explicit batch mode
whisper-anywhere --stdout               # JSON lines output (for opencode plugin)
```

> **opencode plugin**: [whisper-anywhere-opencode](https://github.com/misiekhardcore/whisper-anywhere-opencode) integrates dictation into the opencode TUI. Install via `npm install -g whisper-anywhere-opencode` and add to `opencode.json`.

## Models

Downloaded automatically on first use. Default engine uses SenseVoice via [FunASR](https://github.com/modelscope/FunASR); alternative engines use [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [Vosk](https://alphacephei.com/vosk/).

### SenseVoice (default, `--engine sensevoice`)

| Model | Size | Notes |
|---|---|---|
| `iic/SenseVoiceSmall` | ~120 MB | Default, MIT license, 15-17x faster than Whisper on CPU. **Explicit language codes**: zh, en, yue, ja, ko only. |

### faster-whisper (`--engine faster-whisper`)

| Model | Size | Quality | Language |
|---|---|---|---|
| `distil-large-v3` | 1.5 GB | Best | Multilingual (default when a non-English language is requested) |
| `distil-medium.en` | 300 MB | Better | English only |
| `distil-small.en` | 94 MB | Good | English only |

Set via config or `--model`. When you request a non-English language without specifying a model, `distil-large-v3` is automatically selected.

### Vosk (`--engine vosk`)

| Model | Size | Languages |
|---|---|---|
| `vosk-model-small-en-us-0.15` | ~40 MB | English |
| `vosk-model-small-pl-0.22` | ~50 MB | Polish |
| `vosk-model-small-de-0.15` | ~40 MB | German |
| `vosk-model-small-fr-0.22` | ~50 MB | French |
| `vosk-model-small-es-0.22` | ~50 MB | Spanish |
| `vosk-model-small-pt-0.3` | ~50 MB | Portuguese |
| `vosk-model-small-ru-0.22` | ~50 MB | Russian |
| `vosk-model-small-it-0.22` | ~50 MB | Italian |
| `vosk-model-small-nl-0.22` | ~50 MB | Dutch |
| `vosk-model-small-tr-0.3` | ~50 MB | Turkish |
| `vosk-model-small-vn-0.3` | ~50 MB | Vietnamese |
| `vosk-model-small-ja-0.22` | ~50 MB | Japanese |
| `vosk-model-small-cn-0.22` | ~50 MB | Chinese |
| `vosk-model-small-hi-0.22` | ~50 MB | Hindi |
| `vosk-model-small-ar-0.22` | ~40 MB | Arabic |
| `vosk-model-small-fa-0.5` | ~50 MB | Persian |

Models are auto-downloaded on first use to `~/.cache/vosk/`. Set the language code (e.g. `pl`, `de`, `fr`) via `--language` or the config file to auto-select the matching model. Alternatively, specify any model name directly with `--model`.

> **Performance**: SenseVoiceSmall is 15-17x faster than Whisper on CPU (explicit codes: zh, en, yue, ja, ko). faster-whisper uses CTranslate2 with int8 quantization, typically 2-4x faster than whisper.cpp on CPU. Vosk is lightweight and efficient on CPU, with small model sizes suited for specific languages.

## Project layout

```
whisper-anywhere/
├── whisper_anywhere/    # Python package
│   ├── __init__.py
│   ├── __main__.py      # daemon entry point, config resolution
│   ├── audio.py         # audio capture and WAV writing
│   ├── config.py        # configuration and CLI args
│   ├── daemon.py        # main event loop, keyboard device handling
│   ├── keyboard.py      # evdev keyboard detection
│   ├── lock.py          # single-instance lock
│   ├── output.py        # text output (ydotool / stdout)
│   ├── recording.py     # audio recording and VAD-gated live loop
│   ├── transcribe.py    # model loading and engine registry
│   └── vad.py           # voice activity detection
├── tests/               # pytest suite
├── install.sh           # one-shot installer
├── uninstall.sh         # reverses install.sh
├── Makefile             # development commands
├── pyproject.toml       # package metadata
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

## Uninstall

```bash
bash uninstall.sh
```

Removes the systemd user service and the pip package, and offers to delete your config.
The HuggingFace model cache, pip dependencies, and `input`-group membership are left in
place (the script prints how to remove them).

## License

MIT
