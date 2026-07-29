"""
phantom_curl.models
=====================

Data classes representing structured data used across PhantomCurl.

Classes in this module fall into two categories:

1. Passive data structures (Cookie, RequestOptions, Response,
   StealthConfig) — immutable (frozen) containers with no behavior
   dependent on external state.

2. Active proxy objects (Element) — wrappers around live JS engine
   objects, whose methods perform real operations through the Bridge
   Layer. Such classes live outside this module (see engine/), since
   they require a reference to an active QuickJS context.
"""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, FrozenSet, Mapping, Optional
from urllib.parse import quote

from phantom_curl.utils import CaseInsensitiveDict
from phantom_curl.exceptions import HTTPError


def _freeze_value(value: Any) -> Any:
    """Recursively freeze JSON-like values stored in request models."""
    if isinstance(value, MappingABC):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    return value

@dataclass(frozen=True, slots=True)
class Cookie:
    """
    An immutable representation of a single HTTP cookie.

    Unlike a plain `name -> value` mapping, this model preserves the
    full set of attributes carried by a `Set-Cookie` header. This is
    necessary for two reasons:

    1. Correctly deciding whether a cookie should be sent with a given
       request, based on its `domain`, `path`, and `secure` attributes.
    2. Exporting/importing session state (see StorageState, planned),
       so a user can persist a scraping session to disk and restore it
       later without losing cookie semantics.

    Attributes:
        name: Cookie name.
        value: Cookie value.
        domain: The domain the cookie is scoped to. None means the
            cookie was not explicitly scoped (host-only cookie).
        path: The URL path the cookie is scoped to. Defaults to "/".
        expires: Expiration time as a Unix timestamp. None means a
            session cookie (expires when the session ends).
        secure: Whether the cookie should only be sent over HTTPS.
        http_only: Whether the cookie is inaccessible to JavaScript
            (via document.cookie).
        same_site: The SameSite policy ("Lax", "Strict", "None"),
            or None if not specified by the server.
    """

    name: str
    value: str
    domain: Optional[str] = None
    path: str = "/"
    expires: Optional[float] = None
    secure: bool = False
    http_only: bool = False
    same_site: Optional[str] = None


@dataclass(frozen=True, slots=True)
class StorageState:
    """A serializable snapshot of the cookies in a client session."""

    cookies: tuple[Cookie, ...] = ()

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        """Return a JSON-compatible representation of this state."""
        return {
            "cookies": [
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "expires": cookie.expires,
                    "secure": cookie.secure,
                    "http_only": cookie.http_only,
                    "same_site": cookie.same_site,
                }
                for cookie in self.cookies
            ]
        }

    def to_json(self) -> str:
        """Serialize this state without performing any filesystem I/O."""
        import json

        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StorageState":
        """Create a state snapshot from a validated JSON-like mapping."""
        raw_cookies = data.get("cookies")
        if not isinstance(raw_cookies, list):
            raise ValueError("Storage state must contain a 'cookies' list.")

        cookies: list[Cookie] = []
        for raw_cookie in raw_cookies:
            if not isinstance(raw_cookie, MappingABC):
                raise ValueError("Every cookie in storage state must be an object.")

            name = raw_cookie.get("name")
            value = raw_cookie.get("value")
            domain = raw_cookie.get("domain")
            path = raw_cookie.get("path", "/")
            expires = raw_cookie.get("expires")
            same_site = raw_cookie.get("same_site")
            secure = raw_cookie.get("secure", False)
            http_only = raw_cookie.get("http_only", False)

            if not isinstance(name, str) or not name:
                raise ValueError("Every stored cookie must have a non-empty string name.")
            if not isinstance(value, str):
                raise ValueError("Every stored cookie must have a string value.")
            if domain is not None and not isinstance(domain, str):
                raise ValueError("Cookie domain must be a string or null.")
            if not isinstance(path, str) or not path.startswith("/"):
                raise ValueError("Cookie path must be an absolute path.")
            if expires is not None and (isinstance(expires, bool) or not isinstance(expires, (int, float))):
                raise ValueError("Cookie expiry must be a number or null.")
            if same_site is not None and not isinstance(same_site, str):
                raise ValueError("Cookie SameSite value must be a string or null.")
            if not isinstance(secure, bool) or not isinstance(http_only, bool):
                raise ValueError("Cookie secure and http_only flags must be booleans.")

            cookies.append(
                Cookie(
                    name=name,
                    value=value,
                    domain=domain,
                    path=path,
                    expires=float(expires) if expires is not None else None,
                    secure=secure,
                    http_only=http_only,
                    same_site=same_site,
                )
            )

        return cls(cookies=tuple(cookies))

    @classmethod
    def from_json(cls, serialized: str) -> "StorageState":
        """Deserialize state exported by :meth:`to_json`."""
        import json

        try:
            data = json.loads(serialized)
        except json.JSONDecodeError as error:
            raise ValueError("Storage state is not valid JSON.") from error
        if not isinstance(data, MappingABC):
            raise ValueError("Storage state JSON must contain an object.")
        return cls.from_dict(data)


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Policy for retrying transient request failures in a network session."""

    max_attempts: int = 1
    backoff_factor: float = 0.25
    retry_status_codes: FrozenSet[int] = frozenset({408, 429, 500, 502, 503, 504})
    allowed_methods: FrozenSet[str] = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts must be an integer greater than or equal to 1.")
        if isinstance(self.backoff_factor, bool) or not isinstance(self.backoff_factor, (int, float)):
            raise ValueError("backoff_factor must be a non-negative number.")
        if self.backoff_factor < 0:
            raise ValueError("backoff_factor cannot be negative.")

        status_codes = frozenset(self.retry_status_codes)
        if any(isinstance(code, bool) or not isinstance(code, int) or not 100 <= code <= 599 for code in status_codes):
            raise ValueError("retry_status_codes must contain valid HTTP status codes.")

        if any(not isinstance(method, str) for method in self.allowed_methods):
            raise ValueError("allowed_methods must contain HTTP method names as strings.")
        methods = frozenset(method.upper() for method in self.allowed_methods)
        if not methods or any(not method.isalpha() for method in methods):
            raise ValueError("allowed_methods must contain one or more HTTP method names.")

        object.__setattr__(self, "retry_status_codes", status_codes)
        object.__setattr__(self, "allowed_methods", methods)

    def should_retry_status(self, method: str, status_code: int) -> bool:
        """Return whether a response status qualifies for another attempt."""
        return method.upper() in self.allowed_methods and status_code in self.retry_status_codes

    def delay_for_retry(self, retry_number: int) -> float:
        """Return exponential backoff delay for the given one-based retry number."""
        return self.backoff_factor * (2 ** (retry_number - 1))


@dataclass(frozen=True, slots=True)
class RequestOptions:
    """
    An immutable description of a single HTTP request to be performed.

    This model exists to avoid passing a long, ever-growing list of
    positional/keyword arguments through the codebase. It serves as a
    single request "envelope" that is used in two directions:

    - `PhantomClient` builds a `RequestOptions` and hands it to the
      Network Layer (network/session.py) to perform a real request.
    - The Bridge Layer (bridge/interceptor.py) builds a `RequestOptions`
      from an intercepted JS `fetch()`/`XMLHttpRequest` call and passes
      it to the Network Layer the same way, so both code paths converge
      on the same execution logic.

    Attributes:
        method: HTTP method (e.g. "GET", "POST").
        url: Target URL of the request.
        headers: Request headers.
        params: Query string parameters to append to the URL.
        data: Raw or form-encoded request body.
        json_body: Request body to be JSON-encoded. Named `json_body`
            instead of `json` to avoid shadowing the standard `json`
            module inside this file and in code that imports this class.
        timeout: Request timeout in seconds.
        allow_redirects: Whether to automatically follow HTTP redirects.
        verify: Either a boolean, in which case it controls whether we verify
            the server's TLS/SSL certificate, or a string, in which case it 
            must be a path to a CA bundle to use. Defaults to True.
        proxy: A dictionary mapping protocol schemes (e.g., "http", "https")
            to the URL of the proxy server to route the request through (e.g.,
            {"http": "http://10.10.1.10:3128"}).
    """

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    params: Optional[Mapping[str, str]] = None
    cookies: Optional[Mapping[str, str]] = None
    data: Optional[Any] = None
    json_body: Optional[Any] = None
    timeout: float = 30.0
    allow_redirects: bool = True
    verify: bool = True
    proxy: Optional[ProxyConfig] = None
    proxies: Optional[Mapping[str, ProxyConfig]] = None

    def __post_init__(self) -> None:
        """
        Wraps `headers` and `params` in MappingProxyType to prevent
        mutation after the object is constructed.

        See `Response.__post_init__` for a detailed explanation of why
        `frozen=True` alone is not sufficient to protect mutable field
        values such as dicts.
        """
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

        if self.params is not None:
            object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

        if self.cookies is not None:
            object.__setattr__(self, "cookies", MappingProxyType(dict(self.cookies)))
        
        object.__setattr__(self, "data", _freeze_value(self.data))
        object.__setattr__(self, "json_body", _freeze_value(self.json_body))
        
        if self.proxy is not None and self.proxies is not None:
            raise ValueError(
                "Cannot set both 'proxy' and 'proxies' at the same time. "
                "Use 'proxy' for a single proxy applied to all protocols, "
                "or 'proxies' for per-protocol proxy configuration."
            )
        if self.proxies is not None:
            object.__setattr__(self, "proxies", MappingProxyType(dict(self.proxies)))


@dataclass(frozen=True, slots=True)
class Response:
    """
    An immutable snapshot of the result of an HTTP request performed by
    the Network Layer.

    The object is created once, right after the server's reply is
    received, and is never modified afterwards. This is a deliberate
    design choice: `Response` describes a fact that has already
    happened, so allowing it to be edited after the fact is a potential
    source of bugs (e.g. silently overwriting `status_code` in a test,
    masking a real request failure).

    Attributes:
        url: The final response URL (after following all redirects).
        status_code: The HTTP status code of the response.
        headers: Response headers. Stored as a MappingProxyType to
            prevent accidental mutation of the dict from outside, even
            though the dataclass itself is frozen.
        cookies: Cookies set by the server in this response, represented
            as a tuple of `Cookie` objects rather than a plain mapping,
            preserving domain/path/expiry/security attributes.
        text: The response body decoded as text.
        content: The raw response body (bytes) — needed, for example,
            when saving images or other binary files.
        elapsed: The request duration in seconds.
        redirect_history: URLs the request passed through before
            reaching the final `url` (in the order they were visited).

    Example:
        >>> response.status_code
        200
        >>> response.ok
        True
        >>> data = response.json()
        >>> session_cookie = response.get_cookie("session_id")
    """

    url: str
    status_code: int
    headers: Mapping[str, str]
    cookies: tuple[Cookie, ...]
    text: str
    content: bytes
    elapsed: float
    redirect_history: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """
        Ensures `headers` is truly immutable by wrapping it in a
        MappingProxyType.

        Even if the caller passed a plain `dict`, we wrap it in
        `MappingProxyType` — a read-only "window" over the dict that
        raises TypeError on write attempts. Without this step,
        `frozen=True` would only protect the `headers` attribute itself
        from reassignment (`response.headers = {...}`), but would not
        prevent mutation of its contents (`response.headers["X"] = "Y"`).

        Note that `cookies` does not need the same treatment: it is
        already a `tuple` of frozen `Cookie` instances, and tuples are
        immutable by construction.

        Since `frozen=True` forbids a direct `self.headers = ...`,
        `object.__setattr__` is used instead — this is the officially
        sanctioned way to initialize fields inside a frozen dataclass.
        """
        object.__setattr__(self, "headers", MappingProxyType(CaseInsensitiveDict(self.headers)))

    @property
    def ok(self) -> bool:
        """Returns True if the response status code indicates success (< 400)."""
        return self.status_code < 400

    def raise_for_status(self) -> None:
        """
        Raises an HTTPError if the response status code indicates an error
        (4xx or 5xx).

        Raises:
            HTTPError: If the response status code is 4xx or 5xx.
        """
        if 400 <= self.status_code < 600:
            raise HTTPError(
                f"HTTP request to {self.url} failed with status code {self.status_code}",
                status_code=self.status_code,
                url=self.url
            )

    def json(self) -> Any:
        """
        Parses the response body as JSON.

        Returns:
            The decoded Python object (dict, list, etc.).

        Raises:
            json.JSONDecodeError: If the response body is not valid JSON.
        """
        import json
        return json.loads(self.text)

    def get_cookie(self, name: str) -> Optional[Cookie]:
        """
        Looks up a cookie by name among the cookies set by this response.

        Args:
            name: The cookie name to search for.

        Returns:
            The matching `Cookie`, or None if no cookie with that name
            was set in this response.
        """
        for cookie in self.cookies:
            if cookie.name == name:
                return cookie
        return None


@dataclass(frozen=True, slots=True)
class StealthConfig:
    """
    Stealth Layer configuration: defines which anti-bot evasion
    techniques should be applied during a session.

    The object is created once when configuring `PhantomClient` and is
    passed to the Stealth Layer to generate the corresponding JS
    injections and to select the TLS impersonation profile.

    Attributes:
        impersonate: The curl_cffi impersonation profile for the
            TLS/JA3 fingerprint (e.g. "chrome120", "safari17_0").
            Determines which browser the network layer masquerades as.
        spoof_canvas: Whether to spoof the Canvas fingerprinting result
            (adds noise to canvas.toDataURL()).
        spoof_webgl: Whether to spoof the WebGL fingerprint
            (vendor/renderer).
        spoof_navigator: Whether to spoof navigator properties
            (platform, hardwareConcurrency, webdriver, etc.).
        languages: The list of languages, in priority order, reported
            via navigator.languages.
        timezone: The timezone to spoof (e.g. "Europe/Kyiv"). None
            means the host system's timezone is used.
        webgl_vendor: The value to report as WebGL vendor (only used
            when spoof_webgl=True). None means the default value from
            the stealth profile is used.
        webgl_renderer: The value to report as WebGL renderer, analogous
            to webgl_vendor.
        extra_headers: Additional HTTP headers appended to every
            request (on top of the headers generated by the curl_cffi
            impersonation profile).

    Note:
        This class is immutable (frozen). To obtain a modified copy,
        use `dataclasses.replace()`:

        >>> base = StealthConfig()
        >>> no_canvas = dataclasses.replace(base, spoof_canvas=False)
    """

    impersonate: str = "chrome"
    spoof_canvas: bool = True
    spoof_webgl: bool = True
    spoof_navigator: bool = True
    languages: tuple[str, ...] = ("en-US", "en")
    timezone: Optional[str] = None
    webgl_vendor: Optional[str] = None
    webgl_renderer: Optional[str] = None
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """
        Protects `extra_headers` from mutation using the same technique
        as `Response.headers` — wrapping it in a MappingProxyType.

        Note that `languages` was deliberately typed as a `tuple`
        rather than a `list` in the field annotation itself. This is a
        simpler way to achieve immutability than what is done for
        `extra_headers` — tuples are already immutable out of the box,
        unlike lists.
        """
        object.__setattr__(
            self, "extra_headers", MappingProxyType(dict(self.extra_headers))
        )

@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """
    Immutable configuration for a single proxy server.

    Attributes:
        host: Proxy server hostname or IP address.
        port: Proxy server port.
        username: Username for proxy authentication, or None if the
            proxy requires no authentication.
        password: Password for proxy authentication, or None.
        scheme: Proxy protocol — "http", "https", or "socks5".
    """
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    scheme: str = "http"  # "http", "https", "socks5"

    _VALID_SCHEMES = frozenset({"http", "https", "socks4", "socks5", "socks5h"})

    def __post_init__(self) -> None:
        if not self.host or not self.host.strip():
            raise ValueError("Proxy host cannot be empty.")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("Proxy port must be an integer between 1 and 65535.")
        if self.password is not None and not self.username:
            raise ValueError("A proxy password requires a username.")

        object.__setattr__(self, "host", self.host.strip())
        object.__setattr__(self, "scheme", self.scheme.lower())
        if self.scheme not in self._VALID_SCHEMES:
            raise ValueError(
                f"Invalid proxy scheme: {self.scheme!r}. "
                f"Must be one of: {', '.join(sorted(self._VALID_SCHEMES))}"
        )

    @property
    def url(self) -> str:
        """Builds the full proxy URL, e.g. 'http://user:pass@host:port'."""
        auth = ""
        if self.username:
            username = quote(self.username, safe="")
            password = quote(self.password or "", safe="")
            auth = f"{username}:{password}@"

        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{self.scheme}://{auth}{host}:{self.port}"
