# AGENTS.md

## Project overview

Multi-module Python package for Linux voice dictation. Hold a hotkey, speak, release — text appears wherever the cursor is. Uses `sensevoice` via `funasr` for transcription by default (with `faster-whisper` as an alternative engine), `parec` for audio capture, `ydotool` for keystroke injection, and `evdev` for keyboard event reading.

## Tests and CI

- Unit tests across `audio.py`, `config.py`, `keyboard.py`, and `__main__.py`. Run with `make test`.
- CI runs on push/PR via `.github/workflows/ci.yml` — two jobs: `test` (pytest) and `build` (sdist + wheel).
- The project uses `setuptools` via `pyproject.toml` with a `console_scripts` entry point. Install with `python3 -m pip install --user -e .`.

## External Python packages

- `evdev` — comes from the system package `python3-evdev` (apt). Must use apt because evdev needs to access `/dev/input/` devices.
- `funasr` — installed via `pip install --user funasr` (PyPI). Provides the default SenseVoice transcription engine.
- `faster-whisper` — installed via `pip install --user faster-whisper` (PyPI). Alternative CTranslate2-accelerated transcription.

## Package structure

The daemon is a Python package `whisper_anywhere/` installed via `pip install -e .`. The `console_scripts` entry point creates a `whisper-anywhere` wrapper in `~/.local/bin/`.

```
whisper_anywhere/
├── __init__.py
├── __main__.py      # entry point: main(), run_daemon(), transcribe()
├── audio.py         # write_wav(), read_audio(), stop_recording(), runtime paths
├── config.py        # check_deps(), load_config(), parse_args(), runtime_dir()
├── keyboard.py      # find_keyboards(), keys_held()
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
- The daemon itself runs as `systemd --user` service `whisper-anywhere.service` (installed by
  `install.sh`); logs go to journald (`journalctl --user -u whisper-anywhere`). It reads hotkey,
  model, and language from the config file, so the unit never needs regenerating on config edits.

## Config and data locations

- Config: `~/.config/whisper-anywhere/config` (simple `key=value` format, comments with `#`)
- Models: `~/.cache/modelscope/hub/` (SenseVoice via FunASR) or `~/.cache/huggingface/hub/` (faster-whisper)
- Lock + temp audio: `$XDG_RUNTIME_DIR/whisper-anywhere/` (0700), falling back to
  `~/.cache/whisper-anywhere/` — see `config.runtime_dir()`

## Script architecture

- `find_keyboards()` — scans `/dev/input/` for a keyboard device via evdev, skips ydotoold/lid/power/sleep/video
- `check_deps(engine)` — verifies `parec`, `ydotool` are on PATH, `evdev` imports, and the selected engine's package (`funasr` or `faster_whisper`) is importable
- `load_model()` — initializes the transcription engine (default: SenseVoice via `funasr.AutoModel`). Pluggable via the `Transcriber` protocol — see `register_engine()`.
- `write_wav()` — constructs a RIFF/WAV header and writes raw PCM data to a file
- `read_audio()` — async task that reads raw PCM chunks from `parec --raw` stdout until EOF
- `transcribe()` — stops `parec` via `stop_recording()`, drains remaining audio via `read_audio`, writes WAV, runs model (with optional `language`). Returns text.
- `emit()` — delivers text: `ydotool type` (checking the return code / `FileNotFoundError`) or stdout JSON in `--stdout` mode.
- `run_daemon()` — async evdev read loop; spawns `parec --raw` as an `asyncio.subprocess` on hotkey press, pipes audio through `read_audio` into a `bytearray` buffer, calls `transcribe()` on release. Wrapped in a loop that re-acquires the keyboard on hotplug/`OSError`.
- `read_audio()` caps a single recording at `MAX_RECORDING_SECONDS` (60s) so a stuck hotkey can't run `parec` forever.
- Audio capture uses a pipe (`parec --raw` to `asyncio.subprocess.PIPE`) instead of a file — when `parec` stops (SIGINT), Python drains the pipe to EOF, capturing every last buffered sample
- `parec` is started with `--latency-msec=30` to shrink PulseAudio's internal capture buffer from ~250ms to 30ms, so the tail loss on SIGINT is imperceptible
- Two hotkey modes: combo (Ctrl+Super+Space, all three must be held) or single-key (any `KEY_*` from `linux/input-event-codes.h`)
- Hotkey priority: CLI `--hotkey` > config file `hotkey=` > default combo
- Model priority: CLI `--model` > config file `model=` > `iic/SenseVoiceSmall`
- Engine priority: CLI `--engine` > config file `engine=` > `sensevoice`
- Language priority: CLI `--language` > config file `language=` > auto-detect

## Coding conventions

- Prefer OOP (classes with typed attributes) over functional programming with module-level state.
- Always add type annotations to function signatures and class attributes.
