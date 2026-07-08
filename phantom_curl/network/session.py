"""
phantom_curl.network.session
==============================

A thin wrapper around curl_cffi.requests.Session that translates
PhantomCurl's own data models (RequestOptions, Response, Cookie) into
real HTTP calls with TLS/JA3 fingerprint impersonation.
"""

from __future__ import annotations

from curl_cffi.requests import Session as CurlSession
from curl_cffi.requests.exceptions import (
    ConnectionError,
    Timeout,
)

from phantom_curl.exceptions import ConnectionRejectedError, RequestTimeoutError
from phantom_curl.models import Cookie, StealthConfig, RequestOptions, Response


class NetworkSession:
    """
    Wraps a curl_cffi session, configured according to a StealthConfig.

    This class is stateful: it keeps a single underlying curl_cffi
    Session alive across multiple requests, so cookies set by the
    server are automatically remembered and sent back on subsequent
    requests — the same way a real browser session behaves.
    """

    def __init__(self, stealth_config: StealthConfig) -> None:
        """
        Creates a new network session configured with the given
        stealth settings.

        Args:
            stealth_config: Defines which browser TLS profile to
                impersonate, plus extra headers to attach to every
                request made through this session.
        """
        self._stealth_config = stealth_config

        self._session = CurlSession(
            impersonate=stealth_config.impersonate,
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

    def request(self, options: RequestOptions) -> Response:
        try:
            raw_response = self._session.request(
                method=options.method,
                url=options.url,
                headers=dict(options.headers),
                params=dict(options.params) if options.params is not None else None,
                timeout=options.timeout,
            )

        except ConnectionError as e:
            raise ConnectionRejectedError(
                f"Failed to connect to {options.url}",
                url=options.url
            ) from e
        
        except Timeout as e:
            raise RequestTimeoutError(
                f"Request to {options.url} timed out after {options.timeout} seconds",
                timeout=options.timeout,
                url=options.url
            ) from e

        return self._build_response(raw_response)
    
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
        result = []
        for raw_cookie in raw_response.cookies.jar:
            result.append(
                Cookie(
                    name=raw_cookie.name,
                    value=raw_cookie.value,
                    domain=raw_cookie.domain,
                    path=raw_cookie.path,
                    expires=float(raw_cookie.expires) if raw_cookie.expires is not None else None,
                    secure=raw_cookie.secure,
                    http_only=raw_cookie.has_nonstandard_attr("HttpOnly"),
                    same_site=raw_cookie.get_nonstandard_attr("SameSite"),
                )
            )
        return tuple(result)