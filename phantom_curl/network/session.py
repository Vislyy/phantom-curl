"""
phantom_curl.network.session
==============================

A thin wrapper around curl_cffi.requests.Session that translates
PhantomCurl's own data models (RequestOptions, Response, Cookie) into
real HTTP calls with TLS/JA3 fingerprint impersonation.
"""

from __future__ import annotations

from collections.abc import Mapping
from http.cookiejar import Cookie as HTTPCookie
import time
from curl_cffi.requests import Session as CurlSession
from curl_cffi.requests.exceptions import (
    ConnectionError,
    Timeout,
)

from typing import Any, Optional, cast

from phantom_curl.exceptions import ConnectionRejectedError, RequestTimeoutError
from phantom_curl.models import Cookie, RequestOptions, Response, RetryConfig, StealthConfig, StorageState
from phantom_curl.network.session_cookies import SessionCookies
from phantom_curl.utils.cookie import cookiejar_to_tuple


def _to_mutable(value):
    """Convert frozen request-model values back to curl_cffi-compatible values."""
    if isinstance(value, Mapping):
        return {key: _to_mutable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_mutable(item) for item in value]
    return value


def _to_http_cookie(cookie: Cookie) -> HTTPCookie:
    """Convert PhantomCurl's immutable cookie model to a CookieJar entry."""
    domain = cookie.domain or ""
    rest: dict[str, str] = {}
    if cookie.http_only:
        rest["HttpOnly"] = ""
    if cookie.same_site is not None:
        rest["SameSite"] = cookie.same_site

    return HTTPCookie(
        version=0,
        name=cookie.name,
        value=cookie.value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=bool(domain),
        domain_initial_dot=domain.startswith("."),
        path=cookie.path,
        path_specified=True,
        secure=cookie.secure,
        expires=int(cookie.expires) if cookie.expires is not None else None,
        discard=cookie.expires is None,
        comment=None,
        comment_url=None,
        rest=rest,
        rfc2109=False,
    )


class NetworkSession:
    """
    Wraps a curl_cffi session, configured according to a StealthConfig.

    This class is stateful: it keeps a single underlying curl_cffi
    Session alive across multiple requests, so cookies set by the
    server are automatically remembered and sent back on subsequent
    requests — the same way a real browser session behaves.
    """

    def __init__(self, stealth_config: StealthConfig, retry_config: Optional[RetryConfig] = None) -> None:
        """
        Creates a new network session configured with the given
        stealth settings.

        Args:
            stealth_config: Defines which browser TLS profile to
                impersonate, plus extra headers to attach to every
                request made through this session.
            retry_config: Policy for retrying transient failures. The default
                performs exactly one attempt, preserving the prior behavior.
        """
        self._stealth_config = stealth_config
        self.retry_config = retry_config or RetryConfig()

        # curl_cffi exposes narrow Literal-based types while PhantomCurl accepts
        # user-configured browser profiles and proxy mappings at its public API.
        self._session: Any = CurlSession(
            impersonate=cast(Any, stealth_config.impersonate),
            headers=dict(stealth_config.extra_headers),
        )

    def close(self) -> None:
        """
        Closes the underlying curl_cffi session and releases any
        resources associated with it.
        """
        self._session.close()

    def __enter__(self) -> NetworkSession:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _build_response(self, raw_response) -> Response:
        """
        Converts a raw curl_cffi response into a PhantomCurl Response
        object.

        Args:
            raw_response: The raw response returned by curl_cffi.

        Returns:
            A PhantomCurl Response object.
        """

        response = Response(
            url=raw_response.url,
            status_code=raw_response.status_code,
            headers=raw_response.headers,
            cookies=self._extract_cookies(raw_response),
            text=raw_response.text,
            content=raw_response.content,
            elapsed=float(raw_response.elapsed.total_seconds()),
            redirect_history=tuple(r.url for r in raw_response.history),
        )

        return response

    def _extract_cookies(self, raw_response) -> tuple[Cookie, ...]:
        """
        Converts curl_cffi's internal cookie jar into a tuple of
        PhantomCurl Cookie objects.

        Args:
            raw_response: The raw response returned by curl_cffi.

        Returns:
            A tuple of Cookie objects extracted from the response.
        """
        return cookiejar_to_tuple(raw_response.cookies.jar)

    def _resolve_proxies(self, options: RequestOptions) -> Optional[dict[str, str]]:
        """
        Converts RequestOptions proxy settings into the dict format
        expected by curl_cffi (mapping protocol -> proxy URL string).

        Returns:
            A dict like {"http": "...", "https": "..."}, or None if no
            proxy is configured.
        """
        if options.proxies is not None:
            return {protocol: proxy_config.url for protocol, proxy_config in options.proxies.items()}

        if options.proxy is not None:
            proxy_url = options.proxy.url
            return {"http": proxy_url, "https": proxy_url}

        return None

    def _perform_request(self, options: RequestOptions, proxies: Optional[dict[str, str]]):
        """Issue exactly one request through curl_cffi."""
        return self._session.request(
            method=options.method,
            url=options.url,
            headers=dict(options.headers),
            params=dict(options.params) if options.params is not None else None,
            cookies=dict(options.cookies) if options.cookies is not None else None,
            data=_to_mutable(options.data),
            json=_to_mutable(options.json_body),
            timeout=options.timeout,
            allow_redirects=options.allow_redirects,
            verify=options.verify,
            proxies=proxies,
            proxy_auth=None,
        )

    def _wait_before_retry(self, retry_config: RetryConfig, retry_number: int) -> None:
        """Wait according to the retry policy selected for this request."""
        delay = retry_config.delay_for_retry(retry_number)
        if delay:
            time.sleep(delay)

    def request(self, options: RequestOptions) -> Response:
        proxies = self._resolve_proxies(options)

        retry_config = options.retry_config or self.retry_config

        for attempt in range(1, retry_config.max_attempts + 1):
            try:
                raw_response = self._perform_request(options, proxies)
            except ConnectionError as error:
                if attempt < retry_config.max_attempts and options.method.upper() in retry_config.allowed_methods:
                    self._wait_before_retry(retry_config, attempt)
                    continue
                raise ConnectionRejectedError(
                    f"Failed to connect to {options.url}",
                    url=options.url,
                ) from error
            except Timeout as error:
                if attempt < retry_config.max_attempts and options.method.upper() in retry_config.allowed_methods:
                    self._wait_before_retry(retry_config, attempt)
                    continue
                raise RequestTimeoutError(
                    f"Request to {options.url} timed out after {options.timeout} seconds",
                    timeout=options.timeout,
                    url=options.url,
                ) from error

            response = self._build_response(raw_response)
            should_retry = retry_config.should_retry_status(options.method, response.status_code)
            if should_retry and attempt < retry_config.max_attempts:
                self._wait_before_retry(retry_config, attempt)
                continue
            return response

        raise RuntimeError("Retry loop exited without a response.")

    @property
    def cookies(self) -> SessionCookies:
        """
        Provides live, mutable access to the cookies stored in this
        session.

        Returns:
            A SessionCookies view over the underlying curl_cffi session's
            cookie jar. Changes made through this object (e.g. setting
            or deleting a cookie) directly affect subsequent requests
            made through this session.

        Example:
            >>> session.cookies["session_id"] = "abc123"
            >>> session.cookies["session_id"]
            'abc123'
        """
        return SessionCookies(self._session)

    def export_storage_state(self) -> StorageState:
        """Return a serializable snapshot of all cookies in this session."""
        return StorageState(cookies=self.cookies.as_tuple())

    def import_storage_state(self, state: StorageState, *, clear_existing: bool = True) -> None:
        """Restore cookies from a previously exported :class:`StorageState`."""
        if clear_existing:
            self._session.cookies.clear()
        for cookie in state.cookies:
            self._session.cookies.jar.set_cookie(_to_http_cookie(cookie))
