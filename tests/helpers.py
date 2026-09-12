"""Offline fixtures shared by the Python tests."""

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / 'scripts' / name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('condition did not become true before the deadline')


def running(pid):
    try:
        return not Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].startswith('Z')
    except FileNotFoundError:
        return False


class ExtractorFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = self.home / '.local/state/frameferry'
        self.state.mkdir(parents=True)
        (self.state / 'yt-dlp-update.lock').write_text(str(time.time() + 86400))
        self.fake = self.home / 'yt-dlp'
        self.fake.write_text(f'#!{sys.executable}\n' + '''import json, os, subprocess, sys, time
from pathlib import Path
home = Path.home()
with (home / 'calls').open('a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
if '-U' in sys.argv:
    if os.environ.get('FAKE_UPDATE_WAIT'):
        (home / 'update-ready').touch()
        end = time.monotonic() + 5
        while not (home / 'update-release').exists() and time.monotonic() < end:
            time.sleep(.01)
    sys.exit(int(os.environ.get('FAKE_UPDATE_STATUS', '0')))
if os.environ.get('FAKE_PID'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    (home / 'pids').write_text(f'{os.getpid()} {child.pid}')
    time.sleep(30)
if os.environ.get('FAKE_FAIL'):
    print('This live event has ended', file=sys.stderr)
    sys.exit(1)
info = {'id':'test', 'title':'test', 'url':'https://example.test/video'}
info.update(json.loads(os.environ.get('FAKE_INFO', '{}')))
print(json.dumps(info))
''')
        self.fake.chmod(0o755)
        (self.home / 'deno').symlink_to(sys.executable)
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_STATE_HOME': str(self.home / '.local/state'),
                    'XDG_DATA_HOME': str(self.home / '.local/share'), 'XDG_CONFIG_HOME': str(self.home / '.config'),
                    'PATH': str(self.home) + os.pathsep + os.environ['PATH']}
        self.addCleanup(self.stop_fixture)

    def stop_fixture(self):
        (self.home / 'update-release').touch()
        pids = self.home / 'pids'
        if pids.exists():
            for pid in map(int, pids.read_text().split()):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def calls(self):
        import json
        path = self.home / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run_wrapper(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/yt-dlp-mpv'), *args],
                              capture_output=True, env=self.env, timeout=5)

    def install_provider(self):
        provider = self.home / '.local/share/frameferry/bgutil'
        (provider / 'server/build').mkdir(parents=True)
        (provider / 'server/build/generate_once.js').touch()
        return provider
