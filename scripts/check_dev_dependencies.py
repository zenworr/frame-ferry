#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that installed Python tools match their declared pins and lock file."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    locked = (ROOT / 'requirements-dev.txt').read_text().splitlines()
    for line in (ROOT / 'requirements-dev.in').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name, expected = line.split('==')
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = None
        if installed != expected or not any(entry.startswith(line + ' ') for entry in locked):
            print(f'{name}: expected {expected}. Update the lock file and run make dev-setup.')
            return 1
    print('Python development dependencies match the declared pins and lock file.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
