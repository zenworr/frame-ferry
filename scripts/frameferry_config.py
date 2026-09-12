# SPDX-License-Identifier: MIT
"""Local configuration shared by Frame Ferry's native tools."""

import json
import math
import os
from pathlib import Path
import shutil
from urllib.parse import urlsplit

DEFAULTS = {'mpv': '', 'yt_dlp': '', 'deno': '', 'recovery_timeout': 30,
            'startup_timeout': 38, 'proxy': ''}
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
        if not isinstance(text, str) or (text and (not Path(text).is_absolute() or any(ord(c) < 32 for c in text))):
            raise ValueError(f'{key} must be an absolute executable path or an empty string.')
    for key, minimum, maximum in (('recovery_timeout', 10, 300), ('startup_timeout', 18, 600)):
        number = config[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f'{key} must be between {minimum} and {maximum} seconds.')
    if config['startup_timeout'] < config['recovery_timeout'] + 8:
        raise ValueError('startup_timeout must be at least 8 seconds longer than recovery_timeout.')
    proxy = config['proxy']
    valid = isinstance(proxy, str) and not any(c.isspace() or ord(c) < 32 for c in proxy)
    if valid and proxy:
        try:
            url = urlsplit(proxy)
            valid = (proxy.startswith('http://') and bool(url.hostname) and url.port != 0
                     and url.path in ('', '/') and not url.query and not url.fragment)
        except ValueError:
            valid = False
    if not valid:
        raise ValueError('proxy must be an http:// proxy URL or an empty string; HTTPS and SOCKS proxies are not supported.')
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


def proxy_environment(config):
    env = dict(os.environ)
    for key in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        env.pop(key, None)
        env.pop(key.upper(), None)
    if config['proxy']:
        # FFmpeg uses http_proxy for HTTPS CONNECT as well as plain HTTP.
        env['http_proxy'] = env['https_proxy'] = config['proxy']
    return env
