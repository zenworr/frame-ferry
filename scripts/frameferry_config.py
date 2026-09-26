# SPDX-License-Identifier: MIT
"""Local configuration shared by Frame Ferry's native tools."""

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

BASE_RECOVERY_TIMEOUT = 30
STARTUP_MARGIN = 8
MIN_PRINTABLE_CODEPOINT = 0x20
MEBIBYTE = 1024 * 1024
SECONDS_PER_HOUR = 60 * 60
VERSION_CHECK_TIMEOUT = 5
MINIMUM_VERSIONS = {'mpv': (0, 41), 'deno': (2, 0), 'yt_dlp': (2026, 8)}
DEFAULTS = {
    'mpv': '',
    'yt_dlp': '',
    'deno': '',
    'recovery_timeout': BASE_RECOVERY_TIMEOUT,
    'startup_timeout': BASE_RECOVERY_TIMEOUT + STARTUP_MARGIN,
    'proxy': '',
    'stall_timeout': 10,
    'http_chunk_size': MEBIBYTE,
    'log_retention': 20,
    'update_interval_hours': 24,
}
TIMEOUT_LIMITS = {'recovery_timeout': (10, 300), 'startup_timeout': (18, 600), 'stall_timeout': (3, 120)}
INTEGER_LIMITS = {'http_chunk_size': (0, 8 * MEBIBYTE), 'log_retention': (1, 1000), 'update_interval_hours': (1, 168)}
MIN_HTTP_CHUNK_SIZE = 64 * 1024
TOOLS = {'mpv': 'mpv', 'yt_dlp': 'yt-dlp', 'deno': 'deno'}


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'frameferry/config.json'


def load_config():
    path = config_path()
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        value = {}
    except (OSError, ValueError):
        raise ValueError('Cannot read Frame Ferry config.json as JSON.') from None
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise ValueError('Frame Ferry config.json has unknown settings or is not an object.')
    config = DEFAULTS | value
    for key in TOOLS:
        text = config[key]
        if not isinstance(text, str) or (
            text and (not Path(text).is_absolute() or any(ord(c) < MIN_PRINTABLE_CODEPOINT for c in text))
        ):
            raise ValueError(f'{key} must be an absolute executable path or an empty string.')
    for key, (minimum, maximum) in TIMEOUT_LIMITS.items():
        number = config[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f'{key} must be between {minimum} and {maximum} seconds.')
    for key, (minimum, maximum) in INTEGER_LIMITS.items():
        number = config[key]
        if type(number) is not int or not minimum <= number <= maximum:
            raise ValueError(f'{key} must be an integer between {minimum} and {maximum}.')
    if 0 < config['http_chunk_size'] < MIN_HTTP_CHUNK_SIZE:
        raise ValueError(f'http_chunk_size must be zero or at least {MIN_HTTP_CHUNK_SIZE} bytes.')
    if config['startup_timeout'] < config['recovery_timeout'] + STARTUP_MARGIN:
        raise ValueError(f'startup_timeout must be at least {STARTUP_MARGIN} seconds longer than recovery_timeout.')
    proxy = config['proxy']
    valid = isinstance(proxy, str) and not any(c.isspace() or ord(c) < MIN_PRINTABLE_CODEPOINT for c in proxy)
    if valid and proxy:
        try:
            url = urlsplit(proxy)
            valid = (
                proxy.startswith('http://')
                and bool(url.hostname)
                and url.port != 0
                and url.path in ('', '/')
                and not url.query
                and not url.fragment
            )
        except ValueError:
            valid = False
    if not valid:
        raise ValueError(
            'proxy must be an http:// proxy URL or an empty string; HTTPS and SOCKS proxies are not supported.'
        )
    return config


def executable(config, key):
    configured = config[key]
    if configured:
        if Path(configured).is_file() and os.access(configured, os.X_OK):
            return configured
        raise FileNotFoundError(f'The configured {key} executable is missing or not executable.')
    found = shutil.which(TOOLS[key])
    if found:
        return found
    fallback = Path.home() / '.local/bin' / TOOLS[key]
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    raise FileNotFoundError(f'{TOOLS[key]} was not found. Install it or set its path in Frame Ferry config.json.')


def supported_executable(config, key):
    path = executable(config, key)
    args = [path, '--version'] if key != 'yt_dlp' else [path, '--ignore-config', '--version']
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=VERSION_CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ValueError(f'{key} version check timed out.') from None
    match = re.search(r'(\d+)\.(\d+)', result.stdout)
    minimum = MINIMUM_VERSIONS[key]
    if result.returncode or not match or tuple(map(int, match.groups())) < minimum:
        version = '.'.join(map(str, minimum))
        raise ValueError(f'{key} {version} or newer is required.')
    return path


def proxy_environment(config):
    env = dict(os.environ)
    for key in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        env.pop(key, None)
        env.pop(key.upper(), None)
    if config['proxy']:
        # FFmpeg uses http_proxy for HTTPS CONNECT as well as plain HTTP.
        env['http_proxy'] = env['https_proxy'] = config['proxy']
    return env
