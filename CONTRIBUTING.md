# Contributing

## How to contribute

- **Issues**: Open a GitHub issue for bugs, feature requests, or questions.
- **PRs**: Fork the repo, create a feature branch, and open a pull request.
- **Code style**: Follow the existing style — keep scripts simple, no unnecessary dependencies.

## Development setup

```bash
git clone <your-fork>
cd whisper-anywhere
make dev-setup
```

`make dev-setup` creates `.venv` (gitignored) and installs the package with its
development extras. The venv is built with `--system-site-packages` from a Python
that can import the distro `evdev`, so a Homebrew or otherwise mismatched Python is
skipped. Every development target provisions the same venv on first use, so
`make test` also works from a fresh checkout.

System dependencies come from apt (`python3-evdev`, `pulseaudio-utils`, `ydotool`,
and `wl-clipboard` on Wayland); `install.sh` installs them and sets up the systemd
service for running the daemon, which development does not need.

## Development commands

```bash
make dev-setup      # create/repair the development venv
make test           # run pytest suite
make lint           # ruff check
make format         # ruff format
make build          # build sdist + wheel
make clean          # remove build artifacts
make dev ARGS="--hotkey KEY_F12"   # run the daemon from the working tree
```

Targets use `.venv` once it exists; override the interpreter with
`make test PYTHON=/usr/bin/python3` when needed.

## Testing

Run the unit tests:

```bash
make test
```

For manual testing:

```bash
make dev ARGS="--hotkey KEY_F12"
```

Hold the hotkey, speak, release, verify text appears in the focused window.
