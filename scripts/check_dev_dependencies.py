#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that installed Python tools match their declared pins and lock file."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def main():
    locked = [
        Requirement(line.removesuffix(' \\'))
        for line in (ROOT / 'requirements-dev.txt').read_text().splitlines()
        if line and not line.startswith(('#', ' '))
    ]
    active_locks = {(entry.name, entry.specifier) for entry in locked if not entry.marker or entry.marker.evaluate()}
    for line in (ROOT / 'requirements-dev.in').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        pin = Requirement(line)
        if pin.marker and not pin.marker.evaluate():
            continue
        try:
            installed = version(pin.name)
        except PackageNotFoundError:
            installed = None
        if installed is None or installed not in pin.specifier or (pin.name, pin.specifier) not in active_locks:
            print(f'{pin.name}: expected {pin.specifier}. Update the lock file and run make dev-setup.')
            return 1
    print('Python development dependencies match the declared pins and lock file.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
