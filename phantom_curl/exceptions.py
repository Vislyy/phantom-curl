"""
phantom_curl.exceptions
========================

Centralized exception hierarchy for the PhantomCurl library.

The hierarchy design allows the library user to:
    - catch every PhantomCurl error with a single `except PhantomError`;
    - catch errors from a specific layer (Network / Engine / Bridge / Stealth);
    - catch the most specific exception when fine-grained handling is needed.

Hierarchy overview:

PhantomError
├── NetworkError
│   ├── TLSRejectError
│   ├── RequestTimeoutError
│   └── ConnectionRejectedError
├── EngineError
│   ├── EngineInitError
│   ├── DOMBuildError
│   └── JSRuntimeError
├── BridgeError
│   ├── InterceptorError
│   └── EventLoopError
└── StealthError
    ├── FingerprintInjectionError
    └── CaptchaError
        ├── CaptchaSolveError
        └── CaptchaServiceError
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "PhantomError",
    "NetworkError",
    "TLSRejectError",
    "RequestTimeoutError",
    "ConnectionRejectedError",
    "EngineError",
    "EngineInitError",
    "DOMBuildError",
    "StaleElementError",
    "JSRuntimeError",
    "BridgeError",
    "InterceptorError",
    "EventLoopError",
    "StealthError",
    "FingerprintInjectionError",
    "CaptchaError",
    "CaptchaSolveError",
    "CaptchaServiceError",
]


class PhantomError(Exception):
    """
    Base exception for all PhantomCurl library errors.

    Every custom exception in the library inherits from this class,
    allowing users to write a single universal handler:

        try:
            client.get("https://example.com")
        except PhantomError as e:
            logger.error(f"PhantomCurl error: {e}")

    Attributes:
        message: Human-readable error message.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

class NetworkError(PhantomError):
    """
    Base exception for network layer errors (network/session.py).

    Raised for any HTTP/TLS transport-level issues: dropped connections,
    timeouts, requests rejected by the server, etc.
    """

class HTTPError(NetworkError):
    """
    Raised for HTTP response status codes in the 4xx or 5xx range.

    Attributes:
        status_code: The HTTP status code of the response.
        url: The URL that was requested.
    """

    def __init__(self, message: str, status_code: Optional[int] = None, url: Optional[str] = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message)

class TLSRejectError(NetworkError):
    """
    The server rejected the connection/request, likely due to detecting
    a suspicious TLS/JA3 fingerprint (e.g. a WAF recognized that this
    is not a genuine browser).

    Attributes:
        status_code: HTTP status code of the response, if the server
            managed to return one (e.g. 403 Forbidden from Cloudflare).
        impersonate: The curl_cffi impersonation profile used for the
            request (e.g. "chrome120").
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        impersonate: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.impersonate = impersonate
        super().__init__(message)


class RequestTimeoutError(NetworkError):
    """
    The request did not receive a response within the allotted timeout.

    Attributes:
        timeout: The timeout value (in seconds) that was exceeded.
        url: The URL the request was sent to.
    """

    def __init__(
        self,
        message: str,
        timeout: Optional[float] = None,
        url: Optional[str] = None,
    ) -> None:
        self.timeout = timeout
        self.url = url
        super().__init__(message)


class ConnectionRejectedError(NetworkError):
    """
    Failed to establish a connection with the server (DNS resolution
    failure, connection refused, proxy issues, etc.).

    Attributes:
        url: The URL the connection attempt was made to.
    """

    def __init__(self, message: str, url: Optional[str] = None) -> None:
        self.url = url
        super().__init__(message)

class EngineError(PhantomError):
    """
    Base exception for JS engine errors
    (engine/context.py, engine/dom_builder.py).

    Covers issues with QuickJS initialization, loading the Domino bundle,
    and executing JS code inside the sandbox.
    """

class EngineInitError(EngineError):
    """
    Failed to initialize the JS engine: an error occurred while creating
    the QuickJS context or loading the Domino bundle (domino.js) into
    the sandbox.
    """

class DOMBuildError(EngineError):
    """
    An error occurred while building the DOM tree from the fetched HTML
    using Linkedom.

    Attributes:
        html_snippet: The HTML fragment where the failure occurred
            (useful for diagnostics).
    """

    def __init__(self, message: str, html_snippet: Optional[str] = None) -> None:
        self.html_snippet = html_snippet
        super().__init__(message)

class StaleElementError(EngineError):
    """
    Raised when an Element object is accessed after it has become stale.

    This usually happens when the DOM has been replaced (for example, after
    calling `Page.goto()`), making all previously obtained Element instances
    invalid.
    """

    def __init__(
        self,
        message: str,
        selector: str,
        created_url: Optional[str],
        current_url: Optional[str],
        created_generation: int,
        current_generation: int,
    ) -> None:
        self.selector = selector
        self.created_url = created_url
        self.current_url = current_url
        self.created_generation = created_generation
        self.current_generation = current_generation
        super().__init__(message)

class JSRuntimeError(EngineError):
    """
    An error occurred while executing JavaScript code inside the QuickJS
    context (syntax error, thrown JS exception, stack overflow, etc.).

    Attributes:
        js_stack: The JavaScript-side stack trace, if it could be
            retrieved from QuickJS.
        source: The JS code fragment that caused the error.
    """

    def __init__(
        self,
        message: str,
        js_stack: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        self.js_stack = js_stack
        self.source = source
        super().__init__(message)

class BridgeError(PhantomError):
    """
    Base exception for errors in the bridge between the JS environment
    and Python (bridge/interceptor.py, bridge/event_loop.py).
    """


class InterceptorError(BridgeError):
    """
    An error occurred while intercepting and processing a fetch()/XHR
    call from JS code (e.g. invalid request parameters passed from
    JS to Python).

    Attributes:
        js_call: A string representation of the JS-side call
            (for diagnostics).
    """

    def __init__(self, message: str, js_call: Optional[str] = None) -> None:
        self.js_call = js_call
        super().__init__(message)


class EventLoopError(BridgeError):
    """
    An error occurred while simulating asynchronous timers
    (setTimeout/setInterval) or the microtask queue (Promise) inside
    the QuickJS environment.
    """

class StealthError(PhantomError):
    """
    Base exception for stealth layer errors
    (stealth/fingerprint.py, stealth/captcha.py).
    """


class FingerprintInjectionError(StealthError):
    """
    Failed to apply a JS injection intended to spoof a browser
    fingerprint (Canvas, WebGL, Navigator, etc.).

    Attributes:
        target: The name of the API that was being spoofed
            (e.g. "WebGLRenderingContext").
    """

    def __init__(self, message: str, target: Optional[str] = None) -> None:
        self.target = target
        super().__init__(message)


class CaptchaError(StealthError):
    """
    Base exception for all captcha-solving related errors.
    """


class CaptchaSolveError(CaptchaError):
    """
    The captcha-solving service returned an unsuccessful result
    (failed to recognize the captcha, retry limit exhausted, etc.).

    Attributes:
        captcha_type: The captcha type (e.g. "recaptcha_v2", "hcaptcha").
        attempts: The number of attempts after which solving was
            declared unsuccessful.
    """

    def __init__(
        self,
        message: str,
        captcha_type: Optional[str] = None,
        attempts: Optional[int] = None,
    ) -> None:
        self.captcha_type = captcha_type
        self.attempts = attempts
        super().__init__(message)


class CaptchaServiceError(CaptchaError):
    """
    An error occurred while interacting with an external captcha-solving
    API (2Captcha, CapSolver, etc.): invalid API key, exhausted balance,
    service unavailable, etc.

    Attributes:
        service_name: The service name (e.g. "2captcha").
        status_code: The HTTP status code returned by the service API,
            if available.
    """

    def __init__(
        self,
        message: str,
        service_name: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.service_name = service_name
        self.status_code = status_code
        super().__init__(message)
