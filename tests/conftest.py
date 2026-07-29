from __future__ import annotations

import json
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Iterator
from urllib.parse import parse_qs, urlparse

import pytest

from phantom_curl.client import PhantomClient
from phantom_curl.models import StealthConfig
from phantom_curl.network.session import NetworkSession


class _TestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    flaky_requests = 0

    def log_message(self, format: str, *args: object) -> None:
        """Keep test output quiet."""

    def _send(self, status: int, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, status: int, data: object, **headers: str) -> None:
        self._send(status, json.dumps(data).encode(), "application/json", **headers)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/get":
            self._send_json(
                200,
                {
                    "args": {key: values[0] for key, values in parse_qs(parsed.query).items()},
                    "headers": {"User-Agent": self.headers.get("User-Agent")},
                },
            )
            return

        if parsed.path == "/cookies":
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            self._send_json(200, {name: morsel.value for name, morsel in cookies.items()})
            return

        if parsed.path == "/set-cookie":
            self._send_json(200, {"ok": True}, **{"Set-Cookie": "session_id=abc123; Path=/"})
            return

        if parsed.path == "/slow":
            time.sleep(0.2)
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/flaky":
            type(self).flaky_requests += 1
            attempt = type(self).flaky_requests
            status = 503 if attempt < 3 else 200
            self._send_json(status, {"attempt": attempt})
            return

        if parsed.path == "/redirect-page":
            self.send_response(302)
            self.send_header("Location", "/page/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if parsed.path == "/page/":
            body = b"""
                <html><body>
                    <script>document.body.setAttribute('inline-ran', 'yes');</script>
                    <script type="application/json">not valid JavaScript</script>
                    <script type="module">document.body.setAttribute('module-ran', 'yes');</script>
                    <script src="script.js"></script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/page/script.js":
            received_referer = "yes" if self.headers.get("Referer") else "no"
            body = f"document.body.setAttribute('external-ran', '{received_referer}');".encode()
            self._send(200, body, "text/javascript")
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/post":
            self._send_json(404, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        self._send_json(200, {"json": json.loads(body.decode())})


@pytest.fixture(scope="session")
def http_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def network_session() -> Iterator[NetworkSession]:
    session = NetworkSession(StealthConfig())
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def phantom_client() -> Iterator[PhantomClient]:
    client = PhantomClient()
    try:
        yield client
    finally:
        client.close()
