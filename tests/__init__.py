"""Offline tests for the extension, native tools, and player scripts."""

import sys
from pathlib import Path

# Native entry points import shared modules from their installation directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
