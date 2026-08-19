from __future__ import annotations

import json
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Callable, Iterator
from urllib.parse import parse_qs, urlparse

import pytest

from phantom_curl.client import PhantomClient
from phantom_curl.models import StealthConfig
from phantom_curl.network.session import NetworkSession


class _TestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    flaky_requests = 0
    flaky_override_requests = 0
    math_module_requests = 0
    abortable_requests = 0

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

        if parsed.path == "/set-http-only-cookie":
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "visible=yes; Path=/")
            self.send_header("Set-Cookie", "hidden=no; Path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/value":
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            self._send_json(
                200,
                {
                    "value": "from-api",
                    "referer": self.headers.get("Referer"),
                    "cookies": {name: morsel.value for name, morsel in cookies.items()},
                },
            )
            return

        if parsed.path == "/api/set-cookie":
            self._send_json(200, {"ok": True}, **{"Set-Cookie": "from_fetch=yes; Path=/"})
            return

        if parsed.path == "/api/response-headers":
            self._send_json(200, {"ok": True}, **{"X-Response-Id": "abc123"})
            return

        if parsed.path == "/api/abortable":
            type(self).abortable_requests += 1
            self._send_json(200, {"ok": True})
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

        if parsed.path == "/flaky-override":
            type(self).flaky_override_requests += 1
            attempt = type(self).flaky_override_requests
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

        if parsed.path == "/current-script-page/":
            body = b"""
                <html><body>
                    <script>
                        const currentScript = document.currentScript;
                        const baseUrl = new URL(".", location);
                        document.body.setAttribute("current-script-parent", currentScript.parentElement.tagName);
                        document.body.setAttribute("resolved-base-url", baseUrl.href);
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/page/script.js":
            received_referer = "yes" if self.headers.get("Referer") else "no"
            body = f"document.body.setAttribute('external-ran', '{received_referer}');".encode()
            self._send(200, body, "text/javascript")
            return

        if parsed.path == "/fetch-page/":
            body = b"""
                <html><body>
                    <script>
                        fetch('/api/value')
                            .then(response => response.json())
                            .then(data => document.body.setAttribute('fetch-value', data.value));
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/timer-page/":
            body = b"""
                <html><body>
                    <script>
                        queueMicrotask(() => document.body.setAttribute('microtask-ran', 'yes'));
                        setTimeout(() => document.body.setAttribute('timeout-ran', 'yes'), 0);
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/module-page/":
            body = b"""
                <html><body>
                    <script type="module">
                        import { answer } from '../modules/math.js';
                        document.body.setAttribute('first-module-answer', String(answer));
                    </script>
                    <script type="module">
                        import { answer as secondAnswer } from '../modules/math.js';
                        document.body.setAttribute('second-module-answer', String(secondAnswer));
                    </script>
                    <script type="module">
                        import moduleName, * as math from '../modules/math.js';
                        document.body.setAttribute('module-default-and-namespace', moduleName + ':' + math.answer);
                    </script>
                    <script type="module" src="../modules/external.js"></script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/cycle-module-page/":
            body = b"""
                <html><body>
                    <script type="module">
                        import { a } from '../modules/a.js';
                        document.body.setAttribute('cycle-module-answer', a);
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/missing-module-page/":
            body = b"""
                <html><body>
                    <script type="module">import '../modules/missing.js';</script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/modules/math.js":
            type(self).math_module_requests += 1
            self._send(200, b"export const answer = 42;\nexport default 'math';", "text/javascript")
            return

        if parsed.path == "/modules/external.js":
            self._send(200, b"document.body.setAttribute('external-module-ran', 'yes');", "text/javascript")
            return

        if parsed.path == "/modules/cross-origin-entry.js":
            self._send(
                200,
                (
                    b"import { marker } from './cross-origin-dependency.js';"
                    b"document.body.setAttribute('cross-origin-module-ran', marker);"
                ),
                "text/javascript",
            )
            return

        if parsed.path == "/modules/cross-origin-dependency.js":
            self._send(200, b"export const marker = 'yes';", "text/javascript")
            return

        if parsed.path == "/modules/a.js":
            self._send(200, b"import './b.js'; export const a = 'a';", "text/javascript")
            return

        if parsed.path == "/modules/b.js":
            self._send(200, b"import './a.js'; export const b = 'b';", "text/javascript")
            return

        if parsed.path == "/dynamic-script-page/":
            body = b"""
                <html><body>
                    <script>
                        const script = document.createElement("script");
                        script.src = "/dynamic-script.js";
                        document.head.appendChild(script);
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/dynamic-script.js":
            body = b"document.body.setAttribute('dynamic-script-ran', 'yes');"
            self._send(200, body, "text/javascript")
            return

        if parsed.path == "/dynamic-script-chain-page/":
            body = b"""
                <html><body>
                    <script>
                        const firstScript = document.createElement("script");
                        firstScript.src = "/dynamic-script-first.js";
                        document.head.appendChild(firstScript);
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/dynamic-script-first.js":
            body = b"""
                document.body.setAttribute('first-dynamic-script-ran', 'yes');
                const secondScript = document.createElement('script');
                secondScript.src = '/dynamic-script-second.js';
                document.head.appendChild(secondScript);
            """
            self._send(200, body, "text/javascript")
            return

        if parsed.path == "/dynamic-script-second.js":
            body = b"document.body.setAttribute('second-dynamic-script-ran', 'yes');"
            self._send(200, body, "text/javascript")
            return

        if parsed.path == "/dynamic-script-relative-page/":
            body = b"""
                <html><body>
                    <script>
                        const script = document.createElement("script");
                        script.src = "assets/relative.js";
                        document.head.appendChild(script);
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/dynamic-script-relative-page/assets/relative.js":
            body = b"document.body.setAttribute('relative-dynamic-script-ran', 'yes');"
            self._send(200, body, "text/javascript")
            return

        if parsed.path == "/dynamic-script-error-page/":
            body = b"""
                <html><body>
                    <script>
                        const script = document.createElement("script");
                        script.src = "/dynamic-script-error.js";
                        document.head.appendChild(script);
                    </script>
                </body></html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/dynamic-script-error.js":
            body = b"throw new Error('dynamic script failure');"
            self._send(200, body, "text/javascript")
            return

        if parsed.path == "/broken-page/":
            body = b"<html><body><script>throw new Error('test script failure');</script></body></html>"
            self._send(200, body, "text/html")
            return

        if parsed.path == "/elements/":
            body = b"""
                <html>
                    <head><title>Element fixture</title></head>
                    <body>
                        <input id="name" class="field" data-kind="name">
                        <button id="action">Run</button>
                        <p class="item">First</p><p class="item">Second</p>
                        <script>
                            const input = document.getElementById('name');
                            const button = document.getElementById('action');
                            input.addEventListener('input', () => document.body.setAttribute('input-value', input.value));
                            button.addEventListener('click', () => document.body.setAttribute('clicked', 'yes'));
                            button.addEventListener('custom-event', () => document.body.setAttribute('custom-event', 'yes'));
                        </script>
                    </body>
                </html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/button":
            body = b"""
                <html>
                    <body>
                        <button id="basic-button">Button</button>
                        <script>
                            const button = document.getElementById('basic-button');
                            button.addEventListener('click', () => {
                                const script = document.createElement('script');
                                script.src = '/after-click.js';
                                document.head.appendChild(script);
                            });
                        </script>
                    </body>
                </html>
            """
            self._send(200, body, "text/html")
            return

        if parsed.path == "/after-click.js":
            body = b"document.body.setAttribute('after-click-script-ran', 'yes');"
            self._send(200, body, "text/javascript")
            return

        if parsed.path == "/interaction-queue/":
            body = b"""
                <html>
                    <body>
                        <input id="queue-input">
                        <button id="queue-work">Queue work</button>
                        <script>
                            const input = document.getElementById('queue-input');
                            const button = document.getElementById('queue-work');
                            input.addEventListener('input', () => {
                                fetch('/api/value')
                                    .then(response => response.json())
                                    .then(data => document.body.setAttribute('input-fetch-value', data.value));
                            });
                            button.addEventListener('click', () => {
                                document.body.setAttribute('click-handler-ran', 'yes');
                                fetch('/api/value')
                                    .then(response => response.json())
                                    .then(data => document.body.setAttribute('fetch-value', data.value));
                                setTimeout(() => document.body.setAttribute('timer-ran', 'yes'), 0);
                            });
                            button.addEventListener('queued-event', () => {
                                setTimeout(() => document.body.setAttribute('custom-event-timer-ran', 'yes'), 0);
                            });
                        </script>
                    </body>
                </html>
            """
            self._send(200, body, "text/html")
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/echo":
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            self._send_json(
                200,
                {
                    "body": body.decode(),
                    "header": self.headers.get("X-Page"),
                    "content_type": self.headers.get("Content-Type"),
                    "referer": self.headers.get("Referer"),
                    "cookies": {name: morsel.value for name, morsel in cookies.items()},
                },
            )
            return

        if path != "/post":
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


@pytest.fixture(scope="session")
def cross_origin_server() -> Iterator[str]:
    """Start the same test handler on another origin (a different port)."""
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


@pytest.fixture(autouse=True)
def reset_flaky_request_counts() -> None:
    _TestHandler.flaky_requests = 0
    _TestHandler.flaky_override_requests = 0
    _TestHandler.math_module_requests = 0
    _TestHandler.abortable_requests = 0


@pytest.fixture
def math_module_request_count() -> Callable[[], int]:
    """Return how many times the math module fixture was requested."""
    return lambda: _TestHandler.math_module_requests


@pytest.fixture
def abortable_request_count() -> Callable[[], int]:
    """Return how many requests reached the abortable fetch fixture."""
    return lambda: _TestHandler.abortable_requests
