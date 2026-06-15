# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Changed

- Add release workflow, CHANGELOG, and make bump target
## [1.1.0] - 2026-06-15
### Added

- Systemd user service autostart + uninstall script + doc fixes
- Configurable transcription language

### Changed

- Drop Python 3.9 support, require >=3.10
- Add Vosk as a transcription engine
- Add pre-commit hooks for linting and tests
- Split __main__.py into focused modules
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
## [1.0.0] - 2026-06-11
### Changed

- Initial commit
