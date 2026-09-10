import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from helpers import ExtractorFixture, ROOT, load_script, running, wait_for

wrapper = load_script('yt-dlp-mpv')


class FormatTests(unittest.TestCase):
    def test_youtube_hosts(self):
        for url in ['https://youtube.com/watch?v=x', 'https://m.youtube.com/x',
                    'https://youtu.be/x', 'https://www.youtube-nocookie.com/embed/x']:
            self.assertTrue(wrapper.is_youtube_url(url), url)
        for url in ['https://youtube.com.evil.test/x', 'ftp://youtube.com/x',
                    'https://notyoutube.com/x', 'https://[broken']:
            self.assertFalse(wrapper.is_youtube_url(url), url)

    def test_fallback_preserves_ceiling_and_separator(self):
        fmt = 'bestvideo[height<=?720]+bestaudio/best[height<=?720]'
        for args in [['-f', fmt], ['--format', fmt], ['--format='+fmt], ['-f'+fmt]]:
            with self.subTest(args=args):
                original = args + ['--', 'https://youtube.com/watch?v=x']
                result = wrapper.with_quality_fallback(original)
                self.assertIn('best[height<=?720]', ' '.join(result))
                self.assertNotIn('2160', ' '.join(result))
                self.assertLess(result.index('--extractor-args'), result.index('--'))
                self.assertEqual(original, args + ['--', 'https://youtube.com/watch?v=x'])

    def test_fallback_without_format_and_audio_only(self):
        result = wrapper.with_quality_fallback(['-J', '--', 'https://youtu.be/x'])
        self.assertIn('best[height<=?1080][protocol=m3u8_native]', ' '.join(result))
        self.assertIn('youtube:player_client=visionos', result)
        result = wrapper.with_quality_fallback(['-f', 'bestaudio/best'])
        self.assertIn('bestaudio/best', ' '.join(result))

    def test_hls_tries_selected_quality_before_lower_ceiling(self):
        args = ['-f', 'bestvideo[height<=?2160]+bestaudio', '--', 'https://youtu.be/x']
        high = wrapper.with_quality_fallback(args, ceiling=2160)
        low = wrapper.with_quality_fallback(args)
        self.assertIn('best[height<=?2160][protocol=m3u8_native]', ' '.join(high))
        self.assertIn('best[height<=?1080][protocol=m3u8_native]', ' '.join(low))

    def test_fast_token_fallback_respects_selected_ceiling(self):
        for ceiling in (720, 2160):
            result = wrapper.with_quality_fallback(['-f', f'bestvideo[height<=?{ceiling}]+bestaudio'],
                                                   cookies=True, token=True)
            self.assertIn(f'bestvideo[height<=?{min(ceiling, 1080)}]+bestaudio', ' '.join(result))
            self.assertIn('youtube:player_client=mweb;use_ad_playback_context=true', result)
            self.assertNotIn('m3u8_native', ' '.join(result))

    def test_wide_4k_is_not_mistaken_for_a_lower_quality(self):
        args = ['-f', 'bestvideo[height<=?2160]+bestaudio']
        self.assertFalse(wrapper.below_selected_quality({'width': 3840, 'height': 1920}, args))
        self.assertTrue(wrapper.below_selected_quality({'width': 1920, 'height': 960}, args))
        self.assertFalse(wrapper.below_selected_quality({'width': 1920, 'height': 960}, ['-f', 'best']))

    def test_media_availability_uses_selected_formats_and_budget(self):
        info = {'requested_formats': [{'available_at': 105}, {'available_at': 104}],
                'formats': [{'available_at': 10000}]}
        with patch.object(wrapper.time, 'time', return_value=100), \
                patch.object(wrapper.time, 'monotonic', return_value=10), \
                patch.object(wrapper.time, 'sleep') as sleep, patch.object(wrapper.sys, 'stderr'):
            self.assertTrue(wrapper.wait_until_available(info, 16))
            sleep.assert_called_once_with(5)
            sleep.reset_mock()
            self.assertFalse(wrapper.wait_until_available(info, 14))
            self.assertTrue(wrapper.wait_until_available({'available_at': 99}, 14))
            sleep.assert_not_called()

    def test_only_selected_post_live_fragments_are_checked(self):
        broken = {'protocol': 'http_dash_segments', 'fragments': [{}, {}, {}]}
        data = {'live_status': 'post_live', 'protocol': 'm3u8_native', 'formats': [broken]}
        self.assertFalse(wrapper.has_post_live_fragments_without_durations(data))
        data['requested_formats'] = [broken]
        self.assertTrue(wrapper.has_post_live_fragments_without_durations(data))
        broken['fragments'] = [{}, {'duration': 5}, {'duration': 5}]
        self.assertFalse(wrapper.has_post_live_fragments_without_durations(data))
        data['live_status'] = 'not_live'
        broken['fragments'] = [{}, {}]
        self.assertFalse(wrapper.has_post_live_fragments_without_durations(data))

    def test_extraction_deadline(self):
        started = time.monotonic()
        status, stdout, stderr = wrapper.run_captured([
            sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.1)
        self.assertEqual(status, 1)
        self.assertEqual(stdout, b'')
        self.assertIn(b'timed out', stderr)
        self.assertLess(time.monotonic() - started, 2)


class ProcessTests(ExtractorFixture):
    def test_primary_is_anonymous(self):
        result = self.run_wrapper('-J', '-f', 'bestvideo[height<=?2160]+bestaudio',
                                  '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertNotIn('--cookies-from-browser', self.calls()[0])
        self.assertNotIn('youtube:player_client=web_safari', self.calls()[0])

    def test_ended_live_error_is_not_repeated(self):
        self.env['FAKE_FAIL'] = '1'
        result = self.run_wrapper('-J', '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.calls()), 1)

    def test_explicit_fallback_and_cookie_opt_in(self):
        result = self.run_wrapper('-J', '--cookies-from-browser', 'chromium:test',
                                  '--frameferry-route=fallback', '-f', 'best[height<=?720]',
                                  '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertFalse(any(c.startswith('--frameferry') for c in call))
        self.assertIn('youtube:player_client=web_safari', call)
        self.assertIn('--cookies-from-browser', call)
        self.assertIn('best[height<=?720][protocol=m3u8_native]', ' '.join(call))

    def test_full_quality_token_route(self):
        provider = self.install_provider()
        fmt = 'bestvideo[height<=?2160]+bestaudio/best[height<=?2160]'
        result = self.run_wrapper('-J', '--frameferry-route=token', '--frameferry-timeout', '8',
                                  '--cookies-from-browser', 'chromium:test', '-f', fmt,
                                  '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertIn(fmt, call)
        self.assertIn(str(provider), call)
        self.assertIn('youtube:player_client=mweb', call)
        self.assertNotIn('use_ad_playback_context', ' '.join(call))
        self.assertIn('chromium:test', call)
        self.assertFalse(any(c.startswith('--frameferry') for c in call))

    def test_fast_cookie_fallback_uses_installed_provider(self):
        provider = self.install_provider()
        result = self.run_wrapper('-J', '--cookies-from-browser', 'chromium:test',
                                  '--frameferry-route=fallback', '-f', 'best[height<=?2160]',
                                  '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertIn('youtube:player_client=mweb;use_ad_playback_context=true', call)
        self.assertIn('bestvideo[height<=?1080]+bestaudio/best[height<=?1080]', call)
        self.assertIn(str(provider), call)

    def test_missing_token_provider_fails_without_extraction(self):
        result = self.run_wrapper('-J', '--frameferry-route', 'token', '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'token provider not installed', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_authenticated_route_keeps_full_quality(self):
        fmt = 'bestvideo[height<=?2160]+bestaudio'
        result = self.run_wrapper('-J', '--frameferry-route', 'authenticated',
                                  '--cookies-from-browser', 'chromium:test', '-f', fmt,
                                  '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(fmt, self.calls()[0])
        self.assertNotIn('youtube:player_client=web_safari', self.calls()[0])

    def test_limited_authenticated_json_can_be_reused_without_extraction(self):
        self.env['FAKE_INFO'] = json.dumps({'width': 1920, 'height': 1080,
            'http_headers': {'Referer': 'https://example.test/retained'},
            'formats': [{'available_at': time.time() + 3600}]})
        result = self.run_wrapper('-J', '--frameferry-route=authenticated',
                                  '--cookies-from-browser', 'chromium:test',
                                  '-f', 'bestvideo[height<=?2160]+bestaudio', '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'limited authenticated formats', result.stderr)
        self.assertEqual(json.loads(result.stdout)['height'], 1080)
        candidate = self.home / 'candidate.json'
        self.fake.unlink()
        self.env['PATH'] = str(self.home)
        with candidate.open('wb') as metadata:
            candidate.unlink()
            metadata.write(result.stdout)
            metadata.flush()
            replay = self.run_wrapper('-J', '--frameferry-route=retained',
                                      '--frameferry-candidate', str(candidate), '--', 'https://youtu.be/test')
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(replay.stdout, result.stdout)
        self.assertEqual(len(self.calls()), 1)

    def test_retained_stream_checks_availability_and_invalid_files(self):
        candidate = self.home / 'candidate.json'
        args = ('-J', '--frameferry-route=retained', '--frameferry-timeout=.1',
                '--frameferry-candidate', str(candidate), '--', 'https://youtu.be/test')
        result = self.run_wrapper(*args)
        self.assertEqual(result.returncode, 1, result.stderr)
        for content in ('not JSON', '[]', json.dumps({'available_at': time.time() + 3600})):
            with self.subTest(content=content):
                with candidate.open('w') as metadata:
                    candidate.unlink()
                    metadata.write(content)
                    metadata.flush()
                    result = self.run_wrapper(*args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, b'')
        self.assertIn(b'availability exceeds', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_mpv_sigkill_stops_extractor_and_descendants(self):
        self.env['FAKE_PID'] = '1'
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/yt-dlp-mpv'),
                                    '-J', '--', 'https://youtu.be/test'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        try:
            wait_for(lambda: (self.home / 'pids').exists())
            pids = list(map(int, (self.home / 'pids').read_text().split()))
            process.kill()
            process.communicate(timeout=2)
            wait_for(lambda: not any(map(running, pids)), timeout=2)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)

    def test_other_sites_do_not_get_youtube_policy(self):
        result = self.run_wrapper('-J', '--', 'https://example.test/video')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertNotIn('--cookies-from-browser', self.calls()[0])
        self.assertNotIn('--extractor-retries', self.calls()[0])
