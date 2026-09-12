import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home with spaces'
        self.bin = self.home / 'bin'
        self.bin.mkdir(parents=True)
        self.config = self.home / 'custom-config'
        self.data = self.home / 'custom-data'
        self.state = self.home / 'custom-state'
        self.player = self.config / 'frameferry/mpv'
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.config),
                    'XDG_DATA_HOME': str(self.data), 'XDG_STATE_HOME': str(self.state),
                    'XDG_CACHE_HOME': str(self.home / '.cache'),
                    'PATH': str(self.bin) + os.pathsep + os.environ['PATH']}
        for name, version in (('mpv', 'mpv v0.41.0'), ('yt-dlp', '2026.08.19'), ('deno', 'deno 2.9.6')):
            self.executable(name, f'#!/bin/sh\necho "{version}"\n')
        self.executable('curl', f'#!{sys.executable}\n' + '''import os, sys
from pathlib import Path
url = sys.argv[-1]
if os.environ.get('FAIL_DOWNLOAD') and os.environ['FAIL_DOWNLOAD'] in url:
    sys.exit(22)
Path(sys.argv[sys.argv.index('-o')+1]).write_text('fixture: '+url+'\\n')
''')

    def executable(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def install(self, name='install.sh', *args):
        return subprocess.run(['bash', str(ROOT / 'scripts' / name), *args], env=self.env, capture_output=True, timeout=10)

    def doctor(self):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/doctor')], env=self.env, capture_output=True, timeout=10)

    def prepare(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('uosc/main.lua', 'thumbfast.lua'):
            target = self.player / 'scripts' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()

    def test_component_installers_require_cmp_before_writing_files(self):
        for name in ('install-mpv-ui.sh', 'install-mpv-sponsorblock.sh'):
            with self.subTest(installer=name):
                result = subprocess.run(['bash', '-c',
                    'command() { if [[ "$1" == -v && "$2" == cmp ]]; then return 1; '
                    'else builtin command "$@"; fi; }; source "$1"',
                    'test', str(ROOT / 'scripts' / name)],
                    env=self.env, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'Missing required command: cmp', result.stderr)
                self.assertFalse(self.player.exists())

    def test_isolated_install_and_repeat_do_not_touch_normal_mpv(self):
        normal = self.config / 'mpv/mpv.conf'
        normal.parent.mkdir(parents=True)
        normal.write_text('private settings')
        for _ in range(2): self.assertEqual(self.install().returncode, 0)
        self.assertEqual(normal.read_text(), 'private settings')
        self.assertEqual((self.player / 'mpv.conf').read_bytes(), (ROOT / 'config/mpv/mpv.conf').read_bytes())
        manifest = json.loads((self.config / 'net.imput.helium/NativeMessagingHosts/frameferry.json').read_text())
        self.assertEqual(manifest['path'], str(self.data / 'frameferry/bin/frameferry-native'))
        self.assertEqual(len(manifest['allowed_origins'][0].split('//')[1].rstrip('/')), 32)
        self.assertIn(str(self.data), (self.player / 'script-opts/ytdl_hook.conf').read_text())
        self.assertEqual((self.data / 'frameferry/LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
        self.assertTrue((self.data / 'frameferry/LICENSES/MPL-2.0.txt').is_file())

    def test_updates_keep_user_settings_and_uninstall_keeps_changed_files(self):
        self.prepare()
        local = self.player / 'script-opts/youtube.conf'
        local.write_text('cookies_browser=firefox\n')
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(local.read_text(), 'cookies_browser=firefox\n')
        self.assertEqual(self.install('install.sh', '--uninstall').returncode, 0)
        self.assertTrue(local.exists())
        self.assertFalse((self.data / 'frameferry/bin/frameferry-native').exists())

    def test_uninstall_restores_original_files(self):
        target = self.player / 'mpv.conf'
        target.parent.mkdir(parents=True)
        target.write_text('original')
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.install('install.sh', '--uninstall').returncode, 0)
        self.assertEqual(target.read_text(), 'original')

    def test_uninstall_restores_relative_and_broken_symlinks(self):
        self.player.mkdir(parents=True)
        (self.player / 'original.conf').write_text('original')
        target = self.player / 'mpv.conf'
        for original in ('original.conf', 'missing.conf'):
            target.symlink_to(original)
            self.assertEqual(self.install().returncode, 0)
            self.assertFalse(target.is_symlink())
            self.assertEqual(self.install('install.sh', '--uninstall').returncode, 0)
            self.assertTrue(target.is_symlink())
            self.assertEqual(os.readlink(target), original)
            target.unlink()

    def test_doctor_rejects_manifest_and_executable_damage(self):
        self.prepare()
        self.assertEqual(self.doctor().returncode, 0, self.doctor().stdout)
        path = self.config / 'net.imput.helium/NativeMessagingHosts/frameferry.json'
        content = path.read_text()
        for bad in ('[]', '{', content.replace('chrome-extension://', 'https://')):
            path.write_text(bad)
            self.assertEqual(self.doctor().returncode, 1)
        path.write_text(content)
        binary = self.data / 'frameferry/bin/yt-dlp-mpv'
        binary.chmod(0o644)
        self.assertEqual(self.doctor().returncode, 1)
        binary.chmod(0o755)
        binary.write_text('#!/bin/sh\nexit 0\n')
        self.assertEqual(self.doctor().returncode, 1)
        binary.write_bytes((ROOT / 'scripts/yt-dlp-mpv').read_bytes())
        self.executable('mpv', '#!/bin/sh\necho "mpv v0.39.0"\n')
        self.assertEqual(self.doctor().returncode, 1)

    def test_runtime_config_is_private_preserved_and_checked(self):
        self.prepare()
        path = self.config / 'frameferry/config.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        settings = json.loads(path.read_text())
        for key, name in (('mpv', 'mpv'), ('yt_dlp', 'yt-dlp'), ('deno', 'deno')):
            target = self.bin / ('custom ' + name)
            (self.bin / name).rename(target)
            settings[key] = str(target)
            self.executable(name, '#!/bin/sh\nexit 1\n')
        settings.update(recovery_timeout=60, startup_timeout=68, proxy='http://localhost:8080')
        content = json.dumps(settings)
        path.write_text(content)
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(path.read_text(), content)
        self.assertEqual(self.doctor().returncode, 0, self.doctor().stdout)
        settings['startup_timeout'] = 38
        path.write_text(json.dumps(settings))
        self.assertEqual(self.doctor().returncode, 1)
        self.assertNotEqual(self.install().returncode, 0)

    def test_configured_paths_work_before_first_install(self):
        path = self.config / 'frameferry/config.json'
        path.parent.mkdir(parents=True)
        settings = {}
        for key, name in (('mpv', 'mpv'), ('yt_dlp', 'yt-dlp'), ('deno', 'deno')):
            target = self.bin / ('custom ' + name)
            (self.bin / name).rename(target)
            settings[key] = str(target)
            self.executable(name, '#!/bin/sh\nexit 1\n')
        path.write_text(json.dumps(settings))
        self.prepare()
        self.assertEqual(json.loads(path.read_text()), settings)
        self.assertEqual(self.doctor().returncode, 0, self.doctor().stdout)

    def test_browser_targets_and_custom_userdata(self):
        for browser, folder in (('chromium', 'chromium'), ('chrome', 'google-chrome'), ('brave', 'BraveSoftware/Brave-Browser')):
            self.assertEqual(self.install('install.sh', '--browser', browser).returncode, 0)
            self.assertTrue((self.config / folder / 'NativeMessagingHosts/frameferry.json').is_file())
        custom = self.home / 'browser data'
        self.assertEqual(self.install('install.sh', '--browser-data-dir', str(custom)).returncode, 0)
        self.assertTrue((custom / 'NativeMessagingHosts/frameferry.json').exists())

    def test_relative_xdg_directory_is_rejected(self):
        self.env['XDG_DATA_HOME'] = 'relative-data'
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'must be absolute paths', result.stderr)

    def test_sponsorblock_bundle_is_idempotent(self):
        for _ in range(2):
            result = self.install('install-mpv-sponsorblock.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.player / 'scripts/sponsorblock_shared/sponsorblock.py').is_file())
        self.assertEqual(list(self.player.rglob('*.backup.*')), [])

    def test_failed_download_preserves_sponsorblock(self):
        target = self.player / 'scripts/sponsorblock.lua'
        target.parent.mkdir(parents=True)
        target.write_text('working version')
        self.env['FAIL_DOWNLOAD'] = '/main.lua'
        self.assertNotEqual(self.install('install-mpv-sponsorblock.sh').returncode, 0)
        self.assertEqual(target.read_text(), 'working version')

    def test_bad_ui_checksum_preserves_existing_script(self):
        target = self.player / 'scripts/thumbfast.lua'
        target.parent.mkdir(parents=True)
        target.write_text('working version')
        result = self.install('install-mpv-ui.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Checksum mismatch', result.stderr)
        self.assertEqual(target.read_text(), 'working version')

    def test_existing_token_provider_does_not_clone_or_build(self):
        target = self.data / 'frameferry/bgutil'
        (target / 'server/build').mkdir(parents=True)
        (target / 'server/node_modules').mkdir()
        (target / 'server/build/generate_once.js').touch()
        self.executable('git', '#!/bin/sh\n[ "$3" = rev-parse ] || exit 1\necho 37169ee2656e08c5c2e5dc9df4c598c0cb4c88a8\n')
        self.executable('npm', '#!/bin/sh\nexit 1\n')
        self.assertEqual(self.install('install-mpv-token-provider.sh').returncode, 0)
