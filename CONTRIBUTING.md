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

The daemon is a Python package with runtime dependencies `python3-evdev` (apt) and `faster-whisper` (pip). System dependencies (`ydotool`, `pulseaudio-utils`) are installed by `install.sh`.

## Development commands

```bash
make install-deps   # install test/build dependencies
make test           # run pytest suite
make build          # build sdist + wheel
make clean          # remove build artifacts
```

## Testing

Run the unit tests:

```bash
make test
```

For manual testing:

```bash
whisper-anywhere
```

Hold the hotkey, speak, release, verify text appears in the focused window.
