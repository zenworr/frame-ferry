.DEFAULT_GOAL := check
.PHONY: check syntax test test-slow install doctor

PYTHON ?= python3

check: syntax test

syntax:
	@if command -v node >/dev/null; then for file in extension/*.js tests/*.mjs; do node --check "$$file" || exit; done; fi
	@for file in scripts/*.sh scripts/lib/*.sh; do bash -n "$$file" || exit; done
	@for file in config/mpv/scripts/*.lua tests/*.lua; do luac -p "$$file" || exit; done

test:
	$(PYTHON) -m unittest discover -s tests -v
	@for file in tests/test_*.lua; do lua "$$file" || exit; done

test-slow:
	MPV_SLOW_TESTS=1 $(PYTHON) -m unittest discover -s tests -p test_mpv.py -v

install:
	./scripts/install.sh

doctor:
	$(PYTHON) scripts/doctor
