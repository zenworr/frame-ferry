"""Real mpv and wrapper with fake yt-dlp and loopback media. No browser or cookies."""

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .helpers import ROOT, wait_for

URL = 'https://youtu.be/offline'


class Player:
    def __init__(
        self, routes=None, duplicates=False, options=(), provider=True, url=URL, media_seconds=60, video_seconds=0
    ):
        self.temp = tempfile.TemporaryDirectory(prefix='mpv-test-')
        self.root = Path(self.temp.name)
        self.process = self.socket = self.reader = self.server = self.thread = None
        self.buffer_release = buffer_release = threading.Event()
        try:
            data = io.BytesIO()
            with wave.open(data, 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b'\0' * (media_seconds * 8000 * 2))
            audio_media = data.getvalue()
            video_media = b''
            if video_seconds:
                video = self.root / 'video.mp4'
                subprocess.run(
                    [
                        shutil.which('ffmpeg'),
                        '-v',
                        'error',
                        '-f',
                        'lavfi',
                        '-i',
                        'testsrc2=size=160x90:rate=10',
                        '-t',
                        str(video_seconds),
                        '-c:v',
                        'mpeg4',
                        '-q:v',
                        '3',
                        '-movflags',
                        '+faststart',
                        str(video),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=20,
                )
                video_media = video.read_bytes()
            self.requests = requests = []

            class Handler(BaseHTTPRequestHandler):
                protocol_version = 'HTTP/1.1'

                def handle(self):
                    try:
                        super().handle()
                    except ConnectionResetError:
                        pass

                def log_message(self, *_args):
                    pass

                def do_GET(self):
                    try:
                        if self.path == '/denied' or (
                            self.path == '/header' and self.headers.get('Referer') != 'https://example.test/retained'
                        ):
                            self.send_response(403)
                            self.send_header('Content-Length', '0')
                            self.end_headers()
                            return
                        if self.path == '/stall':
                            self.send_response(200)
                            self.send_header('Content-Length', '100000000')
                            self.end_headers()
                            while True:
                                self.wfile.write(b'0123456789')
                                self.wfile.flush()
                                time.sleep(0.1)
                        media = video_media if self.path.endswith('video.mp4') else audio_media
                        requested = self.headers.get('Range', 'bytes=0-')
                        requests.append((requested, self.client_address[1]))
                        first, last = requested.split('=')[1].split('-')
                        start = int(first)
                        end = min(int(last), len(media) - 1) if last else len(media) - 1
                        broken = self.path == '/broken-video.mp4'
                        cutoff = len(media) // 16
                        if broken and start >= cutoff:
                            self.send_response(403)
                            self.send_header('Content-Length', '0')
                            self.end_headers()
                            return
                        self.send_response(206)
                        self.send_header(
                            'Content-Type', 'video/mp4' if self.path.endswith('video.mp4') else 'audio/wav'
                        )
                        self.send_header('Content-Length', str(end - start + 1))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.send_header('Content-Range', f'bytes {start}-{end}/{len(media)}')
                        self.end_headers()
                        if self.path == '/buffer' and 1024 * 1024 <= start < len(media) - 65536:
                            buffer_release.wait()
                        if broken:
                            self.wfile.write(media[start : min(end + 1, cutoff)])
                            self.close_connection = True
                        else:
                            self.wfile.write(media[start : end + 1])
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.thread = threading.Thread(
                target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True
            )
            self.thread.start()
            self.routes = self.root / 'routes.json'
            self.routes.write_text(json.dumps(routes or {}))
            self.extractor = self.root / 'yt-dlp'
            self.extractor.write_text(
                f'#!{sys.executable}\n'
                + f"""import json, sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
root = Path({str(self.root)!r})
args = ' '.join(sys.argv[1:])
if 'use_ad_playback_context=true' in args:
    route = 'fallback'
elif 'player_client=mweb' in args:
    route = 'token'
elif 'protocol=m3u8_native' in args:
    route = 'fallback' if 'height<=?1080' in args else 'hls'
else:
    route = 'authenticated' if '--cookies' in args else 'primary'
with (root/'calls').open('a') as f: f.write(route+'\\n')
routes = json.loads((root/'routes.json').read_text())
action = routes.get(route, routes.get('*', 'play'))
if action == 'fail':
    print('ERROR: Sign in to confirm', file=sys.stderr)
    sys.exit(1)
info = {{'id':'offline', 'title':'Offline fixture', 'extractor_key':'Youtube', 'width':3840, 'height':2160}}
query = parse_qs(urlsplit(sys.argv[-1]).query)
if 't' in query: info['start_time'] = float(query['t'][0])
if isinstance(action, dict):
    info.update(action)
    action = info.pop('media', 'audio.wav')
base = 'http://127.0.0.1:{self.server.server_port}/'
info['url'] = base + (action if action in ('stall', 'denied', 'header', 'buffer', 'video.mp4', 'broken-video.mp4') else 'audio.wav')
if info.pop('split', False):
    info['requested_formats'] = [
        {{'url': info['url'], 'protocol': 'http', 'ext': 'mp4', 'vcodec': 'mpeg4', 'acodec': 'none'}},
        {{'url': base + 'audio.wav', 'protocol': 'http', 'ext': 'wav', 'vcodec': 'none', 'acodec': 'pcm_s16le'}}]
print(json.dumps(info))
"""
            )
            self.extractor.chmod(0o755)
            (self.root / 'deno').symlink_to(sys.executable)
            state = self.root / '.local/state/frameferry'
            state.mkdir(parents=True)
            (state / 'yt-dlp-update.lock').write_text(str(time.time() + 86400))
            if provider:
                build = self.root / '.local/share/frameferry/bgutil/server/build'
                build.mkdir(parents=True)
                (build / 'generate_once.js').touch()
            guard = self.root / 'network-guard.lua'
            guard.write_text("""mp.add_hook('on_load', 30, function()
    mp.set_property_bool('user-data/test/ready', false)
    local path = mp.get_property('stream-open-filename', '')
    if not path:find('http://127.0.0.1:', 1, true) and not path:match('^av://lavfi:') then
        mp.set_property('stream-open-filename', 'memory://offline-load-failure')
    end
end)
mp.register_event('playback-restart', function()
    mp.set_property_bool('user-data/test/ready', true)
end)
mp.observe_property('user-data/youtube-quality/active', 'native', function()
    mp.set_property_bool('user-data/test/active-bool', mp.get_property_bool('user-data/youtube-quality/active', false))
end)
""")
            browser = self.root / 'xdg-open'
            browser.write_text(
                f'#!{sys.executable}\nfrom pathlib import Path\nimport sys\n'
                f'Path({str(self.root / "browser-url")!r}).write_text(sys.argv[1])\n'
            )
            browser.chmod(0o755)
            self.log = self.root / 'mpv.log'
            self.output = self.log.open('wb')
            ipc = self.root / 'ipc'
            command = [
                shutil.which('mpv'),
                '--no-config',
                '--vo=null',
                '--ao=null',
                '--load-scripts=no',
                '--idle=yes',
                '--keep-open=yes',
                '--terminal=yes',
                '--input-terminal=no',
                '--term-status-msg=',
                '--term-osd=no',
                f'--input-ipc-server={ipc}',
                f'--script={ROOT}/config/mpv/scripts/youtube.lua',
                f'--script={guard}',
                f'--script-opts=youtube-cookies_browser=chromium:fixture,ytdl_hook-ytdl_path={ROOT}/scripts/yt-dlp-mpv',
                '--ytdl-format=bestvideo[height<=?2160]+bestaudio/best[height<=?2160]',
                *options,
                '--',
                url,
            ]
            if duplicates:
                command.append(url)
            env = {
                **os.environ,
                'HOME': str(self.root),
                'TMPDIR': str(self.root),
                'XDG_STATE_HOME': str(self.root / '.local/state'),
                'XDG_DATA_HOME': str(self.root / '.local/share'),
                'XDG_CONFIG_HOME': str(self.root / '.config'),
                'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
            }
            self.started = time.monotonic()
            self.process = subprocess.Popen(
                command, env=env, stdin=subprocess.DEVNULL, stdout=self.output, stderr=subprocess.STDOUT
            )
            self.wait(lambda: ipc.exists() or self.process.poll() is not None)
            if self.process.poll() is not None:
                raise RuntimeError(self.log.read_text(errors='replace'))
            self.socket = socket.socket(socket.AF_UNIX)
            self.socket.settimeout(5)
            self.socket.connect(str(ipc))
            self.reader = self.socket.makefile('rb')
            self.sequence = 0
        except BaseException:
            self.close()
            raise

    def command(self, *command):
        self.sequence += 1
        self.socket.sendall(json.dumps({'command': command, 'request_id': self.sequence}).encode() + b'\n')
        while True:
            line = self.reader.readline()
            if not line:
                raise RuntimeError(self.log.read_text(errors='replace'))
            result = json.loads(line)
            if result.get('request_id') == self.sequence:
                return result

    def get(self, name):
        return self.command('get_property', name).get('data')

    def wait(self, predicate, timeout=5):
        try:
            return wait_for(predicate, timeout)
        except AssertionError as error:
            raise AssertionError(self.log.read_text(errors='replace')) from error

    def wait_loaded(self, route):
        self.wait(
            lambda: (
                self.get('user-data/youtube-quality/route') == route
                and self.get('user-data/youtube-quality/loading') is False
                and self.get('duration') is not None
                and self.get('user-data/test/ready')
            )
        )

    def close(self):
        self.buffer_release.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.reader:
            self.reader.close()
        if self.socket:
            self.socket.close()
        if hasattr(self, 'output'):
            self.output.close()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
        self.temp.cleanup()
