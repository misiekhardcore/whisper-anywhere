# Glossary

Vocabulary for the dictation, insertion and tray design recorded in `docs/adr/`.
The entries describe behaviour the code implements: a dictation is transcribed
once, before anything is inserted, insertion never mutates text already in the
focused application, and the tray only observes the daemon.

- **Dictation** - one complete user action: hotkey press, speech, hotkey release.
  A dictation produces at most one transcript.
- **Recording** - the audio captured during a dictation, held in memory as raw
  16 kHz mono s16le PCM and written to a WAV file only for transcription.
- **Transcript** - the text the engine returns for a recording. It is final: the
  daemon never revises text after insertion.
- **Insertion** - delivering a transcript to the focused application. Two kinds
  exist: clipboard insertion and typing insertion.
- **Clipboard insertion** - writing the transcript to the system clipboard and
  sending a paste chord. The preferred path, chosen once at startup.
- **Clipboard backend** - the tool that reads and writes the clipboard. On a Wayland
  session the backend is `wl-copy`/`wl-paste` from wl-clipboard.
- **Chord injector** - the tool that sends the paste chord: `ydotool`, or `wtype`
  when `ydotool` is absent.
- **Typing insertion** - injecting one key event per character through `ydotool`
  or `wtype`. Fallback used only when clipboard insertion is unavailable.
- **Paste chord** - the key combination that pastes: Ctrl+V, or Ctrl+Shift+V when
  the focused window is a terminal.
- **Focused-window query** - the best-effort `hyprctl` / `swaymsg` question that
  decides whether the focused window is a terminal. Unknown reads as not a terminal.
- **Engine** - a transcription backend implementing `Transcriber`
  (SenseVoice, faster-whisper, Vosk).
- **Runtime directory** - the private directory holding the lock, the status
  socket and the temporary audio file, defined by `Config.runtime_dir()`.
- **Tray indicator** - `whisper-anywhere-tray`, a separate process that renders
  one AppIndicator icon and a menu. It never captures audio or reads the keyboard.
- **Daemon state** - what the daemon is doing, one of `loading`, `idle`,
  `recording` or `processing`. It is published on the status socket and shown by
  the tray.
- **Status socket** - the Unix socket at `state.sock` in the runtime directory.
  The daemon pushes each state change to connected clients and accepts the single
  `quit` command.
- **Appearance** - the icon and status text a state maps to: dimmed for loading
  and for an absent daemon, neutral for idle, red for recording, green for
  processing.
- **Failure note** - the sticky `Last dictation failed` text in the menu status
  line, set when a decode or insertion fails and cleared when the next dictation
  starts. A silent or blank dictation is not a failure and sets no note.
- **Start at login** - the tray menu toggle that enables or disables both systemd
  user units. It changes login autostart only, never what is running now.
- **Launcher entry** - the desktop entry installed in
  `~/.local/share/applications` that starts both units through `systemctl --user`.
