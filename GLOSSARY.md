# Glossary

Vocabulary for the dictation and insertion design recorded in `docs/adr/`. The
entries describe behaviour the code implements: a dictation is transcribed once,
before anything is inserted, and insertion never mutates text already in the
focused application.

- **Dictation** - one complete user action: hotkey press, speech, hotkey release.
  A dictation produces at most one transcript.
- **Recording** - the audio captured during a dictation, held in memory as raw
  16 kHz mono s16le PCM and written to a WAV file only for transcription.
- **Transcript** - the text the engine returns for a recording. It is final: the
  daemon never revises text after insertion.
- **Insertion** - delivering a transcript to the focused application. Two kinds
  exist: clipboard insertion and typing insertion.
- **Clipboard insertion** - writing the transcript to the system clipboard and
  sending a paste chord. The preferred path.
- **Typing insertion** - injecting one key event per character through `ydotool`
  or `wtype`. Fallback used only when clipboard insertion is unavailable.
- **Clipboard snapshot** - the clipboard text read before a clipboard insertion,
  written back afterwards so the user keeps their clipboard.
- **Paste chord** - the key combination that pastes: Ctrl+V, or Ctrl+Shift+V in a
  terminal window.
- **Terminal window** - a focused window identified as a terminal emulator, where
  the paste chord is Ctrl+Shift+V. Detected through `hyprctl` or `swaymsg`; other
  compositors yield an unknown result and get Ctrl+V.
- **Engine** - a transcription backend implementing `Transcriber`
  (SenseVoice, faster-whisper, Vosk).
- **Runtime directory** - the private directory holding the lock and the
  temporary audio file, defined by `Config.runtime_dir()`.
