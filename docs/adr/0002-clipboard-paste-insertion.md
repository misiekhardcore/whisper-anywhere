# ADR 0002 - Insert transcripts through the clipboard and a paste chord

- Status: accepted, not yet implemented
- Date: 2026-11-22

## Context

Text was delivered by `ydotool type`, which injects one synthetic key event per
character, and the probe preferred `wtype`. Long dictations therefore produced
hundreds of key events in the focused application. Terminals and Electron apps
handle that stream inconsistently, and slow injection looks like dropped input.

## Decision

Insertion writes the transcript to the system clipboard and sends one paste chord.
The clipboard path is preferred; character typing through `ydotool` or `wtype`
remains only as a fallback when no clipboard tool or no chord injector is available.

Rules:

- Clipboard backends: `wl-copy`/`wl-paste` under a Wayland session, `xclip` under X11.
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
- Terminal-aware pasting is blind on GNOME and KDE, which expose no focused-window
  query; those users get Ctrl+V.

## Alternatives rejected

- **Keystroke typing only.** The behaviour this ADR removes.
- **Restoring the clipboard after every paste.** More clipboard churn for a single
  insertion per dictation.
- **Leaving the transcript on the clipboard always.** Destroys the user's clipboard
  for every dictation.
