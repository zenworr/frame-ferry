"""Offline tests for the extension, native tools, and player scripts."""

import os
import shutil
import sys
import unittest
from pathlib import Path

# Native entry points import shared modules from their installation directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def player_tests(group='player'):
    def mark(test):
        test.suite_group = group
        return unittest.skipUnless(
            os.environ.get('FRAME_FERRY_PLAYER_TESTS') == '1' and shutil.which('mpv'),
            f'run make test-{group} for these mpv tests',
        )(test)

    return mark
