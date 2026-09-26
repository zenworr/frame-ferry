# SPDX-License-Identifier: MIT
"""Shared installation paths, identity, and atomic file replacement."""

import base64
import hashlib
import json
from pathlib import Path
import tempfile

BROWSERS = {'helium': 'net.imput.helium', 'chromium': 'chromium', 'chrome': 'google-chrome',
            'brave': 'BraveSoftware/Brave-Browser'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extension_id(manifest):
    key = json.loads(manifest.read_text())['key']
    value = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(char, 16)) for char in value)


def atomic_write(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(content)
            output.flush()
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
