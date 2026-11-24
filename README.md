# whisper-anywhere

Hold a hotkey, speak, release — text appears in the focused window.

Offline, local voice dictation for Linux using SenseVoice (FunASR) by default, with faster-whisper and Vosk as alternative engines. No cloud API, no data leaves your machine.

> **Language support**: SenseVoice supports explicit language codes `zh`, `en`, `yue`, `ja`, `ko` only (or `auto` for auto-detect). Other languages (e.g. Polish, German) are **not** supported with explicit codes — use the faster-whisper engine for non-English languages that aren't in SenseVoice's limited set.

## How it works

1. Hold a hotkey (default: `Ctrl+Super+Space`, configurable to a single key like `F12`)
2. Speak — audio is recorded via PulseAudio
3. Release — the engine transcribes the whole hold in one pass and the transcript is
   inserted once: written to the clipboard and pasted with a single Ctrl+V chord

A dictation produces at most one transcript, and the daemon never revises text after
it has been inserted. An empty hold, or a hold the engine hears as silence, produces
no text. Release-to-text latency is the transcription time of the whole recording,
which is why a single hold is capped at 60 seconds.

## Requirements

- **Ubuntu** (or Debian-based distro with `apt`)
- **PulseAudio or PipeWire** (for `parec`)
- **Python 3.10-3.14** with `python3-evdev` for keyboard access. The installer picks a
  supported interpreter automatically, so a newer `python3` on `PATH` (such as Homebrew
  3.15) is skipped; an explicit `PYTHON` is checked against the same range. Python 3.15
  is not supported yet because `torchaudio` has no 3.15 wheels.
- **A Wayland or X11 desktop** — `ydotool` injects keystrokes via the kernel `uinput`
  device, so it works under either (tested on GNOME and KDE Plasma)
- **`wl-clipboard`** (`wl-copy`/`wl-paste`) on Wayland, for the preferred clipboard
  insertion; without it the transcript is typed instead
- **GTK 3 and AppIndicator** (`python3-gi`, `gir1.2-ayatanaappindicator3-0.1`) for the
  tray indicator. GNOME also needs the AppIndicator extension to host it; without a
  host the tray logs why it is not showing and retries
- **systemd** (the daemon and the tray install as `systemd --user` services)

## Quick install

```bash
git clone https://github.com/misiekhardcore/whisper-anywhere
cd whisper-anywhere
bash install.sh
```

The installer installs only the Python stack the configured engine needs: it reads
`engine=` from `~/.config/whisper-anywhere/config` (SenseVoice when unset), so a
faster-whisper or Vosk setup never downloads PyTorch, and the SenseVoice model is
only pre-loaded for the SenseVoice engine. Pass `ENGINE=faster-whisper bash install.sh`
to choose it for a fresh install. System packages that are already present are left
alone, so a second run needs no password, and the run fails loudly when the package
it just installed cannot be imported outside the source tree.

Or manually, step by step. Use a supported interpreter (3.10-3.14) for the commands
below; if `python3` points at a newer version, substitute `python3.14` (or another
supported version).

```bash
# system dependencies
sudo apt install pulseaudio-utils python3-evdev python3-pip ydotool \
  python3-gi gir1.2-ayatanaappindicator3-0.1
# on Wayland, the clipboard backend used for insertion
sudo apt install wl-clipboard

# Python packages (default: sensevoice via funasr)
python3 -m pip install --user torch torchaudio \
  --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install --user funasr
# Optional: faster-whisper for alternative engine
python3 -m pip install --user faster-whisper 'av<19' \
  || python3 -m pip install --user --break-system-packages faster-whisper 'av<19'
# Optional: Vosk for lightweight multilingual transcription
python3 -m pip install --user vosk

# install whisper-anywhere itself
python3 -m pip install --user -e .

# input group for keyboard access
sudo usermod -a -G input $USER
# log out and back in

# ydotool daemon
systemctl --user enable --now ydotool.service
```

## Usage

`install.sh` installs two `systemd --user` units, `whisper-anywhere.service` (the
daemon) and `whisper-anywhere-tray.service` (the tray indicator), enables autostart,
starts both, and adds a searchable applications-menu launcher with its own icon
that starts both through `systemctl --user`. Autostart is on by default: the
installer asks one question on a terminal, and a scripted install honours
`AUTOSTART=0` or `AUTOSTART=1`. The tray follows the graphical session and never
restarts on its own, so a headless desktop cannot restart-storm it.

```bash
systemctl --user status whisper-anywhere whisper-anywhere-tray   # check they run
journalctl --user -u whisper-anywhere -f                          # daemon logs
journalctl --user -u whisper-anywhere-tray -f                     # tray logs
systemctl --user restart whisper-anywhere                         # apply config changes
systemctl --user start whisper-anywhere whisper-anywhere-tray     # start both
```

The launcher entry, login autostart and the tray all start through the same
systemd user manager, so they share one lifecycle; each unit keeps its own
journald log.

Or run it in the foreground (useful for debugging):

```bash
whisper-anywhere
```

Either way: hold the hotkey, speak, release. Text appears wherever your cursor is.

### Insertion

The transcript is written to the system clipboard and a single paste chord is sent,
so the focused application receives one paste instead of a keystroke stream. The
preferred path is `wl-copy`/`wl-paste` (Wayland) plus `ydotool` sending Ctrl+V;
`wtype` sends the chord only when `ydotool` is absent.

Dictating does not cost you your clipboard. The clipboard text you had before
dictating is restored after the paste lands, but only while the clipboard still
holds the transcript; if something else changed it in the meantime, the old text is
dropped instead of overwriting the new content. Clipboard content that is not text -
an image or a file list, for example - cannot be snapshotted, so the transcript
replaces it permanently. When the clipboard write fails no paste is sent, and when
the paste fails the transcript stays on the clipboard so you can paste it yourself.

When no clipboard backend is available, or the session is not Wayland, insertion
falls back to typing the transcript through `ydotool` (or `wtype`) and reports why.
The daemon prints the chosen insertion strategy on startup, and names the package to
install when a tool is missing.

### Configuration

Edit `~/.config/whisper-anywhere/config`, then `systemctl --user restart whisper-anywhere`:

```ini
# Single-key mode (F12 — no app conflicts)
hotkey=KEY_F12

# Or omit for Ctrl+Super+Space combo
# hotkey=

# Engine (sensevoice, faster-whisper, or vosk)
# engine=sensevoice

# Model name (default: iic/SenseVoiceSmall)
# model=iic/SenseVoiceSmall

# Force a language (e.g. zh, en, yue, ja, ko). SenseVoice supports
# only zh, en, yue, ja, ko — other codes are ignored (auto-detected).
# With faster-whisper, any ISO 639-1 code works.
# language=en
```

A configuration file written for an older release may still contain keys this version
no longer reads; they are ignored, so the daemon still starts.

### Command-line options

```bash
whisper-anywhere --hotkey KEY_F12       # single-key mode
whisper-anywhere --hotkey KEY_GRAVE     # use backtick key
whisper-anywhere --engine faster-whisper
whisper-anywhere --engine vosk
whisper-anywhere --model vosk-model-small-en-us-0.15
whisper-anywhere --model distil-small.en
whisper-anywhere --language en          # force language (SenseVoice: zh/en/yue/ja/ko; faster-whisper: any ISO 639-1; Vosk: any ISO 639-1)
whisper-anywhere --stdout               # JSON lines output (for opencode plugin)
```

### Stdout mode

`--stdout` (or `stdout=1` in the config file) prints exactly one JSON line per
dictation, shaped `{"type": "final", "text": "..."}`. A silent dictation prints
nothing. Earlier releases also printed lines for text that was still being spoken;
those are gone, so a consumer should treat every line as one finished transcript.

> **opencode plugin**: [whisper-anywhere-opencode](https://github.com/misiekhardcore/whisper-anywhere-opencode) integrates dictation into the opencode TUI. Install via `npm install -g whisper-anywhere-opencode` and add to `opencode.json`.

## Models

Downloaded automatically on first use. Default engine uses SenseVoice via [FunASR](https://github.com/modelscope/FunASR); alternative engines use [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [Vosk](https://alphacephei.com/vosk/).

### SenseVoice (default, `--engine sensevoice`)

| Model                 | Size    | Notes                                                                                                           |
| --------------------- | ------- | --------------------------------------------------------------------------------------------------------------- |
| `iic/SenseVoiceSmall` | ~120 MB | Default, MIT license, 15-17x faster than Whisper on CPU. **Explicit language codes**: zh, en, yue, ja, ko only. |

### faster-whisper (`--engine faster-whisper`)

| Model              | Size   | Quality | Language                                                        |
| ------------------ | ------ | ------- | --------------------------------------------------------------- |
| `distil-large-v3`  | 1.5 GB | Best    | Multilingual (default when a non-English language is requested) |
| `distil-medium.en` | 300 MB | Better  | English only                                                    |
| `distil-small.en`  | 94 MB  | Good    | English only                                                    |

Set via config or `--model`. When you request a non-English language without specifying a model, `distil-large-v3` is automatically selected.

### Vosk (`--engine vosk`)

| Model                         | Size   | Languages  |
| ----------------------------- | ------ | ---------- |
| `vosk-model-small-en-us-0.15` | ~40 MB | English    |
| `vosk-model-small-pl-0.22`    | ~50 MB | Polish     |
| `vosk-model-small-de-0.15`    | ~40 MB | German     |
| `vosk-model-small-fr-0.22`    | ~50 MB | French     |
| `vosk-model-small-es-0.22`    | ~50 MB | Spanish    |
| `vosk-model-small-pt-0.3`     | ~50 MB | Portuguese |
| `vosk-model-small-ru-0.22`    | ~50 MB | Russian    |
| `vosk-model-small-it-0.22`    | ~50 MB | Italian    |
| `vosk-model-small-nl-0.22`    | ~50 MB | Dutch      |
| `vosk-model-small-tr-0.3`     | ~50 MB | Turkish    |
| `vosk-model-small-vn-0.3`     | ~50 MB | Vietnamese |
| `vosk-model-small-ja-0.22`    | ~50 MB | Japanese   |
| `vosk-model-small-cn-0.22`    | ~50 MB | Chinese    |
| `vosk-model-small-hi-0.22`    | ~50 MB | Hindi      |
| `vosk-model-small-ar-0.22`    | ~40 MB | Arabic     |
| `vosk-model-small-fa-0.5`     | ~50 MB | Persian    |

Models are auto-downloaded on first use to `~/.cache/vosk/`. Set the language code (e.g. `pl`, `de`, `fr`) via `--language` or the config file to auto-select the matching model. Alternatively, specify any model name directly with `--model`.

> **Performance**: SenseVoiceSmall is 15-17x faster than Whisper on CPU (explicit codes: zh, en, yue, ja, ko). faster-whisper uses CTranslate2 with int8 quantization, typically 2-4x faster than whisper.cpp on CPU. Vosk is lightweight and efficient on CPU, with small model sizes suited for specific languages.

## Project layout

```
whisper-anywhere/
├── whisper_anywhere/    # Python package
│   ├── __init__.py
│   ├── __main__.py      # daemon entry point, config resolution
│   ├── audio.py         # audio capture and WAV writing
│   ├── config.py        # configuration and CLI args
│   ├── daemon.py        # main event loop, keyboard device handling
│   ├── keyboard.py      # evdev keyboard detection
│   ├── lock.py          # single-instance lock
│   ├── output.py        # text output (stdout / insertion)
│   ├── recording.py     # one recording and one transcription per dictation
│   ├── state.py         # daemon state and the status socket
│   ├── tray/            # separate tray process: appearance, socket client, GTK view
│   ├── transcribe/      # model loading and engine registry
│   └── insertion/       # clipboard backend, paste chord, clipboard and typing inserters
├── tests/               # pytest suite
├── install.sh           # one-shot installer
├── uninstall.sh         # reverses install.sh
├── Makefile             # development commands
├── pyproject.toml       # package metadata
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

## Uninstall

```bash
bash uninstall.sh
```

Removes both systemd user units, the applications-menu launcher and its icon, and
the status socket, uninstalls the pip package, and offers to delete your config.
The HuggingFace model cache, pip dependencies, and `input`-group membership are
left in place (the script prints how to remove them).

## License

MIT
