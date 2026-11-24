# AGENTS.md

## Project overview

Multi-module Python package for Linux voice dictation. Hold a hotkey, speak, release — text appears wherever the cursor is. Uses `sensevoice` via `funasr` for transcription by default (with `faster-whisper` as an alternative engine), `parec` for audio capture, `wl-copy`/`wl-paste` and `ydotool` for clipboard-paste insertion, and `evdev` for keyboard event reading.

## Tests and CI

- Unit tests across `audio.py`, `config.py`, `keyboard.py`, `daemon.py`, `output.py`, `recording.py`, and `__main__.py`. Run with `make test`; every development target provisions `.venv` from an `evdev`-capable Python via the Makefile, so no manual setup is needed.
- CI runs on push/PR via `.github/workflows/ci.yml` — two jobs: `test` (pytest) and `build` (sdist + wheel).
- **Pre-commit gate:** Run `make lint && make test` before any commit. Fix all failures.
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
├── __main__.py      # entry point: main(), config resolution (load_hotkey, plan_engine)
├── audio.py         # write_wav(), read_audio(), stop_recording(), runtime paths
├── config.py        # check_deps(), load_config(), parse_args(), runtime_dir()
├── daemon.py        # Daemon.run(), _pump_device(), keyboard device handling
├── keyboard.py      # find_keyboards(), keys_held()
├── lock.py          # Lock.acquire(), Lock.release(), LOCK_PATH
├── output.py        # async emit() -> inserter
├── recording.py     # Recording, Recorder.start(), Recorder.finish()
├── transcribe/      # load_engine(), Transcriber protocol, one module per engine
└── insertion/       # TextInserter, Clipboard/WaylandClipboard, PasteChord,
                     # ClipboardInserter, TypingInserter, select_insertion()
```

## System dependencies (apt only)

- `pulseaudio-utils` — provides `parec`
- `python3-evdev` — provides `evdev` Python module
- `ydotool` — provides `ydotool` (paste chord and typing fallback)
- `wl-clipboard` — provides `wl-copy`/`wl-paste` (Wayland clipboard backend, preferred)
- `wtype` — optional; sends the paste chord and types only when `ydotool` is absent

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
- `check_deps(engine, insertion)` — verifies `parec` is on PATH, `evdev` imports, the selected engine's package is importable (`funasr` for SenseVoice only, `faster_whisper`, or `vosk`), and the already-resolved insertion strategy is usable; `main()` resolves that strategy once, so the diagnosis and the running inserter cannot disagree
- `select_insertion()` — resolves insertion once at startup: clipboard paste when a Wayland clipboard backend and a chord injector exist, otherwise typing; returns the description, an optional warning and the inserter
- `load_engine(engine_id, model_id, language)` — builds the selected engine from the `register_engine()` registry, defaulting to SenseVoice and `iic/SenseVoiceSmall`
- `plan_engine()` — resolves engine id and model from CLI, then config, and defers the `load_engine()` call until the daemon has published loading
- `write_wav()` — constructs a RIFF/WAV header and writes raw PCM data to a file
- `read_audio()` — async task that reads raw PCM chunks from `parec --raw` stdout until EOF
- `Recorder.start()` — spawns `parec --raw` and returns a `Recording` (process, reader task, PCM buffer)
- `Recorder.finish()` — stops `parec` via `stop_recording()`, drains the remaining audio, writes the WAV, runs the engine once over the whole recording and emits the transcript once. An empty recording, a blank transcript and an engine error all end quietly with a line on stderr.
- `emit()` — async; delivers text through the resolved `TextInserter` in a worker thread (clipboard write plus one paste chord, or typing), or prints one `{"type": "final", "text": ...}` line in `--stdout` mode. An empty transcript emits nothing.
- `ClipboardInserter.insert_text()` — writes the transcript with `wl-copy`, then sends one Ctrl+V chord via `ydotool` (or `wtype`). A failed write sends no chord; a failed chord leaves the transcript on the clipboard. Subprocesses run detached (`stdout=DEVNULL`) because a forked selection owner holding an inherited pipe would otherwise block forever.
- `Daemon.run()` — async evdev read loop; a hotkey press starts a `Recorder.start()`, the matching release calls `Recorder.finish()`. One dictation is one engine call and one emission. Wrapped in a loop that re-acquires the keyboard on hotplug/`OSError`.
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
