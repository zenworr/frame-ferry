import json
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from .helpers import ROOT
from .mpv_harness import URL, Player


@unittest.skipUnless(shutil.which('mpv'), 'mpv is required for offline playback tests')
class MpvTests(unittest.TestCase):
    def player(self, *args, **kwargs):
        p = Player(*args, **kwargs)
        self.addCleanup(p.close)
        return p

    def test_real_hooks_recover_without_removing_duplicate_entries(self):
        p = self.player({'primary': 'fail'}, duplicates=True)
        p.wait_loaded('authenticated')
        self.assertEqual(p.get('playlist-count'), 2)
        self.assertTrue(p.get('user-data/test/active-bool'), 'uosc cannot read the active flag')
        p.command('playlist-next')
        p.wait(lambda: len((p.root / 'calls').read_text().splitlines()) == 4)
        p.wait_loaded('authenticated')
        self.assertEqual(p.get('playlist-count'), 2)
        self.assertEqual(
            (p.root / 'calls').read_text().splitlines(), ['primary', 'authenticated', 'primary', 'authenticated']
        )

    def test_youtube_transport_and_cache_in_real_mpv(self):
        p = self.player(
            {'primary': {'protocol': 'http'}},
            media_seconds=180,
            options=(
                f'--include={ROOT}/config/mpv/mpv.conf',
                '--vo=null',
                '--ao=null',
                '--pause=yes',
                '--save-position-on-quit=no',
                '--no-resume-playback',
            ),
        )
        p.wait_loaded('primary')
        self.assertEqual(p.get('options/network-timeout'), 60)
        self.assertGreater(p.get('options/cache-secs'), 180)
        self.assertEqual(p.get('options/demuxer-max-bytes'), 300 * 1024 * 1024)
        p.wait(lambda: (p.get('demuxer-cache-duration') or 0) > 60)
        version = re.match(r'^n?(\d+)\.', p.get('ffmpeg-version'))
        if not version or int(version[1]) < 9:
            self.assertNotIn('request_size', p.get('options/stream-lavf-o'))
            return
        p.wait(lambda: len(p.requests) >= 3)
        for requested, _port in p.requests:
            first, last = requested.split('=')[1].split('-')
            self.assertTrue(last, 'unbounded request used for YouTube media')
            self.assertLessEqual(int(last) - int(first) + 1, 1024 * 1024)
        self.assertEqual(len({port for _, port in p.requests}), 1, 'HTTP connection was not reused')
        other = f'http://127.0.0.1:{p.server.server_port}/audio.wav'
        p.command('loadfile', other)
        p.wait(lambda: p.get('user-data/test/ready') and p.get('path') == other)
        self.assertNotIn(
            'request_size', p.get('options/stream-lavf-o'), 'YouTube transport options leaked to another site'
        )

    def test_sustained_buffering_recovers_automatically_at_the_same_position(self):
        p = self.player(
            {'primary': {'protocol': 'http', 'media': 'buffer'}}, media_seconds=180, options=('--speed=20',)
        )
        p.wait_loaded('primary')
        version = re.match(r'^n?(\d+)\.', p.get('ffmpeg-version'))
        if not version or int(version[1]) < 9:
            self.skipTest('The bounded HTTP stall fixture requires FFmpeg 9+')
        p.wait(lambda: p.get('paused-for-cache'), timeout=8)
        position = p.get('time-pos')
        started = time.monotonic()
        self.assertFalse(p.get('pause'))
        self.assertFalse(p.get('seeking'))
        p.wait(lambda: len((p.root / 'calls').read_text().splitlines()) > 1, timeout=13)
        elapsed = time.monotonic() - started
        p.wait_loaded('authenticated')
        self.assertGreater(elapsed, 9)
        self.assertLess(elapsed, 13)
        self.assertAlmostEqual(float(p.get('file-local-options/start')), position, delta=0.5)
        self.assertGreaterEqual(p.get('time-pos'), position - 0.5)
        self.assertEqual((p.root / 'calls').read_text().splitlines(), ['primary', 'authenticated'])
        self.assertEqual(p.get('playlist-count'), 1)
        self.assertFalse(p.get('pause'))

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is required for the split-stream fixture')
    def test_video_failure_recovers_while_audio_keeps_playing(self):
        p = self.player(
            {
                'primary': {'split': True, 'media': 'broken-video.mp4'},
                'authenticated': {'split': True, 'media': 'video.mp4'},
            },
            media_seconds=120,
            video_seconds=120,
            options=('--speed=4',),
        )
        p.wait_loaded('primary')
        p.wait(
            lambda: (p.get('audio-pts') or 0) > (p.get('demuxer-cache-state').get('cache-end') or 120) + 1, timeout=8
        )
        self.assertFalse(p.get('paused-for-cache'), 'fixture did not reproduce the video-only failure')
        self.assertFalse(p.get('eof-reached'))
        audio = p.get('audio-pts')
        reader = p.get('demuxer-cache-state')['reader-pts']
        p.wait(lambda: p.get('audio-pts') > audio + 2)
        self.assertAlmostEqual(p.get('demuxer-cache-state')['reader-pts'], reader, delta=0.1)
        last_position = [p.get('time-pos')]

        def recovered():
            if p.get('user-data/youtube-quality/route') != 'primary':
                return True
            position = p.get('time-pos')
            if position is not None:
                last_position[0] = position
            return False

        p.wait(recovered, timeout=13)
        p.wait_loaded('authenticated')
        self.assertAlmostEqual(float(p.get('file-local-options/start')), last_position[0], delta=1)
        self.assertEqual(p.get('playlist-count'), 1)
        self.assertEqual((p.root / 'calls').read_text().splitlines(), ['primary', 'authenticated'])
        reader = p.get('demuxer-cache-state')['reader-pts']
        p.wait(lambda: p.get('demuxer-cache-state')['reader-pts'] > reader + 1)
        self.assertIn('Video stream stopped while audio continued', p.log.read_text())

    def test_error_screen_and_manual_retry(self):
        p = self.player({'*': 'fail'})
        p.wait(lambda: p.get('media-title') == 'YouTube playback failed' and p.get('video-params'))
        self.assertTrue(p.get('pause'))
        self.assertTrue(p.get('ytdl'), 'error screen unloaded the extraction hook')
        self.assertEqual(p.get('playlist-count'), 1)
        self.assertEqual(
            (p.root / 'calls').read_text().splitlines(), ['primary', 'authenticated', 'token', 'hls', 'fallback']
        )
        p.routes.write_text('{}')
        p.command('script-binding', 'youtube/youtube-retry')
        p.wait_loaded('primary')
        self.assertFalse(p.get('pause'))
        self.assertEqual(p.get('playlist-count'), 1)

    def test_right_click_toggles_pause(self):
        p = self.player(options=(f'--input-conf={ROOT}/config/mpv/input.conf',))
        p.wait_loaded('primary')
        p.command('keypress', 'MBTN_RIGHT')
        p.wait(lambda: p.get('pause') is True)
        p.command('keypress', 'MBTN_RIGHT')
        p.wait(lambda: p.get('pause') is False)

    def test_browser_timestamp_overrides_watch_history(self):
        for timestamp, routes, route in (
            (30, {}, 'primary'),
            (0, {'primary': 'fail'}, 'authenticated'),
            (None, {}, 'primary'),
        ):
            with self.subTest(timestamp=timestamp), tempfile.TemporaryDirectory() as history:
                url = URL if timestamp is None else URL + f'?t={timestamp}'
                options = ('--pause=yes', '--resume-playback=yes', f'--watch-later-directory={history}')
                previous = self.player(url=url, options=options)
                previous.wait_loaded('primary')
                previous.command('seek', 42.5, 'absolute+exact')
                previous.wait(
                    lambda previous=previous: (
                        abs((previous.get('time-pos') or 0) - 42.5) < 0.2 and not previous.get('seeking')
                    )
                )
                self.assertEqual(previous.command('write-watch-later-config')['error'], 'success')
                self.assertTrue(list(Path(history).iterdir()))
                current = self.player(routes, url=url, options=options)
                current.wait_loaded(route)
                self.assertAlmostEqual(current.get('time-pos'), 42.5 if timestamp is None else timestamp, delta=0.2)
                current.command('seek', 45.5, 'absolute+exact')
                current.wait(
                    lambda current=current: (
                        abs((current.get('time-pos') or 0) - 45.5) < 0.2 and not current.get('seeking')
                    )
                )
                calls = len((current.root / 'calls').read_text().splitlines())
                current.command('script-binding', 'youtube/youtube-retry')
                current.wait(
                    lambda current=current, calls=calls: len((current.root / 'calls').read_text().splitlines()) > calls
                )
                current.wait_loaded(route)
                self.assertAlmostEqual(current.get('time-pos'), 45.5, delta=0.2)

    def test_browser_timestamp_round_trip(self):
        for routes, route in (({}, 'primary'), ({'primary': 'fail'}, 'authenticated')):
            with self.subTest(route=route):
                p = self.player(routes, url=URL + '?t=30', options=('--pause=yes',))
                p.wait_loaded(route)
                self.assertAlmostEqual(p.get('time-pos'), 30, delta=0.2)
                p.command('seek', 42.5, 'absolute+exact')
                p.wait(lambda p=p: abs((p.get('time-pos') or 0) - 42.5) < 0.2 and not p.get('seeking'))
                p.command('script-binding', 'youtube/youtube-browser')
                destination = p.root / 'browser-url'
                p.wait(destination.exists)
                self.assertEqual(destination.read_text(), URL + '?t=42')
                p.wait(lambda p=p: p.process.poll() is not None)
                self.assertEqual(p.process.returncode, 0)

    def test_manual_retry_preserves_position_and_pause(self):
        p = self.player(duplicates=True)
        p.wait_loaded('primary')
        p.command('seek', 30, 'absolute+exact')
        p.wait(lambda: (p.get('time-pos') or 0) >= 29.9 and not p.get('seeking'))
        p.command('set_property', 'pause', True)
        position = p.get('time-pos')
        p.command('script-binding', 'youtube/youtube-retry')
        p.wait(lambda: len((p.root / 'calls').read_text().splitlines()) == 2)
        p.wait_loaded('primary')
        self.assertAlmostEqual(p.get('time-pos'), position, delta=0.2)
        self.assertTrue(p.get('pause'))
        p.command('playlist-next')
        p.wait(lambda: len((p.root / 'calls').read_text().splitlines()) == 3)
        p.wait_loaded('primary')
        self.assertLess(p.get('time-pos'), 1, 'position leaked into the next playlist item')

    def test_retry_after_error_screen_restores_playback_position(self):
        p = self.player()
        p.wait_loaded('primary')
        p.command('seek', 30, 'absolute+exact')
        p.wait(lambda: (p.get('time-pos') or 0) >= 29.9 and not p.get('seeking'))
        p.command('set_property', 'pause', True)
        position = p.get('time-pos')
        p.routes.write_text(json.dumps({'*': 'fail'}))
        p.command('script-binding', 'youtube/youtube-retry')
        p.wait(lambda: p.get('media-title') == 'YouTube playback failed' and p.get('video-params'))
        p.routes.write_text('{}')
        p.command('script-binding', 'youtube/youtube-retry')
        p.wait(lambda: len((p.root / 'calls').read_text().splitlines()) == 7)
        p.wait_loaded('primary')
        self.assertAlmostEqual(p.get('time-pos'), position, delta=0.2)
        self.assertTrue(p.get('pause'))

    def test_retained_authenticated_stream_survives_failed_alternatives(self):
        p = self.player(
            {
                '*': 'fail',
                'authenticated': {
                    'width': 1920,
                    'height': 1080,
                    'media': 'header',
                    'http_headers': {'Referer': 'https://example.test/retained'},
                },
            },
            provider=False,
        )
        p.wait_loaded('retained')
        self.assertEqual((p.root / 'calls').read_text().splitlines(), ['primary', 'authenticated', 'hls'])
        self.assertEqual(p.get('media-title'), 'Offline fixture')
        self.assertEqual(p.get('playlist-count'), 1)
        candidate = p.get('file-local-options/ytdl-raw-options')['frameferry-candidate']
        self.assertFalse(Path(candidate).exists(), 'successful replay left its temporary file')

    def test_higher_quality_route_wins_over_retained_stream(self):
        p = self.player({'primary': 'fail', 'authenticated': {'width': 1920, 'height': 1080}})
        p.wait_loaded('token')
        self.assertEqual((p.root / 'calls').read_text().splitlines(), ['primary', 'authenticated', 'token'])
        self.assertNotIn('frameferry-candidate', p.get('file-local-options/ytdl-raw-options'))

    def test_unusable_retained_stream_falls_back_without_a_loop(self):
        for metadata in ({'media': 'denied'}, {'available_at': time.time() + 3600}):
            with self.subTest(metadata=metadata):
                p = self.player(
                    {'*': 'fail', 'authenticated': {'width': 1920, 'height': 1080, **metadata}, 'fallback': 'play'},
                    provider=False,
                )
                p.wait_loaded('fallback')
                self.assertEqual(
                    (p.root / 'calls').read_text().splitlines(), ['primary', 'authenticated', 'hls', 'fallback']
                )
                self.assertEqual(p.get('playlist-count'), 1)

    def test_retained_file_is_private_and_removed_on_cancellation(self):
        for action in ('browser', 'shutdown', 'kill'):
            with self.subTest(action=action):
                p = self.player(
                    {'*': 'fail', 'authenticated': {'width': 1920, 'height': 1080, 'media': 'stall'}}, provider=False
                )
                p.wait(
                    lambda p=p: (
                        p.get('user-data/youtube-quality/route') == 'retained'
                        and p.get('file-local-options/ytdl-raw-options').get('frameferry-candidate')
                    )
                )
                candidate = Path(p.get('file-local-options/ytdl-raw-options')['frameferry-candidate'])
                marker = str(candidate) + ' (deleted)'
                self.assertFalse(candidate.exists(), 'signed URLs have a named temporary file')
                descriptor = None
                for fd in Path(f'/proc/{p.process.pid}/fd').iterdir():
                    try:
                        if os.readlink(fd) == marker:
                            descriptor = fd
                            break
                    except FileNotFoundError:
                        continue
                self.assertIsNotNone(descriptor)
                self.assertEqual(descriptor.stat().st_mode & 0o777, 0o600)
                if action == 'browser':
                    p.command('script-binding', 'youtube/youtube-browser')
                    p.wait(lambda p=p: p.process.poll() is not None)
                    self.assertEqual(p.process.returncode, 0)
                else:
                    if action == 'kill':
                        p.process.kill()
                    else:
                        p.process.terminate()
                    p.process.wait(timeout=3)
                self.assertFalse(candidate.exists(), 'cancellation left its temporary file')
                if descriptor.exists():
                    self.assertNotEqual(os.readlink(descriptor), marker, 'mpv still holds the metadata open')

    def test_retained_stream_does_not_leak_between_players_or_items(self):
        a = self.player({'*': 'fail', 'authenticated': {'width': 1920, 'height': 1080}})
        b = self.player({'*': 'fail'})
        a.wait_loaded('retained')
        b.wait(lambda: b.get('media-title') == 'YouTube playback failed')
        a.routes.write_text(json.dumps({'*': 'fail'}))
        a.command('loadfile', URL + '-next')
        a.wait(lambda: a.get('media-title') == 'YouTube playback failed')
        self.assertNotIn('frameferry-candidate', a.get('file-local-options/ytdl-raw-options'))

    def test_players_have_independent_routes(self):
        a = self.player({'primary': 'fail', 'authenticated': 'fail'})
        b = self.player()
        a.wait_loaded('token')
        b.wait_loaded('primary')
        self.assertEqual(a.get('playlist-count'), 1)
        self.assertEqual(b.get('playlist-count'), 1)

    def test_browser_action_cancels_loading_without_failure_claim(self):
        p = self.player({'*': 'stall'})
        p.wait(lambda: p.get('user-data/youtube-quality/loading'))
        p.command('script-binding', 'youtube/youtube-browser')
        p.wait(lambda: (p.root / 'browser-url').exists())
        p.wait(lambda: p.process.poll() is not None)
        self.assertEqual(p.process.returncode, 0)
        self.assertEqual((p.root / 'browser-url').read_text(), URL)
        self.assertNotIn('YouTube playback failed', p.log.read_text())

    def test_browser_open_failure_keeps_player_available(self):
        p = self.player()
        p.wait_loaded('primary')
        browser = p.root / 'xdg-open'
        browser.write_text('#!/bin/sh\nexit 1\n')
        p.command('script-binding', 'youtube/youtube-browser')
        p.wait(lambda: 'Could not open the browser' in p.log.read_text())
        self.assertIsNone(p.process.poll())

    def test_sponsorblock_timer_and_toggle_in_real_mpv(self):
        p = self.player(options=[f'--script={ROOT}/config/mpv/scripts/sponsorblock_chapter_skip.lua'])
        p.wait_loaded('primary')
        p.command('seek', 10, 'absolute+exact')
        p.wait(lambda: (p.get('time-pos') or 0) >= 9.9 and not p.get('seeking'))
        p.command('set_property', 'pause', True)
        p.command(
            'set_property',
            'chapter-list',
            [
                {'time': 10, 'title': 'sponsor segment start (fixture)'},
                {'time': 30, 'title': 'sponsor segment end (fixture)'},
            ],
        )
        p.wait(lambda: p.get('user-data/sponsorblock/available'))
        self.assertLess(p.get('time-pos'), 20, 'paused playback was skipped')
        p.command('script-binding', 'sponsorblock_chapter_skip/sponsorblock-toggle')
        p.wait(lambda: p.get('user-data/sponsorblock/state') == 'Off')
        p.command('set_property', 'pause', False)
        p.wait(lambda: p.get('time-pos') > 10.2)
        self.assertLess(p.get('time-pos'), 15, 'disabled skipping still moved playback')
        p.command('script-binding', 'sponsorblock_chapter_skip/sponsorblock-toggle')
        p.wait(lambda: p.get('time-pos') >= 30, timeout=3)

    def test_quick_fallback_skips_intermediate_routes(self):
        p = self.player({'primary': 'stall'})
        p.wait(lambda: p.get('user-data/youtube-quality/loading'))
        p.command('script-binding', 'youtube/youtube-fast-fallback')
        p.wait_loaded('fallback')
        calls = (p.root / 'calls').read_text().splitlines()
        self.assertEqual(calls[-1], 'fallback')
        self.assertFalse(set(calls) & {'authenticated', 'token', 'hls'})
        self.assertEqual(p.get('playlist-count'), 1)

    @unittest.skipUnless(os.environ.get('MPV_SLOW_TESTS') == '1', 'run make test-slow for the 30-second watchdog')
    def test_continuous_data_cannot_bypass_total_deadline(self):
        cases = [
            (self.player({'*': 'stall'}), ['primary', 'authenticated', 'token', 'fallback']),
            (
                self.player(
                    {
                        '*': 'stall',
                        'primary': 'fail',
                        'authenticated': {'width': 1920, 'height': 1080, 'media': 'stall'},
                    }
                ),
                ['primary', 'authenticated', 'token', 'hls', 'fallback'],
            ),
        ]
        for p, expected in cases:
            with self.subTest(calls=expected):
                p.wait(lambda p=p: p.get('media-title') == 'YouTube playback failed', timeout=33)
                elapsed = time.monotonic() - p.started
                self.assertLess(elapsed, 32)
                self.assertGreater(elapsed, 25)
                self.assertEqual(p.get('playlist-count'), 1)
                self.assertEqual((p.root / 'calls').read_text().splitlines(), expected)
        self.assertIn('Trying the earlier stream', cases[1][0].log.read_text())
