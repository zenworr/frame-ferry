.DEFAULT_GOAL := check
.PHONY: check check-tools check-player-tools dev-setup lint format syntax dependency-check audit test test-player test-slow install doctor

PYTHON ?= python3
DEV_BIN := .venv/bin
PYTHON_SOURCES := scripts tests
PYTHON_ENTRYPOINTS := scripts/frameferry-native scripts/setup-frameferry scripts/doctor scripts/yt-dlp-mpv scripts/yt-dlp-update-background

# Network access is limited to these explicit setup and audit targets.
dev-setup:
	$(PYTHON) -m venv .venv
	$(DEV_BIN)/python -m pip install --require-hashes -r requirements-dev.txt
	npm ci --ignore-scripts

check: lint syntax dependency-check test

check-tools:
	@for tool in $(PYTHON) node npm lua luac luacheck bash curl patch cmp; do \
		command -v "$$tool" >/dev/null || { echo "Missing $$tool. See docs/development.md." >&2; exit 1; }; \
	done
	@test -x $(DEV_BIN)/ruff -a -x $(DEV_BIN)/shellcheck -a -d node_modules || \
		{ echo 'Run make dev-setup before make check.' >&2; exit 1; }

check-player-tools:
	@for tool in $(PYTHON) mpv ffmpeg openssl; do \
		command -v "$$tool" >/dev/null || { echo "Missing $$tool. See docs/development.md." >&2; exit 1; }; \
	done
	@PYTHONPATH=scripts $(PYTHON) -c "from frameferry_config import DEFAULTS, supported_executable; supported_executable(DEFAULTS, 'mpv')"

lint: check-tools
	$(DEV_BIN)/ruff check $(PYTHON_SOURCES)
	$(DEV_BIN)/ruff format --check $(PYTHON_SOURCES)
	npm run lint
	npm run format:check
	$(DEV_BIN)/shellcheck scripts/*.sh scripts/lib/*.sh
	luacheck config/mpv/scripts tests

format:
	$(DEV_BIN)/ruff format $(PYTHON_SOURCES)
	$(DEV_BIN)/ruff check --fix $(PYTHON_SOURCES)
	npm run format

syntax: check-tools
	$(PYTHON) -m py_compile scripts/*.py $(PYTHON_ENTRYPOINTS)
	@for file in extension/*.js tests/*.mjs; do node --check "$$file" || exit; done
	@for file in scripts/*.sh scripts/lib/*.sh; do bash -n "$$file" || exit; done
	@for file in config/mpv/scripts/*.lua tests/*.lua; do luac -p "$$file" || exit; done

dependency-check: check-tools
	$(DEV_BIN)/python scripts/check_dev_dependencies.py
	$(DEV_BIN)/python -m pip check
	npm ls --all >/dev/null

audit:
	$(DEV_BIN)/pip-audit --strict --require-hashes --disable-pip -r requirements-dev.txt
	npm run audit

test:
	FRAME_FERRY_PLAYER_TESTS=0 $(PYTHON) -m unittest discover -s tests -t . -v
	@for file in tests/test_*.lua; do lua "$$file" || exit; done

test-player: check-player-tools
	FRAME_FERRY_PLAYER_TESTS=1 $(PYTHON) -m unittest discover -s tests -t . -v

test-slow: check-player-tools
	FRAME_FERRY_PLAYER_TESTS=1 MPV_SLOW_TESTS=1 $(PYTHON) -m unittest discover -s tests -t . -p test_mpv.py -v

install:
	./scripts/install.sh

doctor:
	$(PYTHON) scripts/doctor
