import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from .mpv_harness import Player
from .ui_fixtures import patched_thumbfast


@unittest.skipUnless(
    os.environ.get('FRAME_FERRY_PLAYER_TESTS') == '1' and shutil.which('mpv'),
    'run make test-player for real mpv tests',
)
class ThumbfastTests(unittest.TestCase):
    def test_preview_uses_only_video_without_request_context(self):
        for allow_preview in (True, False):
            with self.subTest(allow_preview=allow_preview), tempfile.TemporaryDirectory() as directory:
                self.check_thumbnail(Path(directory), allow_preview)

    def check_thumbnail(self, root, allow_preview):
        ui = os.environ.get('FRAME_FERRY_UI_CONFIG')
        thumbfast = Path(ui) / 'scripts/thumbfast.lua' if ui else patched_thumbfast(root)
        thumbnail = root / 'preview'
        child_args = root / 'child.json'
        child_log = root / 'child.log'
        child = root / 'mpv-child'
        child.write_text(
            f'#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n'
            f'Path({str(child_args)!r}).write_text(json.dumps(sys.argv[1:]))\n'
            f'os.execv({shutil.which("mpv")!r}, ["mpv", {f"--log-file={child_log}"!r}, *sys.argv[1:]])\n'
        )
        child.chmod(0o755)
        p = Player(
            {'primary': {'media': 'video.mp4', 'protocol': 'http', 'dynamic_range': 'SDR', 'split': allow_preview}},
            video_seconds=15,
            options=(
                f'--script={thumbfast}',
                '--script-opts-append=thumbfast-network=yes',
                f'--script-opts-append=thumbfast-mpv_path={child}',
                f'--script-opts-append=thumbfast-thumbnail={thumbnail}',
                '--pause',
            ),
        )
        try:
            p.wait_loaded('primary')
            result_key = 'user-data/mpv/ytdl/json-subprocess-result'
            result = p.get(result_key)
            data = json.loads(result['stdout'])
            base = data['url'].removesuffix('video.mp4')

            def candidate(name, height, **overrides):
                return {
                    'url': base + name + '-video.mp4',
                    'height': height,
                    'protocol': 'http',
                    'dynamic_range': 'SDR',
                    'vcodec': 'mpeg4',
                    **overrides,
                }

            data['formats'] = [
                candidate('audio', 360, vcodec='none'),
                candidate('no-codec', 340, vcodec=None),
                candidate('header', 320, http_headers={'Referer': 'https://example.test/preview'}),
                candidate('cookie', 300, cookies='preview=fixture'),
            ]
            selected = candidate('preview', 180, http_headers={})
            if allow_preview:
                data['formats'].append(selected)
            result['stdout'] = json.dumps(data)
            self.assertEqual(p.command('set_property', result_key, result)['error'], 'success')
            p.wait(lambda: p.get('video-out-params'))
            p.command('script-message-to', 'thumbfast', 'thumb', '2', '', '')
            image = Path(f'{thumbnail}{p.process.pid}.bgra')
            p.wait(lambda: image.is_file() and image.stat().st_size > 0)
            args = json.loads(child_args.read_text())
            self.assertEqual(args[-1], selected['url'] if allow_preview else data['url'])
            self.assertFalse('Disabling filter pad' in child_log.read_text(), 'preview padding failed')
            self.assertIn('--ytdl=no', args)
            self.assertNotIn('example.test', repr(args))
            self.assertNotIn('preview=fixture', repr(args))
            first_frame = image.read_bytes()
            p.command('script-message-to', 'thumbfast', 'thumb', '7', '', '')
            p.wait(lambda: image.is_file() and image.read_bytes() not in (b'', first_frame))
            self.assertEqual((p.root / 'calls').read_text().splitlines(), ['primary'])
            p.command('quit')
            p.process.wait(timeout=5)
        finally:
            p.close()
