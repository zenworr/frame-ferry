import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from helpers import ExtractorFixture, load_script
import frameferry_config as config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'config.json'
        patcher = patch.object(config, 'config_path', return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_and_partial_configuration(self):
        self.assertEqual(config.load_config(), config.DEFAULTS)
        self.path.write_text('{"proxy": "http://127.0.0.1:8080"}')
        self.assertEqual(config.load_config()['proxy'], 'http://127.0.0.1:8080')
        self.assertEqual(config.load_config()['recovery_timeout'], 30)

    def test_invalid_configuration_is_rejected_without_exposing_secrets(self):
        for value in ([], {'other': True}, {'mpv': 'relative/path'}, {'deno': False},
                      {'yt_dlp': '/bad\npath'}, {'recovery_timeout': True}, {'recovery_timeout': 0},
                      {'recovery_timeout': float('nan')}, {'startup_timeout': float('inf')},
                      {'recovery_timeout': 60}, {'startup_timeout': 37},
                      {'proxy': None}, {'proxy': 'HTTP://host'}, {'proxy': 'http://host:invalid'}, {'proxy': 'http://host:0'},
                      {'proxy': 'http://host/path'}, {'proxy': 'http://host\n'},
                      {'proxy': 'https://user:secret@host'}, {'proxy': 'socks5://user:secret@host'}):
            self.path.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                config.load_config()
            self.assertNotIn('secret', str(error.exception))
        self.path.write_text('{')
        with self.assertRaises(ValueError):
            config.load_config()

    def test_executable_paths_do_not_fall_back_when_invalid(self):
        binary = self.path.with_name('custom player')
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
        settings = config.DEFAULTS | {'mpv': str(binary)}
        with patch.object(config.shutil, 'which', return_value='/other/mpv'):
            self.assertEqual(config.executable(settings, 'mpv'), str(binary))
            binary.chmod(0o644)
            with self.assertRaises(FileNotFoundError):
                config.executable(settings, 'mpv')
        with patch.object(config.shutil, 'which', return_value='/path/mpv'):
            self.assertEqual(config.executable(config.DEFAULTS, 'mpv'), '/path/mpv')
        with patch.object(config.shutil, 'which', return_value=None), patch.object(config.Path, 'home', return_value=self.path.parent):
            fallback = self.path.parent / '.local/bin/mpv'
            fallback.parent.mkdir(parents=True)
            fallback.symlink_to(sys.executable)
            self.assertEqual(config.executable(config.DEFAULTS, 'mpv'), str(fallback))

    def test_proxy_environment_is_consistent_and_does_not_change_parent(self):
        inherited = {'http_proxy': 'old', 'HTTP_PROXY': 'old', 'HTTPS_PROXY': 'old',
                     'ALL_PROXY': 'socks5://old', 'NO_PROXY': '*', 'no_proxy': '*', 'OTHER': 'keep'}
        with patch.dict(os.environ, inherited, clear=True):
            self.assertEqual(config.proxy_environment(config.DEFAULTS), {'OTHER': 'keep'})
            env = config.proxy_environment(config.DEFAULTS | {'proxy': 'http://localhost:8080'})
            self.assertEqual(env, {'OTHER': 'keep', 'http_proxy': 'http://localhost:8080',
                                  'https_proxy': 'http://localhost:8080'})
            self.assertEqual(dict(os.environ), inherited)

    def test_native_uses_configured_player_and_both_timeouts(self):
        native = load_script('frameferry-native')
        settings = config.DEFAULTS | {'mpv': sys.executable, 'recovery_timeout': 60, 'startup_timeout': 70,
                                      'proxy': 'http://localhost:8080'}
        self.path.write_text(json.dumps(settings))
        message = {'version': 1, 'action': 'play', 'url': 'https://example.org/video',
                   'position': None, 'quality': 0, 'fullscreen': False}
        command = native.command_for(message, Path('/tmp/ipc'))
        self.assertEqual(command[0], sys.executable)
        self.assertIn('--script-opts-append=youtube-recovery_timeout=60', command)
        self.path.with_name('mpv.conf').touch()
        with patch.object(native, 'CONFIG', self.path.parent), patch.object(native, 'STATE', self.path.parent / 'state'), \
                patch.object(native.subprocess, 'Popen') as spawn, patch.object(native.time, 'monotonic', return_value=100), \
                patch.object(native, 'wait_for_playback') as wait:
            native.handle(message)
            self.assertEqual(wait.call_args.args[2], 170)
            self.assertEqual(spawn.call_args.kwargs['env']['http_proxy'], settings['proxy'])
            self.assertNotIn('proxy', ' '.join(spawn.call_args.args[0]))
        with self.assertRaises(ValueError):
            native.validate(message | {'mpv': '/untrusted/executable'})


class WrapperConfigTests(ExtractorFixture):
    def settings(self, values):
        path = Path(self.env['XDG_CONFIG_HOME']) / 'frameferry/config.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values))

    def test_custom_executables_deno_proxy_and_network_timeout(self):
        custom = self.home / 'custom extractor'
        self.fake.rename(custom)
        self.settings({'yt_dlp': str(custom), 'deno': sys.executable, 'recovery_timeout': 60,
                       'startup_timeout': 68, 'proxy': 'http://localhost:8080'})
        result = self.run_wrapper('-J', '--', 'https://youtube.com/watch?v=fixture')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.calls()[0]
        self.assertIn('deno:' + sys.executable, args)
        self.assertEqual(args[args.index('--proxy') + 1], 'http://localhost:8080')
        self.assertEqual(float(args[args.index('--socket-timeout') + 1]), 10)

    def test_no_proxy_is_explicit_and_invalid_config_stops_extraction(self):
        self.env['HTTPS_PROXY'] = 'http://unwanted.invalid:8080'
        self.assertEqual(self.run_wrapper('-J', '--', 'https://example.org/video').returncode, 0)
        args = self.calls()[0]
        self.assertEqual(args[args.index('--proxy') + 1], '')
        self.settings({'proxy': 'socks5://user:secret@host'})
        result = self.run_wrapper('-J', '--', 'https://example.org/video')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b'secret', result.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_extended_recovery_scales_extraction_cap(self):
        wrapper = load_script('yt-dlp-mpv')
        settings = config.DEFAULTS | {'recovery_timeout': 90, 'startup_timeout': 98, 'deno': sys.executable}
        with patch.object(wrapper, 'load_config', return_value=settings), patch.object(wrapper, 'executable', return_value=sys.executable), \
                patch.object(wrapper, 'run_captured', return_value=(1, b'', b'')) as run, \
                patch.object(sys, 'argv', ['yt-dlp-mpv', '--frameferry-timeout=45', '-J', 'https://youtube.com/watch?v=fixture']), \
                patch.dict(os.environ):
            wrapper.main()
        self.assertEqual(run.call_args.args[1], 45)
