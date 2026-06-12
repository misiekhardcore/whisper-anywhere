# Contributing

## How to contribute

- **Issues**: Open a GitHub issue for bugs, feature requests, or questions.
- **PRs**: Fork the repo, create a feature branch, and open a pull request.
- **Code style**: Follow the existing style — keep scripts simple, no unnecessary dependencies.

## Development setup

```bash
git clone <your-fork>
cd whisper-anywhere
./install.sh
```

The daemon runs as a single Python script with Python dependencies `python3-evdev` (apt) and `faster-whisper` (pip). System dependencies (`ydotool`, `pulseaudio-utils`) are installed by `install.sh`.

## Testing

Test the daemon manually:

```bash
whisper-anywhere
```

Hold the hotkey, speak, release, verify text appears in the focused window.
