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

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

from phantom_curl.utils import CaseInsensitiveDict


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
    """

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    params: Optional[Mapping[str, str]] = None
    data: Optional[Any] = None
    json_body: Optional[Any] = None
    timeout: float = 30.0
    allow_redirects: bool = True

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