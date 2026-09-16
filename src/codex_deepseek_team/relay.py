"""Fixed-destination provider relay and namespace-local HTTP bridge.

The actual provider credential lives only in the host-side relay. The bridge is
also runnable as an isolated stdlib script; it has no access to package state.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
from urllib.parse import urlsplit

MAX_REQUEST = 64 * 1024 * 1024
ENDPOINTS = frozenset(('/responses', '/v1/responses', '/anthropic/v1/messages',
                       '/anthropic/v1/messages/count_tokens'))
LOCAL_CREDENTIAL = 'deepseek-team-isolated-client'


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__('localhost', timeout=30)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class _Handler(BaseHTTPRequestHandler):
    # Closing-delimited responses permit both JSON and streaming SSE without
    # retaining the entire provider response in memory or exposing raw logs.
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args):
        pass

    def do_POST(self):
        url = urlsplit(self.path)
        if (url.scheme or url.netloc or url.path not in ENDPOINTS or
                url.query not in ('', 'beta=true') or url.fragment):
            self.send_error(403, 'Endpoint not available')
            return
        try:
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('chunked requests not supported')
            size = int(self.headers.get('Content-Length', '-1'))
            if not 0 <= size <= MAX_REQUEST:
                raise ValueError('invalid request length')
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError('incomplete request')
        except ValueError:
            self.send_error(400, 'Invalid request length')
            return
        headers = {'Content-Type': 'application/json', 'Accept-Encoding': 'identity'}
        for name in ('anthropic-version', 'anthropic-beta', 'Accept'):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        connection = None
        started = False
        try:
            connection, auth = self.server.connection()
            headers.update(auth)
            connection.request('POST', self.path, body, headers)
            response = connection.getresponse()
            if connection.sock is not None:
                connection.sock.settimeout(None)  # silence is not a total timeout
            if response.status >= 400:
                self.server.failures.append(response.status)
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type', 'application/json'))
            self.end_headers()
            started = True
            while data := response.read1(65536):
                self.wfile.write(data)
                self.wfile.flush()
        except (OSError, http.client.HTTPException):
            self.server.failures.append(502)
            if not started:
                self.send_error(502, 'Provider transport unavailable')
        finally:
            if connection is not None:
                connection.close()

    def do_CONNECT(self):
        self.send_error(403, 'Tunnelling is not supported')


class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    block_on_close = False


class ProviderRelay(AbstractContextManager):
    """A per-run Unix capability, never a general HTTP proxy.

    ``upstream`` is dependency injection for offline tests only; production CLI
    never accepts an upstream URL, host, proxy, redirect or endpoint override.
    """
    def __init__(self, path: Path, credential: str,
                 upstream: tuple[str, str, int] = ('https', 'api.deepseek.com', 443)):
        self.path = Path(path)
        self.server = _UnixServer(str(self.path), _Handler)
        os.chmod(self.path, 0o600)
        self.failures: list[int] = []
        self.server.failures = self.failures
        scheme, host, port = upstream
        if scheme not in ('http', 'https'):
            self.server.server_close()
            self.path.unlink(missing_ok=True)
            raise ValueError('Unsupported provider transport')
        factory = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
        self.server.connection = lambda: (
            factory(host, port, timeout=30),
            {'Authorization': 'Bearer ' + credential, 'x-api-key': credential})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.path.unlink(missing_ok=True)


def bridge(config_file: str, socket_file: str) -> int:
    """Run inside bwrap: expose only the per-run relay on private loopback."""
    config = json.loads(Path(config_file).read_text())
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    server.daemon_threads = True
    server.failures = []
    server.connection = lambda: (UnixHTTPConnection(socket_file), {})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f'http://127.0.0.1:{server.server_port}'
    args = [part.replace('@DEEPSEEK_TEAM_ENDPOINT@', endpoint) for part in config['command']]
    env = {key: value.replace('@DEEPSEEK_TEAM_ENDPOINT@', endpoint)
           for key, value in config['env'].items()}
    try:
        # Same process group and namespace as the bridge. Parent cancellation or
        # PID-namespace teardown also kills tests/builds spawned by the runtime.
        return subprocess.call(args, env=env)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--bridge':
        raise SystemExit('This helper is launched by DeepSeek Team inside its OS sandbox.')
    raise SystemExit(bridge(sys.argv[2], sys.argv[3]))
