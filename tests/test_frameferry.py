import io
import json
import os
import signal
import socket
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from helpers import ROOT, load_script

native = load_script('frameferry-native')


def request(**changes):
    return {'version': 1, 'action': 'play', 'url': 'https://www.youtube.com/watch?v=fixture&t=99',
            'position': 30, 'quality': 1080, 'fullscreen': False, **changes}


class NativeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for extension tests')
    def test_extension_behavior(self):
        result = subprocess.run(['node', str(ROOT / 'tests/test_extension.mjs')],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('mpv'), 'mpv is required')
    def test_real_native_handoff_starts_at_position_and_confirms_playback(self):
        from mpv_harness import Player
        player = Player()
        self.addCleanup(player.close)
        config = player.root / 'native-config'
        config.mkdir()
        (config / 'mpv.conf').write_text('vo=null\nao=null\npause=yes\nkeep-open=yes\n')
        observed = []
        original = native.wait_for_playback
        def probe(process, path, deadline):
            original(process, path, deadline)
            with socket.socket(socket.AF_UNIX) as ipc:
                ipc.connect(str(path))
                ipc.sendall(b'{"command":["get_property","time-pos"],"request_id":1}\n')
                with ipc.makefile('rb') as stream:
                    while True:
                        event = json.loads(stream.readline())
                        if event.get('request_id') == 1:
                            observed.append(event['data'])
                            break
        with patch.object(native, 'CONFIG', config), patch.object(native, 'STATE', player.root/('native-state-' + 'x' * 80)), \
                patch.object(native, 'wait_for_playback', side_effect=probe):
            reply = native.handle(request(url=f'http://127.0.0.1:{player.server.server_port}/audio.wav', quality=0))
        try:
            self.assertTrue(reply['ok'])
            self.assertAlmostEqual(observed[0], 30, delta=.2)
        finally:
            os.kill(reply['pid'], signal.SIGTERM)
            os.waitpid(reply['pid'], 0)

    def test_fixed_schema_rejects_unsafe_values(self):
        for value in (None, [], request(url='file:///tmp/movie'), request(url='https://user:secret@example.org'),
                      request(url='https://example.org\n--script=evil'), request(url='https://example.org:broken'),
                      request(position=True), request(position=float('nan')), request(position=float('inf')),
                      request(position=-1), request(quality=999), request(quality=True), request(fullscreen='yes'),
                      request(action='shell'), request(version=2), request(version=True), request(version=1.0),
                      request(args=['--script=evil'])):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.validate(value)

    def test_start_is_entry_local_and_quality_is_bounded(self):
        with patch.object(native.shutil, 'which', return_value='/usr/bin/mpv'):
            command = native.command_for(request(position=0), Path('/tmp/socket'))
        self.assertEqual(command[-4:], ['--{', '--start=0', 'https://www.youtube.com/watch?v=fixture&t=0', '--}'])
        self.assertIn('--ytdl-format=bestvideo[height<=?1080]+bestaudio/best[height<=?1080]', command)
        self.assertIn('--fullscreen=no', command)

    def test_null_position_preserves_url_and_player_history(self):
        with patch.object(native.shutil, 'which', return_value='mpv'):
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

    def test_failed_playback_stops_new_player_and_preserves_browser(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(native, 'CONFIG', Path(temp)), patch.object(native, 'STATE', Path(temp)/'state'), \
                patch.object(native, 'command_for', return_value=['mpv']), \
                patch.object(native.subprocess, 'Popen') as spawn, \
                patch.object(native, 'wait_for_playback', side_effect=TimeoutError('not ready')):
            (Path(temp) / 'mpv.conf').touch()
            spawn.return_value.poll.return_value = None
            with self.assertRaises(TimeoutError): native.handle(request())
            spawn.return_value.terminate.assert_called_once()
            self.assertNotIn('shell', spawn.call_args.kwargs)
            self.assertEqual(next((Path(temp)/'state').glob('player-*.log')).stat().st_mode & 0o777, 0o600)
