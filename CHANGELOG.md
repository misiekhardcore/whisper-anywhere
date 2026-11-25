# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The tray menu has a "Start at login" item that reads the two user units whenever the menu opens and enables or disables them

### Changed

- A dictation is transcribed once, over the whole hotkey hold, and inserted once; the streaming mode that retyped text while you were still speaking is gone
- `--stdout` prints exactly one `{"type": "final", "text": ...}` line per dictation. This is a breaking change for line consumers: the `{"type": "partial", ...}` lines no longer exist, so react to final lines only
- The dependency check requires `funasr` only for the SenseVoice engine
- Insertion writes the transcript to the clipboard and sends one paste chord (Ctrl+V through `ydotool`, or `wtype` when `ydotool` is absent) instead of typing every character, and it is the only mechanism: a missing clipboard backend or chord injector now stops startup with the package to install
- The transcript is left on the clipboard after a successful paste
- The dependency check and installer name the clipboard backend and chord injector
- `install.sh` installs the Python stack of the configured engine only, and pre-loads the SenseVoice model only for the SenseVoice engine; `ENGINE` picks the engine for a fresh install

### Removed

- The streaming transcription mode, its speech-detection model, the `--vad` flag, and the `vad_engine` / `vad` configuration keys. Config files that still contain those keys keep starting; they are ignored
- Backspacing and retyping already-inserted text, which the `Typer` implementations no longer offer
- The `wtype` compositor probe that injected a stray Ctrl keystroke into the focused window at startup; tool presence and session type now decide insertion
- Typing insertion (`ydotool type` / `wtype` text) and its `TypingInserter`; the transcript is always pasted, never typed

### Fixed

- `install.sh` performs the editable install from the primary worktree, so the console scripts cannot end up importing a worktree that is later removed
- `install.sh` checks that the package it installed imports from outside the source tree, and fails instead of reporting success when it does not
- `install.sh` asks `dpkg` first, so it skips apt and the privilege prompt when every system package is already present
- The installer summary reports the hotkey from the config instead of always claiming the default combo
- `--stdout` is honoured when passed as a flag again; the mode check used to treat the boolean flag as one of the `1`/`true`/`yes` config strings

## [1.1.3] - 2026-10-13

### Fixed

- Add missing pyav19 package install

## [1.1.2] - 2026-10-13

### Changed

- Cleanup

### Fixed

- Add missing pytorch package install

## [1.1.1] - 2026-06-16

### Fixed

- Prefer YdotoolTyper over ClipboardTyper in probe order

## [1.1.0] - 2026-06-15

### Changed

- Add --version CLI flag
- Refactor transcribe/ and vad/ into sub-packages, config/keyboard into classes
- Abstract text typing into Typer interface with WtypeTyper and YdotoolTyper
- Release v1.0.0

## [1.0.0] - 2026-06-15

### Added

- Systemd user service autostart + uninstall script + doc fixes
- Configurable transcription language

### Changed

- Add release workflow, CHANGELOG, and make bump target
- Drop Python 3.9 support, require >=3.10
- Add Vosk as a transcription engine
- Add pre-commit hooks for linting and tests
- Split **main**.py into focused modules
- Only backspace and retype the changed suffix in partial/final updates
- Live streaming mode with VAD-gated phrase transcription
- Formal Transcriber Protocol + extensible engine registry
- Add FunASR/SenseVoice as alternative batch transcription engine
- Prevent multiple daemon instances with flock-based lock
- 1.0.0 → 1.1.0
- --stdout output mode, distil-medium.en default, refactor transcribe()
- Bridge system dist-packages for non-system Python
- Restructure project into Python package with modules
- Send SIGINT to parec instead of SIGTERM so it finalizes WAV file properly
- Replace whisper.cpp with faster-whisper (distil-large-v3)
- Remove fragile evdev grab — combo mode works without intercept
- Initial commit

### Documentation

- Document VAD/live mode in README and install.sh
- Add opencode plugin npm install reference to README

### Fixed

- Document SenseVoice language limitation, warn at runtime, smart faster-whisper multilingual default
- Enable ITN in SenseVoice transcriber for improved output
- Prefer physical keyboards over virtual devices; surface parec errors
- Skip ydotool virtual device in find_keyboard
- Harden daemon runtime (safe paths, ydotool errors, hotplug, max-recording)
- Lower requires-python to >=3.9 so it installs on current distros
- Guard against empty buffers and partial samples in WAV writing

### Infrastructure

- Build the package across the Python version matrix

### Testing

- End-to-end dictation pipeline test

## [0.1.0] - 2026-06-11

### Changed

- Initial commit
