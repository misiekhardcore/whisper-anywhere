# ADR 0003 - A tray indicator reports dictation state

- Status: accepted, implemented
- Date: 2026-11-22

## Context

The daemon is invisible. The only feedback that a dictation started, finished or
failed is in journald, and a silent recording, a failed decode and a failed
insertion all end the same way: no text, no signal. The user has no way to tell
"still transcribing" from "your hotkey never registered".

Two constraints shaped the design. First, the installed unit is
`WantedBy=default.target`, so the daemon may start before a display exists, and
input capture and audio must not depend on a GUI. Second, on Wayland the only
icon mechanism that works is a StatusNotifierItem (AppIndicator), which is
driven by a GTK main loop and is effectively menu-based.

## Decision

A separate process, `whisper-anywhere-tray`, renders one AppIndicator icon and a
small menu. The daemon never imports GTK and never knows the tray exists.

### Process split

- The tray is its own console script and its own systemd user unit,
  `WantedBy=graphical-session.target` and `Restart=no`. A missing display or a
  missing AppIndicator host stops the icon, never dictation; without
  `Restart=no` a headless session would restart-storm.
- **Rejected: in-process tray.** GTK must own the process main thread, which the
  `asyncio` daemon loop owns today, and a GTK or display failure would become a
  dictation failure.

### Status socket

The daemon publishes state on a Unix socket at
`Config.runtime_dir()/state.sock`, in the same 0700 directory as the lock and
the temporary audio file. It is served from the existing asyncio loop, accepted
connections receive a snapshot, and every transition is pushed to all connected
clients. Clients send one command, `quit`.

- Latency is a socket push, not a poll: the tray repaints from the value that
  arrives, which is far below the panel's own frame interval.
- **Rejected: a state file watched with inotify.** Push-shaped at best and
  poll-shaped at worst, and Quit still needs a second channel.
- **Rejected: a D-Bus service on the session bus.** Adds a bus library plus a
  reconnect path for a private, single-user, same-directory channel.
- The socket is bound **before** the engine loads, so the loading state is
  observable; a stale socket left by a crash is unlinked and rebound, which the
  single-instance lock already guarantees is safe.

### States and appearance

Payload is one newline-terminated JSON object per update:

```json
{"state": "processing", "note": null}
```

| State        | Icon                    | Status line                 |
| ------------ | ----------------------- | --------------------------- |
| `loading`    | dimmed microphone       | Starting                    |
| `idle`       | neutral microphone      | Idle                        |
| `recording`  | red microphone          | Recording                   |
| `processing` | green microphone        | Processing                  |
| no daemon    | dimmed microphone       | daemon stopped              |

- A dictation moves `recording` -> `processing` -> `idle`. `processing` covers the
  engine call only: it begins on hotkey release and ends when the transcript
  exists.
- Because `processing` excludes insertion, an insertion failure is never a
  colour. Failures from the decode or the insertion set a **failure note**,
  `Last dictation failed`, in the status line, kept until the next dictation
  starts.
- A silent recording or a blank transcript is not a failure. Nothing was said,
  so the tray returns to `idle` with no note.
- There is no minimum display time for `processing`, so a fast decode may blink
  the green icon. Accepted: honest timing over a padded animation.
- "Loading model" and "daemon not running" share the dimmed icon and differ in
  the status line, because one glyph cannot honestly encode both.

### Menu

- A disabled status line, mirroring the table above plus the failure note.
- **Start at login**, checkable: runs `systemctl --user enable` or `disable` for
  both units and reflects `is-enabled` when the menu opens. It changes login
  autostart only, never the running state, so toggling it cannot stop a daemon
  mid-dictation. Hidden when `systemctl --user is-enabled` cannot be read.
- **Quit whisper anywhere**: sends `quit` on the socket, then exits. Stopping
  the daemon leaves the tray showing "daemon stopped" until it exits too. Quit
  during a recording discards that recording and exits immediately.
- No Start/Stop daemon item. The daemon is restarted from the launcher entry or
  a terminal, which keeps the tray a viewer of state rather than a second process
  manager that can disagree with systemd.

### Installation

- `install.sh` adds `python3-gi` and `gir1.2-ayatanaappindicator3-0.1` to its apt
  step; the existing system dist-packages bridge already makes `gi` importable
  from the interpreter that runs the daemon.
- Both units are written. The tray unit starts with the graphical session; the
  daemon unit keeps its current shape.
- A launcher entry in `~/.local/share/applications` runs
  `systemctl --user start` for both units, so the launcher, login autostart and
  the tray all pass through one supervisor; each unit keeps its own journald log.
  The entry is searchable by keywords and installs its own icon into the user's
  hicolor theme, so the menu shows the same microphone as the tray instead of a
  generic system icon.
- Autostart is enabled by default: `install.sh` asks on a TTY and honours
  `AUTOSTART=0|1` when it is not interactive. `uninstall.sh` removes the
  launcher entry, both units and the socket.

### Tray without a host

GNOME needs the AppIndicator extension to host an item, and bare sway has no host
at all. When no `StatusNotifierWatcher` is on the session bus the tray logs one
journald line naming the missing host and retries registration periodically, so
an extension installed later starts working without a restart.

### Icons

The PNGs are generated by a committed, dev-only script (Pillow, a development
dependency) and shipped as package data: four panel states (neutral, red, green,
dimmed) plus one launcher icon at 48, 64, 128 and 256 px. The neutral glyph is
drawn to read on both light and dark panels rather than shipping per-theme
variants.

### Test seams

- The appearance mapping is a pure function from state and note to icon and
  status text, tested without GTK.
- The daemon takes a state publisher behind a protocol, faked in the daemon and
  recorder tests to assert the transition order, the failure note and that a
  silent recording produces no note.
- The socket is tested against a real server on a temporary path: snapshot on
  connect, push on transition, `quit` shutting the daemon down.
- The tray's systemd actions run through an injectable command runner, so the
  enable/disable argv is asserted without touching the user's units.
- The installer tests assert the launcher entry, both units, the new apt
  packages and their removal by `uninstall.sh`.

## Consequences

- One more process, one more unit, one more launcher entry, and a socket in the
  runtime directory.
- Daemon and tray speak an unversioned protocol. They ship together, so a
  mismatch shows up as a reconnect loop rather than a negotiated error.
- Quit stops everything, so restarting means the launcher or a terminal.
- The icon is informational only: nothing in the tray can repair a failed
  insertion, which remains a journald diagnosis.
- Coloured icons are unusual for a panel; on a host that renders indicators
  monochrome the states would be indistinguishable, and only the status line
  would carry the state.

## Alternatives rejected

- **No indicator.** The current state: failures and stalls are invisible.
- **A desktop notification per dictation.** Interrupts typing and duplicates the
  transcript.
- **An icon that also acts as the microphone toggle.** Dictation is hold-to-talk;
  a click-toggle would be a second input path to design and test.
