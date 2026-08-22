"""Minimal bridges from JavaScript browser APIs to networking."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit

from phantom_curl.exceptions import InterceptorError
from phantom_curl.models import OriginPolicy
from phantom_curl.network.session import NetworkSession
from phantom_curl.utils.request_builder import build_request_options


class FetchInterceptor:
    """Perform the supported subset of JavaScript ``fetch`` requests."""

    _SUPPORTED_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, session: NetworkSession, page_url: str, origin_policy: OriginPolicy) -> None:
        self._session = session
        self._page_url = page_url
        self._origin_policy = origin_policy

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Perform one supported fetch request and return its serializable result."""
        try:
            request_options = self._parse_request(request)
            request_options["url"] = self._resolve_url(request_options["url"])
            response = self._session.request(build_request_options(allow_redirects=False, **request_options))
        except InterceptorError as error:
            return {"error": str(error)}

        return {
            "status": response.status_code,
            "ok": response.ok,
            "url": response.url,
            "headers": {
                name: value
                for name, value in response.headers.items()
                if name.lower() != "set-cookie"
            },
            "text": response.text,
        }

    def _parse_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        url = request.get("url")
        method = request.get("method", "GET")
        if not isinstance(url, str) or not url:
            raise InterceptorError("fetch requires a non-empty string URL")
        if not isinstance(method, str):
            raise InterceptorError("fetch method must be a string")
        method = method.upper()
        if method not in self._SUPPORTED_METHODS:
            raise InterceptorError(f"PhantomCurl fetch does not support the {method!r} HTTP method")

        headers = request.get("headers", {})
        if not isinstance(headers, Mapping) or not all(
            isinstance(name, str) and isinstance(value, str) for name, value in headers.items()
        ):
            raise InterceptorError("fetch headers must be a mapping of strings to strings")

        body = request.get("body")
        if body is not None and not isinstance(body, str):
            raise InterceptorError("PhantomCurl fetch currently supports string request bodies only")
        if body is not None and method in {"GET", "HEAD"}:
            raise InterceptorError(f"fetch {method} requests cannot include a body")

        request_headers = dict(headers)
        request_headers["Referer"] = self._page_url

        return {"url": url, "method": method, "headers": request_headers, "data": body}

    def _resolve_url(self, requested_url: str) -> str:
        url = urljoin(self._page_url, requested_url)
        if not self._origin_policy.allows(self._origin(self._page_url), self._origin(url)):
            raise InterceptorError(
                "PhantomCurl fetch only permits same-origin URLs unless OriginPolicy allows the target origin"
            )
        return url

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise InterceptorError("fetch URL must resolve to an HTTP or HTTPS origin")

        try:
            port = parsed.port
        except ValueError as error:
            raise InterceptorError("fetch URL contains an invalid port") from error

        scheme = parsed.scheme.lower()
        hostname = parsed.hostname.lower()
        host = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if scheme == "https" else 80
        if port in {None, default_port}:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"
