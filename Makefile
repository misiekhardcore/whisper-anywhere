.PHONY: test test-e2e install dev-setup clean build lint format check dev bump changelog precommit precommit-install

# Development runs inside .venv so pip never fights an externally-managed or
# Homebrew Python. The venv must be created from an interpreter that can import
# the distro-built evdev: a Homebrew Python cannot, even at the same version.
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python3
DEV_STAMP := $(VENV)/.dev-ready

BASE_PYTHON := $(shell for candidate in python3 /usr/bin/python3; do \
	if command -v $$candidate >/dev/null 2>&1 && \
		$$candidate -c 'import sys, evdev; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then \
		echo $$candidate; break; \
	fi; \
done)
ifeq ($(strip $(BASE_PYTHON)),)
BASE_PYTHON := python3
endif

# Prefer the project venv, but fall back to a working system Python so the
# targets still run before `make dev-setup` has been called.
PYTHON ?= $(shell if test -x $(VENV_PYTHON) && \
	$(VENV_PYTHON) -c 'import evdev' >/dev/null 2>&1; then \
	echo $(VENV_PYTHON); else echo $(BASE_PYTHON); fi)
PYTEST ?= $(PYTHON) -m pytest

$(DEV_STAMP): pyproject.toml
	@if [ -x "$(VENV_PYTHON)" ] && ! "$(VENV_PYTHON)" -c 'import evdev' >/dev/null 2>&1; then \
		echo "Replacing $(VENV): its Python cannot import evdev"; \
		rm -rf "$(VENV)"; \
	fi
	@test -x "$(VENV_PYTHON)" || { \
		echo "Creating $(VENV) from $(BASE_PYTHON)"; \
		"$(BASE_PYTHON)" -m venv --system-site-packages "$(VENV)"; \
	}
	@"$(VENV_PYTHON)" -m pip install --quiet -e ".[dev]"
	@"$(VENV_PYTHON)" -c 'import evdev' || { \
		echo "evdev is not importable. Install it with: sudo apt install python3-evdev"; \
		exit 1; \
	}
	@touch $@

dev-setup: $(DEV_STAMP)
	@echo "Development environment ready. Activate it with: source $(VENV)/bin/activate"

test: $(DEV_STAMP)
	$(PYTEST) -v tests/

test-e2e: $(DEV_STAMP)
	WHISPER_E2E=1 $(PYTEST) -m integration -v tests/

install:
	$(BASE_PYTHON) -m pip install --user -e . 2>/dev/null \
		|| $(BASE_PYTHON) -m pip install --user --break-system-packages -e .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .pytest_cache dist *.egg-info

build: $(DEV_STAMP)
	$(PYTHON) -m build

lint: $(DEV_STAMP)
	$(PYTHON) -m ruff check .

format: $(DEV_STAMP)
	$(PYTHON) -m ruff format .

check: $(DEV_STAMP)
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .

dev: $(DEV_STAMP)
	$(PYTHON) -m whisper_anywhere $(ARGS)

bump:
	sed -i "s/^version = \".*\"/version = \"$(VERSION)\"/" pyproject.toml
	@echo "Version bumped to $(VERSION)"

changelog:
	sed -i '/^## \[Unreleased\]/,/^## \[/{/^## \[Unreleased\]/d;/^## \[/!d}' CHANGELOG.md
	git cliff --unreleased --prepend CHANGELOG.md

precommit: check
	$(PYTEST) -v tests/

precommit-install: $(DEV_STAMP)
	$(VENV_PYTHON) -m pre_commit install
