.PHONY: test test-e2e install install-pkg install-deps clean build lint format check dev bump changelog precommit precommit-install

PYTHON ?= $(shell which python3)
PYTEST ?= $(PYTHON) -m pytest

test:
	$(PYTEST) -v tests/

test-e2e:
	WHISPER_E2E=1 $(PYTEST) -m integration -v tests/

install:
	$(PYTHON) -m pip install --user -e . 2>/dev/null \
		|| $(PYTHON) -m pip install --user --break-system-packages -e .

install-pkg:
	$(PYTHON) -m pip install -e .

install-deps:
	$(PYTHON) -m pip install --user evdev pytest pytest-asyncio build ruff numpy 2>/dev/null; \
	$(PYTHON) -m pip install --user --break-system-packages evdev pytest pytest-asyncio build ruff numpy 2>/dev/null || true

build: install-deps
	$(PYTHON) -m build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .pytest_cache dist *.egg-info

lint:
	ruff check .

format:
	ruff format .

check:
	ruff format --check .
	ruff check .

dev:
	$(PYTHON) -m whisper_anywhere $(ARGS)

bump:
	sed -i "s/^version = \".*\"/version = \"$(VERSION)\"/" pyproject.toml
	@echo "Version bumped to $(VERSION)"

changelog:
	sed -i '/^## \[Unreleased\]/,/^## \[/{/^## \[Unreleased\]/d;/^## \[/!d}' CHANGELOG.md
	git cliff --unreleased --prepend CHANGELOG.md

precommit: check
	$(PYTEST) -v tests/

precommit-install:
	pre-commit install
