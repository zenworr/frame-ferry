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
    def test_preview_accepts_default_headers_but_not_special_formats(self):
        for include_preview in (True, False):
            with self.subTest(include_preview=include_preview), tempfile.TemporaryDirectory() as directory:
                self.check_thumbnail(Path(directory), include_preview)

    def test_preview_rejects_top_level_request_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            self.check_thumbnail(Path(directory), include_preview=True, top_level_headers={'X-Token': 'top-secret'})

    def check_thumbnail(self, root, include_preview, top_level_headers=None):
        allow_preview = include_preview and top_level_headers is None
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

            defaults = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
            }
            data['http_headers'] = {**defaults, **(top_level_headers or {})}
            data['formats'] = [
                candidate('audio', 360, vcodec='none'),
                candidate('no-codec', 340, vcodec=None),
                candidate('referer', 320, http_headers={**defaults, 'Referer': 'https://example.test/preview'}),
                candidate('cookie', 300, cookies='preview=fixture'),
                candidate('cookie-header', 280, http_headers={**defaults, 'cookie': 'header=fixture'}),
                candidate('authorization', 260, http_headers={**defaults, 'Authorization': 'Bearer fixture'}),
                candidate('custom-agent', 240, http_headers={**defaults, 'User-Agent': 'Fixture Agent'}),
                candidate('custom-accept', 220, http_headers={**defaults, 'Accept': 'application/x-fixture'}),
            ]
            selected = candidate('preview', 180, http_headers=defaults if top_level_headers is None else {})
            if include_preview:
                data['formats'].append(selected)
            result['stdout'] = json.dumps(data)
            self.assertEqual(p.command('set_property', result_key, result)['error'], 'success')
            p.wait(lambda: p.get('video-out-params'))
            p.command('script-message-to', 'thumbfast', 'thumb', '2', '', '')
            image = Path(f'{thumbnail}{p.process.pid}.bgra')
            p.wait(lambda: image.is_file() and image.stat().st_size > 0)
            args = json.loads(child_args.read_text())
            self.assertEqual(args[-1], selected['url'] if allow_preview else data['url'])
            log = child_log.read_text()
            self.assertNotIn('Disabling filter pad', log, 'preview padding failed')
            self.assertIn('--ytdl=no', args)
            self.assertFalse(any(arg.startswith(('--http-header-fields', '--user-agent', '--cookies')) for arg in args))
            for value in ('example.test', 'preview=fixture', 'header=fixture', 'Bearer fixture', 'top-secret'):
                self.assertNotIn(value, repr(args))
                self.assertNotIn(value, log)
            first_frame = image.read_bytes()
            p.command('script-message-to', 'thumbfast', 'thumb', '7', '', '')
            p.wait(lambda: image.is_file() and image.read_bytes() not in (b'', first_frame))
            self.assertEqual((p.root / 'calls').read_text().splitlines(), ['primary'])
            p.command('quit')
            p.process.wait(timeout=5)
        finally:
            p.close()
