import io
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from frameferry_config import DEFAULTS

from . import player_tests
from .helpers import ROOT, load_script, wait_for
from .mpv_harness import Player

native = load_script('frameferry-native')
BROWSER_REPLY = {'ok': True, 'outcome': 'browser', 'message': 'Return to the browser was requested in mpv.'}


def request(**changes):
    return {
        'version': 1,
        'action': 'play',
        'url': 'https://www.youtube.com/watch?v=fixture&t=99',
        'position': 30,
        'quality': 1080,
        'fullscreen': False,
        **changes,
    }


class NativeTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(native, 'load_config', return_value=dict(DEFAULTS))
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for extension tests')
    def test_extension_behavior(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/test_extension.mjs')], capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @player_tests()
    def test_real_native_handoff_starts_at_position_and_confirms_playback(self):
        player = Player(url=None)
        self.addCleanup(player.close)
        self.assertIsNone(player.process)
        config = player.root / 'native-config'
        config.mkdir()
        (config / 'mpv.conf').write_text('vo=null\nao=null\npause=yes\nkeep-open=yes\n')
        observed = []
        original = native.wait_for_playback

        def probe(process, path, deadline):
            self.addCleanup(process.wait, timeout=5)
            self.addCleanup(process.terminate)
            outcome = original(process, path, deadline)
            with socket.socket(socket.AF_UNIX) as ipc:
                ipc.connect(str(path))
                ipc.sendall(b'{"command":["get_property","time-pos"],"request_id":1}\n')
                with ipc.makefile('rb') as stream:
                    while True:
                        event = json.loads(stream.readline())
                        if event.get('request_id') == 1:
                            observed.append(event['data'])
                            break
            return outcome

        with (
            patch.object(native, 'CONFIG', config),
            patch.object(native, 'STATE', player.root / ('native-state-' + 'x' * 80)),
            patch.object(native, 'wait_for_playback', side_effect=probe),
        ):
            reply = native.handle(
                request(url=f'http://127.0.0.1:{player.server.server_port}/audio.wav', position=30.625, quality=0)
            )
        self.assertEqual(reply['outcome'], 'playing')
        self.assertAlmostEqual(observed[0], 30.625, delta=0.2)

    @player_tests()
    def test_browser_return_during_native_startup(self):
        for action in ('fast', 'slow', 'failed', 'quit'):
            with self.subTest(action=action):
                self.check_browser_return_during_startup(action)

    def check_browser_return_during_startup(self, action):
        player = Player(url=None)
        self.addCleanup(player.close)
        config = player.root / 'native-config'
        config.mkdir()
        (config / 'mpv.conf').write_text('vo=null\nao=null\nytdl=no\nload-scripts=no\n')
        guard = config / 'loopback.lua'
        guard.write_text(f"""mp.add_hook('on_load', 30, function()
    if not mp.get_property_bool('user-data/youtube-quality/slate') then
        mp.set_property('stream-open-filename', 'http://127.0.0.1:{player.server.server_port}/stall')
    end
end)
""")
        opener = player.root / 'xdg-open'
        started = player.root / 'opener-started'
        release = player.root / 'opener-release'
        wait = f'while [ ! -f "{release}" ]; do sleep 0.02; done\n' if action == 'slow' else ''
        opener.write_text(f'#!/bin/sh\ntouch "{started}"\n{wait}exit {int(action == "failed")}\n')
        opener.chmod(0o755)
        waiting = threading.Event()
        allow_poll = threading.Event()
        original_wait = native.wait_for_playback
        original_command = native.command_for
        ipc = []

        def command(message, path, settings):
            ipc.append(path)
            binary, *args = original_command(message, path, settings)
            return [binary, f'--script={ROOT}/config/mpv/scripts/youtube.lua', f'--script={guard}', *args]

        def wait_to_poll(process, path, deadline):
            player.process = process
            waiting.set()
            if not allow_poll.wait(10):
                raise AssertionError('The startup test did not release the native host.')
            return original_wait(process, path, deadline)

        state = player.root / 'native-state'
        with (
            patch.object(native, 'CONFIG', config),
            patch.object(native, 'STATE', state),
            patch.object(native, 'command_for', side_effect=command),
            patch.object(native, 'wait_for_playback', side_effect=wait_to_poll),
            patch.object(
                native, 'proxy_environment', return_value=os.environ | {'PATH': f'{player.root}:{os.environ["PATH"]}'}
            ),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            reply = pool.submit(native.handle, request())
            try:
                self.assertTrue(waiting.wait(5))
                player.log = next(state.glob('player-*.log'))
                player.wait(ipc[0].is_socket)
                player.socket = socket.socket(socket.AF_UNIX)
                player.socket.settimeout(5)
                player.socket.connect(str(ipc[0]))
                player.reader = player.socket.makefile('rb')
                player.sequence = 0
                player.wait(lambda: player.get('user-data/youtube-quality/loading'))
                if action == 'quit':
                    player.socket.sendall(b'{"command":["quit"]}\n')
                else:
                    player.command('script-binding', 'youtube/youtube-browser')
                    wait_for(started.exists)
                if action in ('fast', 'quit'):
                    self.assertEqual(player.process.wait(timeout=5), 0)
                allow_poll.set()
                if action == 'quit':
                    with self.assertRaisesRegex(RuntimeError, 'mpv exited before playback started'):
                        reply.result(timeout=5)
                else:
                    self.assertEqual(reply.result(timeout=5), BROWSER_REPLY)
                    if action == 'slow':
                        self.assertIsNone(player.process.poll())
                        release.touch()
                        self.assertEqual(player.process.wait(timeout=5), 0)
                    elif action == 'failed':
                        player.wait(lambda: player.get('user-data/youtube-quality/slate'))
                        self.assertIsNone(player.process.poll())
                        self.assertEqual(player.get('user-data/youtube-quality/route'), 'browser')
            finally:
                release.touch()
                allow_poll.set()

    @player_tests()
    def test_native_reports_the_safe_player_failure_reason(self):
        player = Player({'*': 'fail'})
        self.addCleanup(player.close)
        player.wait(lambda: player.get('user-data/youtube-quality/slate'))
        with self.assertRaisesRegex(RuntimeError, 'YouTube requested account access'):
            native.wait_for_playback(player.process, player.root / 'ipc', time.monotonic() + 2)

    @player_tests()
    def test_custom_thumbnail_executable_reaches_mpv_without_splitting_the_path(self):
        path = '/opt/player, with spaces/mpv'
        with patch.object(native, 'executable', return_value=path):
            command = native.command_for(request(), Path('/tmp/ipc'))
        option = next(arg for arg in command if arg.startswith('--script-opts-append=thumbfast-mpv_path='))
        player = Player(options=(option,))
        self.addCleanup(player.close)
        player.wait_loaded('primary')
        self.assertEqual(player.get('options/script-opts')['thumbfast-mpv_path'], path)

    def test_fixed_schema_rejects_unsafe_values(self):
        for value in (
            None,
            [],
            request(url='file:///tmp/movie'),
            request(url='https://user:secret@example.org'),
            request(url='https://example.org\n--script=evil'),
            request(url='https://example.org:broken'),
            request(position=True),
            request(position=float('nan')),
            request(position=float('inf')),
            request(position=-1),
            request(quality=999),
            request(quality=True),
            request(fullscreen='yes'),
            request(action='shell'),
            request(version=2),
            request(version=True),
            request(version=1.0),
            request(args=['--script=evil']),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.validate(value)

    def test_start_is_entry_local_and_quality_is_bounded(self):
        with patch.object(native, 'executable', return_value='/usr/bin/mpv'):
            command = native.command_for(request(position=0), Path('/tmp/socket'))
        self.assertEqual(command[-4:], ['--{', '--start=0', 'https://www.youtube.com/watch?v=fixture&t=0', '--}'])
        self.assertIn('--ytdl-format=bestvideo[height<=?1080]+bestaudio/best[height<=?1080]', command)
        self.assertIn('--fullscreen=no', command)
        self.assertIn('--script-opts-append=thumbfast-mpv_path=/usr/bin/mpv', command)
        with patch.object(native, 'executable', return_value='/usr/bin/mpv'):
            precise = native.command_for(request(position=42.625), Path('/tmp/socket'))
        self.assertEqual(precise[-3:], ['--start=42.625', 'https://www.youtube.com/watch?v=fixture&t=42.625', '--}'])

    def test_null_position_preserves_url_and_player_history(self):
        with patch.object(native, 'executable', return_value='mpv'):
            command = native.command_for(request(position=None, quality=0), Path('/tmp/socket'))
        self.assertEqual(command[-2:], ['--', request()['url']])
        self.assertFalse(any(arg.startswith('--start=') for arg in command))

    def test_native_framing_and_partial_reads(self):
        class Partial(io.BytesIO):
            def read(self, size):
                return super().read(min(size, 2))

        payload = json.dumps(request()).encode()
        output = io.BytesIO()
        with patch.object(native, 'handle', return_value={'ok': True, 'message': 'ready'}) as handler:
            native.serve(Partial(struct.pack('=I', len(payload)) + payload), output)
            handler.assert_called_once_with(request())
        data = output.getvalue()
        self.assertEqual(struct.unpack('=I', data[:4])[0], len(data) - 4)
        self.assertTrue(json.loads(data[4:])['ok'])

    def test_malformed_frames_return_errors(self):
        for data in (b'', b'\x01', struct.pack('=I', 65537), struct.pack('=I', 1) + b'{'):
            output = io.BytesIO()
            native.serve(io.BytesIO(data), output)
            self.assertFalse(json.loads(output.getvalue()[4:])['ok'])

    def test_play_responses(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(native, 'CONFIG', Path(temp)),
            patch.object(native, 'STATE', Path(temp) / 'state'),
            patch.object(native, 'command_for', return_value=['mpv']),
            patch.object(native.subprocess, 'Popen') as spawn,
            patch.object(native, 'wait_for_playback') as wait,
        ):
            (Path(temp) / 'mpv.conf').touch()
            spawn.return_value.pid = 123
            spawn.return_value.poll.return_value = None
            payload = json.dumps(request()).encode()
            frame = struct.pack('=I', len(payload)) + payload

            def play():
                output = io.BytesIO()
                native.serve(io.BytesIO(frame), output)
                return json.loads(output.getvalue()[4:])

            self.assertEqual(play(), {'ok': True, 'outcome': 'playing', 'message': 'mpv is playing.', 'pid': 123})

            def request_browser(_process, path, _deadline):
                path.with_name(native.BROWSER_REQUEST_FILE).touch()
                raise RuntimeError('mpv exited before playback started')

            wait.side_effect = request_browser
            self.assertEqual(play(), BROWSER_REPLY)
            spawn.return_value.terminate.assert_not_called()

            wait.side_effect = RuntimeError('no stream')
            failure = play()
            self.assertEqual(failure.keys(), {'ok', 'message'})
            self.assertFalse(failure['ok'])
            self.assertIn('no stream\nPlayer log: ', failure['message'])
            spawn.return_value.terminate.assert_called_once()

    def test_prune_ignores_vanished_logs_and_applies_retention_to_old_logs(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(native, 'STATE', Path(temp)):
            newest, oldest, vanished = (Path(temp) / f'player-{name}.log' for name in ('newest', 'oldest', 'vanished'))
            for log, mtime in ((newest, 2), (oldest, 1)):
                log.touch()
                os.utime(log, (mtime, mtime))
            with patch.object(Path, 'glob', return_value=iter((vanished, oldest, newest))):
                native.prune_logs(2)
            self.assertTrue(newest.exists())
            self.assertFalse(oldest.exists())

    def test_concurrent_startup_failures_keep_both_logs(self):
        pending = threading.Event()
        both_pending = threading.Barrier(2)

        def fail_startup(_process, _path, _deadline):
            pending.set()
            both_pending.wait(timeout=5)
            raise RuntimeError('not ready')

        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(native, 'CONFIG', Path(temp)),
            patch.object(native, 'STATE', Path(temp) / 'state'),
            patch.object(native, 'load_config', return_value=DEFAULTS | {'log_retention': 1}),
            patch.object(native, 'command_for', return_value=['mpv']),
            patch.object(native.subprocess, 'Popen'),
            patch.object(native, 'wait_for_playback', side_effect=fail_startup),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            (Path(temp) / 'mpv.conf').touch()
            first = pool.submit(native.handle, request())
            self.assertTrue(pending.wait(5))
            second = pool.submit(native.handle, request())
            logs = set()
            for call in (first, second):
                with self.assertRaisesRegex(RuntimeError, 'not ready') as error:
                    call.result(timeout=5)
                log = Path(str(error.exception).split('Player log: ')[1])
                self.assertTrue(log.is_file(), log)
                logs.add(log)
            self.assertEqual(len(logs), 2)

    def test_failed_playback_stops_new_player_and_preserves_browser(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(native, 'CONFIG', Path(temp)),
            patch.object(native, 'STATE', Path(temp) / 'state'),
            patch.object(native, 'command_for', return_value=['mpv']),
            patch.object(native.subprocess, 'Popen') as spawn,
            patch.object(native, 'wait_for_playback', side_effect=TimeoutError('not ready')),
        ):
            (Path(temp) / 'mpv.conf').touch()
            spawn.return_value.poll.return_value = None
            with self.assertRaises(RuntimeError) as error:
                native.handle(request())
            log = next((Path(temp) / 'state').glob('player-*.log'))
            self.assertIn('not ready', str(error.exception))
            self.assertIn(str(log), str(error.exception))
            spawn.return_value.terminate.assert_called_once()
            self.assertNotIn('shell', spawn.call_args.kwargs)
            self.assertEqual(next((Path(temp) / 'state').glob('player-*.log')).stat().st_mode & 0o777, 0o600)
