"""
phantom_curl.client
=====================

The main facade of the PhantomCurl library — PhantomClient.
Provides a simple, requests-like interface while internally
delegating to the Network Layer.
"""

from __future__ import annotations

from typing import Union, Optional, Mapping, Any

from phantom_curl.models import (
    ProxyConfig,
    Response,
    RetryConfig,
    StealthConfig,
    StorageState,
)
from phantom_curl.page import Page
from phantom_curl.network.session_cookies import SessionCookies
from phantom_curl.network.session import NetworkSession
from phantom_curl.utils.request_builder import build_request_options


class PhantomClient:
    """
    The main entry point of the PhantomCurl library.

    Wraps the Network Layer (and, in the future, the Environment/Bridge/
    Stealth layers) behind a simple, requests-like API.

    Example:
        >>> client = PhantomClient()
        >>> response = client.get("https://example.com")
        >>> response.status_code
        200
    """

    def __init__(
        self,
        stealth_config: Optional[StealthConfig] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> None:
        """
        Creates a new PhantomClient.

        Args:
            stealth_config: Stealth settings to use for this client.
                If not provided, default StealthConfig() is used.
            retry_config: Policy for retrying transient network failures.
                If omitted, each request is attempted once.
        """
        self.stealth_config = stealth_config or StealthConfig()
        self.retry_config = retry_config or RetryConfig()

        self._session = NetworkSession(
            stealth_config=self.stealth_config,
            retry_config=self.retry_config,
        )

    def close(self) -> None:
        """
        Closes the underlying network session and releases resources.
        """
        self._session.close()

    def __enter__(self) -> PhantomClient:
        """
        Context manager entry point. Allows using PhantomClient in a `with` statement.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Context manager exit point. Closes the network session when exiting the `with` block.
        """
        self.close()

    def get(
        self,
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        allow_redirects: bool = True,
        verify: bool = True,
        proxy: Union[ProxyConfig, str, None] = None,
        proxies: Optional[Mapping[str, Union[ProxyConfig, str]]] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> Response:
        """
        Performs an HTTP GET request.

        Args:
            url: Target URL.
            params: Query string parameters.
            headers: Additional request headers.
            cookies: Additional request cookies.
            timeout: Request timeout in seconds.
            allow_redirects: Whether to automatically follow HTTP redirects.

        Returns:
            The server's response.
        """

        options = build_request_options(
            method="GET",
            url=url,
            headers=headers or {},
            params=params or {},
            cookies=cookies or {},
            data=None,
            json=None,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify,
            proxy=proxy,
            proxies=proxies,
            retry_config=retry_config,
        )
        return self._session.request(options)

    def head(
        self,
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        allow_redirects: bool = True,
        verify: bool = True,
        proxy: Union[ProxyConfig, str, None] = None,
        proxies: Optional[Mapping[str, Union[ProxyConfig, str]]] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> Response:
        """
        Performs an HTTP HEAD request.

        Args:
            url: Target URL.
            params: Query string parameters.
            headers: Additional request headers.
            cookies: Additional request cookies.
            timeout: Request timeout in seconds.
            allow_redirects: Whether to automatically follow HTTP redirects.

        Returns:
            The server's response.
        """

        options = build_request_options(
            method="HEAD",
            url=url,
            headers=headers or {},
            params=params or {},
            cookies=cookies or {},
            data=None,
            json=None,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify,
            proxy=proxy,
            proxies=proxies,
            retry_config=retry_config,
        )
        return self._session.request(options)

    def options(
        self,
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        allow_redirects: bool = True,
        verify: bool = True,
        proxy: Union[ProxyConfig, str, None] = None,
        proxies: Optional[Mapping[str, Union[ProxyConfig, str]]] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> Response:
        """
        Performs an HTTP OPTIONS request.

        Args:
            url: Target URL.
            params: Query string parameters.
            headers: Additional request headers.
            cookies: Additional request cookies.
            timeout: Request timeout in seconds.
            allow_redirects: Whether to automatically follow HTTP redirects.

        Returns:
            The server's response.
        """

        options = build_request_options(
            method="OPTIONS",
            url=url,
            headers=headers or {},
            params=params or {},
            cookies=cookies or {},
            data=None,
            json=None,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify,
            proxy=proxy,
            proxies=proxies,
            retry_config=retry_config,
        )
        return self._session.request(options)

    def post(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        allow_redirects: bool = False,
        verify: bool = True,
        proxy: Union[ProxyConfig, str, None] = None,
        proxies: Optional[Mapping[str, Union[ProxyConfig, str]]] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> Response:
        """
        Performs an HTTP POST request.

        Args:
            url: Target URL.
            data: Form data to send in the body of the request.
            json: JSON data to send in the body of the request.
            headers: Additional request headers.
            cookies: Additional request cookies.
            timeout: Request timeout in seconds.
            allow_redirects: Whether to automatically follow HTTP redirects.

        Returns:
            The server's response.
        """

        options = build_request_options(
            method="POST",
            url=url,
            headers=headers or {},
            params={},
            cookies=cookies or {},
            data=data,
            json=json,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify,
            proxy=proxy,
            proxies=proxies,
            retry_config=retry_config,
        )
        return self._session.request(options)

    def put(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        allow_redirects: bool = False,
        verify: bool = True,
        proxy: Union[ProxyConfig, str, None] = None,
        proxies: Optional[Mapping[str, Union[ProxyConfig, str]]] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> Response:
        """
        Performs an HTTP PUT request.

        Args:
            url: Target URL.
            data: Form data to send in the body of the request.
            json: JSON data to send in the body of the request.
            headers: Additional request headers.
            cookies: Additional request cookies.
            timeout: Request timeout in seconds.
            allow_redirects: Whether to automatically follow HTTP redirects.

        Returns:
            The server's response.
        """

        options = build_request_options(
            method="PUT",
            url=url,
            headers=headers or {},
            params={},
            cookies=cookies or {},
            data=data,
            json=json,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify,
            proxy=proxy,
            proxies=proxies,
            retry_config=retry_config,
        )
        return self._session.request(options)

    def patch(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        allow_redirects: bool = False,
        verify: bool = True,
        proxy: Union[ProxyConfig, str, None] = None,
        proxies: Optional[Mapping[str, Union[ProxyConfig, str]]] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> Response:
        """
        Performs an HTTP PATCH request.

        Args:
            url: Target URL.
            data: Form data to send in the body of the request.
            json: JSON data to send in the body of the request.
            headers: Additional request headers.
            cookies: Additional request cookies.
            timeout: Request timeout in seconds.
            allow_redirects: Whether to automatically follow HTTP redirects.

        Returns:
            The server's response.
        """

        options = build_request_options(
            method="PATCH",
            url=url,
            headers=headers or {},
            params={},
            cookies=cookies or {},
            data=data,
            json=json,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify,
            proxy=proxy,
            proxies=proxies,
            retry_config=retry_config,
        )
        return self._session.request(options)

    def delete(
        self,
        url: str,
        headers: Optional[Mapping[str, str]] = None,
        cookies: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        allow_redirects: bool = False,
        verify: bool = True,
        proxy: Union[ProxyConfig, str, None] = None,
        proxies: Optional[Mapping[str, Union[ProxyConfig, str]]] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> Response:
        """
        Performs an HTTP DELETE request.

        Args:
            url: Target URL.
            headers: Additional request headers.
            cookies: Additional request cookies.
            timeout: Request timeout in seconds.
            allow_redirects: Whether to automatically follow HTTP redirects.

        Returns:
            The server's response.
        """

        options = build_request_options(
            method="DELETE",
            url=url,
            headers=headers or {},
            params={},
            cookies=cookies or {},
            data=None,
            json=None,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify,
            proxy=proxy,
            proxies=proxies,
            retry_config=retry_config,
        )
        return self._session.request(options)

    @property
    def cookies(self) -> SessionCookies:
        """
        Provides live, mutable access to the cookies stored in this
        client's session.
        """
        return self._session.cookies

    def new_page(self, url: Optional[str] = None) -> Page:
        """
        Creates a new virtual browser tab (Page) backed by this client's
        shared NetworkSession.

        If `url` is provided, immediately navigates the new page to it
        (equivalent to calling `page.goto(url)` right after creation).

        Args:
            url: An optional URL to navigate to immediately after
                creating the page. If omitted, the page is returned
                without any document loaded.

        Returns:
            The newly created Page.

        Raises:
            NetworkError: If `url` is provided and the underlying HTTP
                request fails (see Page.goto).
            DOMBuildError: If `url` is provided and the response body
                could not be parsed as HTML (see Page.goto).

        Note:
            If navigation fails (an exception is raised), the exception
            propagates directly out of this method — the already-created
            Page instance is not returned to the caller in that case.
        """
        page = Page(session=self._session)
        if url:
            page.goto(url)

        return page

    def export_storage_state(self) -> StorageState:
        """Return a JSON-serializable snapshot of the current cookie session."""
        return self._session.export_storage_state()

    def import_storage_state(self, state: StorageState, *, clear_existing: bool = True) -> None:
        """Restore cookies from a previously exported storage snapshot."""
        self._session.import_storage_state(state, clear_existing=clear_existing)
