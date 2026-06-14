.PHONY: test test-e2e install install-deps clean build lint format check

PYTHON ?= $(shell which python3)
PYTEST ?= $(PYTHON) -m pytest

test:
	$(PYTEST) -v tests/

test-e2e:
	WHISPER_E2E=1 $(PYTEST) -m integration -v tests/

install:
	$(PYTHON) -m pip install --user -e . 2>/dev/null \
		|| $(PYTHON) -m pip install --user --break-system-packages -e .

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
