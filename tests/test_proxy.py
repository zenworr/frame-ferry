import io
import os
from pathlib import Path
import shutil
import signal
import ssl
import subprocess
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from helpers import load_script
from frameferry_config import DEFAULTS


@unittest.skipUnless(shutil.which('mpv') and shutil.which('openssl'), 'mpv and OpenSSL are required')
class ProxyTests(unittest.TestCase):
    def test_native_http_and_https_media_use_the_configured_proxy(self):
        native = load_script('frameferry-native')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=video.invalid', '-keyout', str(root / 'key.pem'),
                            '-out', str(root / 'cert.pem')], check=True, capture_output=True, timeout=10)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(root / 'cert.pem', root / 'key.pem')
            output = io.BytesIO()
            with wave.open(output, 'wb') as media:
                media.setnchannels(1)
                media.setsampwidth(2)
                media.setframerate(8000)
                media.writeframes(b'\0' * 16000)
            body = output.getvalue()
            requests = []

            class Proxy(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass

                def do_GET(self):
                    requests.append(self.path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'audio/wav')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def do_CONNECT(self):
                    requests.append('CONNECT ' + self.path)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.flush()
                    with context.wrap_socket(self.connection, server_side=True) as secured:
                        secured.settimeout(5)
                        with secured.makefile('rb') as reader:
                            line = reader.readline()
                            requests.append(line.decode().strip())
                            while reader.readline().strip():
                                pass
                            secured.sendall(f'HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)

            server = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            (root / 'mpv.conf').write_text('vo=null\nao=null\npause=yes\nkeep-open=yes\nytdl=no\ntls-verify=no\n')
            proxy = f'http://127.0.0.1:{server.server_port}'
            settings = DEFAULTS | {'proxy': proxy}
            processes = []
            popen = subprocess.Popen
            def spawn(*args, **kwargs):
                process = popen(*args, **kwargs)
                processes.append(process)
                return process
            with patch.object(native, 'CONFIG', root), patch.object(native, 'STATE', root / 'state'), \
                    patch.object(native, 'load_config', return_value=settings), \
                    patch.object(native.subprocess, 'Popen', side_effect=spawn), \
                    patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': '*', 'http_proxy': 'http://wrong.invalid:1'}):
                for scheme in ('http', 'https'):
                    with self.subTest(scheme=scheme):
                        reply = native.handle({'version': 1, 'action': 'play', 'url': f'{scheme}://video.invalid/fixture.wav',
                                               'position': None, 'quality': 0, 'fullscreen': False})
                        try:
                            self.assertTrue(reply['ok'])
                        finally:
                            os.kill(reply['pid'], signal.SIGTERM)
                            processes[-1].wait(timeout=5)
            self.assertIn('http://video.invalid:80/fixture.wav', requests)
            self.assertIn('CONNECT video.invalid:443', requests)
            self.assertIn('GET /fixture.wav HTTP/1.1', requests)
