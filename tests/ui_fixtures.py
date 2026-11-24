import gzip
import subprocess

from .helpers import ROOT

# Pinned po5/thumbfast, MPL-2.0. Use gzip -n to preserve the exact source bytes.
THUMBFAST_UPSTREAM = ROOT / 'tests/fixtures/thumbfast.lua.gz'


def patched_thumbfast(directory):
    target = directory / 'thumbfast.lua'
    target.write_bytes(gzip.decompress(THUMBFAST_UPSTREAM.read_bytes()))
    subprocess.run(
        ['patch', '--batch', '--fuzz=0', '-s', '-p1', '-d', str(directory)],
        input=(ROOT / 'patches/thumbfast-low-resolution.patch').read_bytes(),
        check=True,
        capture_output=True,
        timeout=5,
    )
    return target
