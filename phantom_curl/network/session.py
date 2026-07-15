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

from typing import Optional

from phantom_curl.exceptions import ConnectionRejectedError, RequestTimeoutError
from phantom_curl.models import Cookie, StealthConfig, RequestOptions, Response
from phantom_curl.network.session_cookies import SessionCookies
from phantom_curl.utils.cookie import cookiejar_to_tuple

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
            return {
                protocol: proxy_config.url
                for protocol, proxy_config in options.proxies.items()
            }
        
        if options.proxy is not None:
            proxy_url = options.proxy.url
            return {"http": proxy_url, "https": proxy_url}
        
        
        return None

    def request(self, options: RequestOptions) -> Response:
        proxies = self._resolve_proxies(options)
        
        try:
            raw_response = self._session.request(
                method=options.method,
                url=options.url,    
                headers=dict(options.headers),
                params=dict(options.params) if options.params is not None else None,
                cookies=dict(options.cookies) if options.cookies is not None else None,
                data=options.data,
                json=options.json_body,
                timeout=options.timeout,
                allow_redirects=options.allow_redirects,
                verify=options.verify,
                proxies=proxies,
                proxy_auth=None
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