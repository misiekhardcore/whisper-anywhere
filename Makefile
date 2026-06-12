.PHONY: test install install-deps clean build

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest

test:
	PYTHONPATH="/usr/lib/python3/dist-packages:$$PYTHONPATH" $(PYTEST) -v tests/

install:
	pip3 install --user -e . 2>/dev/null \
		|| pip3 install --user --break-system-packages -e .

install-deps:
	$(PYTHON) -m pip install --user pytest pytest-asyncio build 2>/dev/null \
		|| $(PYTHON) -m pip install --user --break-system-packages pytest pytest-asyncio build

build: install-deps
	$(PYTHON) -m build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .pytest_cache dist *.egg-info
