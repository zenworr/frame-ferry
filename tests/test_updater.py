import subprocess
import sys
import time
from unittest.mock import patch

from helpers import ExtractorFixture, ROOT, load_script, wait_for

wrapper = load_script('yt-dlp-mpv')


class UpdaterTests(ExtractorFixture):
    def update_command(self):
        return [sys.executable, str(ROOT / 'scripts/yt-dlp-update-background'), str(self.fake),
                str(self.state / 'yt-dlp-update.lock'), str(self.state / 'yt-dlp-update.log')]

    def test_cooldown_does_not_spawn_an_updater(self):
        with patch.object(wrapper, 'STATE_DIR', self.state), \
                patch.object(wrapper.subprocess, 'Popen') as popen:
            wrapper.start_background_update(str(self.fake))
            popen.assert_not_called()

    def test_update_does_not_block_extraction(self):
        (self.state / 'yt-dlp-update.lock').unlink()
        self.env['FAKE_UPDATE_WAIT'] = '1'
        result = self.run_wrapper('-J', '--frameferry-update=yes', '--', 'https://youtu.be/test')
        self.assertEqual(result.returncode, 0, result.stderr)
        wait_for(lambda: (self.home / 'update-ready').exists())
        log = self.state / 'yt-dlp-update.log'
        self.assertNotIn('exit=', log.read_text())
        (self.home / 'update-release').touch()
        wait_for(lambda: 'exit=0' in log.read_text())
        self.assertIn('--ignore-config', next(c for c in self.calls() if '-U' in c))

    def test_concurrent_and_sequential_checks_share_cooldown(self):
        (self.state / 'yt-dlp-update.lock').write_text('')
        processes = [subprocess.Popen(self.update_command(), env=self.env) for _ in range(4)]
        try:
            for process in processes:
                self.assertEqual(process.wait(timeout=5), 0)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        for _ in range(2):
            subprocess.run(self.update_command(), env=self.env, check=True, timeout=5)
        self.assertEqual(len(self.calls()), 1)
        self.assertGreater(float((self.state / 'yt-dlp-update.lock').read_text()), time.time())

    def test_expired_cooldown_allows_a_new_check(self):
        (self.state / 'yt-dlp-update.lock').write_text(str(time.time() - 1))
        subprocess.run(self.update_command(), env=self.env, check=True, timeout=5)
        self.assertEqual(len(self.calls()), 1)

    def test_failed_update_also_has_a_cooldown(self):
        (self.state / 'yt-dlp-update.lock').write_text('')
        self.env['FAKE_UPDATE_STATUS'] = '1'
        for _ in range(2):
            subprocess.run(self.update_command(), env=self.env, check=True, timeout=5)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn('exit=1', (self.state / 'yt-dlp-update.log').read_text())
