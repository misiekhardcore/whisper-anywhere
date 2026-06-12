# AGENTS.md

## Project overview

Single-script Linux voice dictation daemon. Hold a hotkey, speak, release — text appears wherever the cursor is. Uses `faster-whisper` for transcription, `parec` for audio capture, `ydotool` for keystroke injection, and `evdev` for keyboard event reading.

## No build system, no tests, no CI

- There is no `pyproject.toml`, `requirements.txt`, `Makefile`, or CI pipeline.
- Do **not** add a package manager, build system, or test framework unless the user asks.
- There are no automated tests. Manual testing only: run `whisper-anywhere`, hold the hotkey, speak, verify text appears.

## External Python packages

- `evdev` — comes from the system package `python3-evdev` (apt). Must use apt because evdev needs to access `/dev/input/` devices.
- `faster-whisper` — installed via `pip3 install --user faster-whisper` (PyPI). Provides CTranslate2-accelerated transcription.

## The script file *is* the daemon

- `whisper-anywhere` (no `.py` extension) is the entire application. It is installed as an executable in `~/.local/bin/`.
- Shebang: `#!/usr/bin/python3`

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

## Script architecture

- `find_keyboard()` — scans `/dev/input/` for a keyboard device via evdev, skips ydotoold/lid/power/sleep/video
- `check_deps()` — verifies `parec`, `ydotool` are on PATH and `evdev`/`faster_whisper` import works
- `load_model()` — initializes faster-whisper `WhisperModel` (auto-downloads from HuggingFace on first use)
- `write_wav()` — constructs a RIFF/WAV header and writes raw PCM data to a file
- `read_audio()` — async task that reads raw PCM chunks from `parec --raw` stdout until EOF
- `transcribe()` — sends SIGINT to `parec`, drains remaining audio via `read_audio`, writes WAV, runs model, types with `ydotool`
- `run_daemon()` — async evdev read loop; spawns `parec --raw` as an `asyncio.subprocess` on hotkey press, pipes audio through `read_audio` into a `bytearray` buffer, calls `transcribe()` on release
- Audio capture uses a pipe (`parec --raw` to `asyncio.subprocess.PIPE`) instead of a file — when `parec` stops (SIGINT), Python drains the pipe to EOF, capturing every last buffered sample without artificial timeouts
- Two hotkey modes: combo (Ctrl+Super+Space, all three must be held) or single-key (any `KEY_*` from `linux/input-event-codes.h`)
- Hotkey priority: CLI `--hotkey` > config file `hotkey=` > default combo
- Model priority: CLI `--model` > config file `model=` > `distil-large-v3`
