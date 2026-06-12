# AGENTS.md

## Project overview

Multi-module Python package for Linux voice dictation. Hold a hotkey, speak, release — text appears wherever the cursor is. Uses `faster-whisper` for transcription, `parec` for audio capture, `ydotool` for keystroke injection, and `evdev` for keyboard event reading.

## Tests and CI

- 39 unit tests across `audio.py`, `config.py`, and `keyboard.py`. Run with `make test`.
- CI runs on push/PR via `.github/workflows/ci.yml` — two jobs: `test` (pytest) and `build` (sdist + wheel).
- The project uses `setuptools` via `pyproject.toml` with a `console_scripts` entry point. Install with `python3 -m pip install --user -e .`.

## External Python packages

- `evdev` — comes from the system package `python3-evdev` (apt). Must use apt because evdev needs to access `/dev/input/` devices.
- `faster-whisper` — installed via `pip install --user faster-whisper` (PyPI). Provides CTranslate2-accelerated transcription.

## Package structure

The daemon is a Python package `whisper_anywhere/` installed via `pip install -e .`. The `console_scripts` entry point creates a `whisper-anywhere` wrapper in `~/.local/bin/`.

```
whisper_anywhere/
├── __init__.py
├── __main__.py      # entry point: main(), run_daemon(), transcribe()
├── audio.py         # write_wav(), read_audio()
├── config.py        # check_deps(), load_config(), parse_args()
├── keyboard.py      # find_keyboard(), keys_held()
└── transcribe.py    # load_model()
```

## System dependencies (apt only)

- `pulseaudio-utils` — provides `parec`
- `python3-evdev` — provides `evdev` Python module
- `ydotool` — provides `ydotool` (keystroke injection)

## Key runtime requirements

- User must be in the `input` group (`sudo usermod -a -G input $USER`) for evdev keyboard access.
- `ydotool` systemd user service must be running (`systemctl --user start ydotool.service`).
- PulseAudio or PipeWire must be running for `parec`.

## Config and data locations

- Config: `~/.config/whisper-anywhere/config` (simple `key=value` format, comments with `#`)
- Models: `~/.local/share/whisper/models/`
- Temp audio: `/tmp/whisper-anywhere.wav`

## opencode plugin

An opencode plugin lives at `.opencode/plugins/whisper-anywhere.ts`:
- Spawns `whisper-anywhere --stdout` as a child process
- Reads JSON lines from stdout: `{"text": "..."}`
- Injects text into TUI via `client.tui.appendPrompt()`
- Registers `/voice` toggle command
- Falls back to ydotool when the plugin is not connected (via `--stdout` flag logic)

The plugin is auto-discovered by opencode when placed in `.opencode/plugins/`.

## Script architecture

- `find_keyboard()` — scans `/dev/input/` for a keyboard device via evdev, skips ydotoold/lid/power/sleep/video
- `check_deps()` — verifies `parec`, `ydotool` are on PATH and `evdev`/`faster_whisper` import works
- `load_model()` — initializes faster-whisper `WhisperModel` (auto-downloads from HuggingFace on first use)
- `write_wav()` — constructs a RIFF/WAV header and writes raw PCM data to a file
- `read_audio()` — async task that reads raw PCM chunks from `parec --raw` stdout until EOF
- `transcribe()` — sends SIGINT to `parec`, drains remaining audio via `read_audio`, writes WAV, runs model. Returns text; caller decides output (ydotool or stdout JSON).
- `run_daemon()` — async evdev read loop; spawns `parec --raw` as an `asyncio.subprocess` on hotkey press, pipes audio through `read_audio` into a `bytearray` buffer, calls `transcribe()` on release
- Audio capture uses a pipe (`parec --raw` to `asyncio.subprocess.PIPE`) instead of a file — when `parec` stops (SIGINT), Python drains the pipe to EOF, capturing every last buffered sample
- `parec` is started with `--latency-msec=30` to shrink PulseAudio's internal capture buffer from ~250ms to 30ms, so the tail loss on SIGINT is imperceptible
- Two hotkey modes: combo (Ctrl+Super+Space, all three must be held) or single-key (any `KEY_*` from `linux/input-event-codes.h`)
- Hotkey priority: CLI `--hotkey` > config file `hotkey=` > default combo
- Model priority: CLI `--model` > config file `model=` > `distil-medium.en`
