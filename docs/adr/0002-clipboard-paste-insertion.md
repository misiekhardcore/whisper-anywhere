# ADR 0002 - Insert transcripts through the clipboard and a paste chord

- Status: accepted, implemented
- Date: 2026-11-22

## Context

Text was delivered by `ydotool type`, which injects one synthetic key event per
character, and the probe preferred `wtype`. Long dictations therefore produced
hundreds of key events in the focused application. Terminals and Electron apps
handle that stream inconsistently, and slow injection looks like dropped input.

## Decision

Insertion writes the transcript to the system clipboard and sends one paste chord.
It is the only insertion mechanism: character typing one key event per character is
gone, so a session without a clipboard backend or without a chord injector gets an
actionable install message at startup instead of a degraded typed insertion.

Rules:

- Clipboard backends: `wl-copy`/`wl-paste` under a Wayland session, `xclip` under X11.
  The backend is chosen by session type, never by which tool is first on `PATH`, and
  a session type that is neither gets the Wayland backend.
- A clipboard read asks the backend what flavours the selection offers and reports
  no text unless one of them is text (`wl-paste --list-types` on Wayland,
  `xclip -t TARGETS -o` on X11).
- Paste chord: `ydotool key` with Ctrl+V, or Ctrl+Shift+V in a terminal window.
  `wtype` provides the chord only when `ydotool` is absent.
- The focused window's terminal-ness is detected through `hyprctl` or `swaymsg`.
  Compositors without an IPC query fall back to Ctrl+V.
- The previous clipboard text is snapshotted and written back once, after a delay,
  and only when the clipboard still holds the transcript. A clipboard holding
  non-text content cannot be snapshotted and is overwritten without restore.
- If the clipboard write or the chord fails, the transcript stays on the clipboard
  and the failure is reported on stderr.

## Consequences

- One paste event reaches the application instead of a keystroke stream.
- `Typer.backspace`, `emit_partial`, `emit_final` and the prefix diff go away;
  the `TextInserter` protocol is to have a single `insert_text` method.
- Insertion blocks for the clipboard settle and restore delays, so `TextOutput.emit`
  must become async and run the inserter in a worker thread to keep the evdev loop
  responsive.
- Clipboard restoration is best effort: an image or file on the clipboard is replaced.
- Typing insertion and the code that drove it are removed; a machine missing the
  clipboard backend or chord injector inserts nothing until the package is installed.
- Terminal-aware pasting is blind on GNOME and KDE, which expose no focused-window
  query; those users get Ctrl+V.

## Alternatives rejected

- **Keystroke typing only.** The behaviour this ADR removes.
- **Restoring the clipboard after every paste.** More clipboard churn for a single
  insertion per dictation.
- **Leaving the transcript on the clipboard always.** Destroys the user's clipboard
  for every dictation.
