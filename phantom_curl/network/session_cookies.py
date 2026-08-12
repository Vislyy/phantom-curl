"""
phantom_curl.network.session_cookies
======================================

A mutable, dict-like view over the cookies stored in an active
curl_cffi session, allowing users to read, set, and delete cookies
directly on a live PhantomClient/NetworkSession.
"""

from __future__ import annotations

from collections.abc import MutableMapping
import time
from typing import TYPE_CHECKING, Iterator
from urllib.parse import urlsplit

from phantom_curl.models import Cookie
from phantom_curl.utils.cookie import cookiejar_to_tuple

if TYPE_CHECKING:
    from curl_cffi.requests import Session as CurlSession


class SessionCookies(MutableMapping):
    """
    A live, mutable view over the cookies of an active curl_cffi
    session.

    Unlike Response.cookies (an immutable snapshot tied to a single
    HTTP response), SessionCookies reflects — and can modify — the
    ongoing cookie state of a session across multiple requests.

    This class is a thin delegator around curl_cffi's own Cookies
    object (which is itself a MutableMapping), adding only the
    ability to export the current state as PhantomCurl Cookie objects
    via as_tuple().

    Example:
        >>> client = PhantomClient()
        >>> client.get("https://example.com/login")
        >>> client.cookies["session_id"]
        'abc123'
        >>> client.cookies["custom"] = "value"
        >>> del client.cookies["custom"]
    """

    def __init__(self, curl_session: "CurlSession", http_only_cookie_keys: set[tuple[str, str, str]]) -> None:
        """
        Args:
            curl_session: The underlying curl_cffi session whose
                cookie jar this object wraps.
        """
        self._curl_session = curl_session
        self._http_only_cookie_keys = http_only_cookie_keys

    def __setitem__(self, name: str, value: str) -> None:
        """Sets a cookie by name on the underlying session."""
        self._curl_session.cookies[name] = value

    def __getitem__(self, name: str) -> str:
        """
        Returns the value of a cookie by name.

        Raises:
            KeyError: If no cookie with this name exists in the session.
        """
        return self._curl_session.cookies[name]

    def __delitem__(self, name: str) -> None:
        """
        Removes a cookie by name from the underlying session.

        Raises:
            KeyError: If no cookie with this name exists in the session.
        """
        del self._curl_session.cookies[name]

    def __iter__(self) -> Iterator[str]:
        """Iterates over cookie names currently stored in the session."""
        return iter(self._curl_session.cookies)

    def __len__(self) -> int:
        """Returns the number of cookies currently stored in the session."""
        return len(self._curl_session.cookies)

    def as_tuple(self) -> tuple[Cookie, ...]:
        """
        Returns an immutable snapshot of all cookies in this session
        as a tuple of PhantomCurl Cookie objects — the same format
        used by Response.cookies.

        Returns:
            A tuple of Cookie objects representing the current session
            cookie state.
        """
        return cookiejar_to_tuple(self._curl_session.cookies.jar, self._http_only_cookie_keys)

    def document_cookie_string(self, url: str) -> str:
        """Return the non-HttpOnly cookies visible to JavaScript at ``url``."""
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if hostname is None:
            return ""

        path = parsed.path or "/"
        secure_page = parsed.scheme == "https"
        now = time.time()
        visible = [
            f"{cookie.name}={cookie.value}"
            for cookie in self.as_tuple()
            if not cookie.http_only
            and (cookie.expires is None or cookie.expires > now)
            and (not cookie.secure or secure_page)
            and self._domain_matches(hostname, cookie.domain)
            and self._path_matches(path, cookie.path)
        ]
        return "; ".join(visible)

    def set_document_cookie(self, cookie_string: str, url: str) -> None:
        """Persist one ``document.cookie`` assignment in the underlying jar."""
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if hostname is None:
            raise ValueError("document.cookie requires an HTTP or HTTPS page URL")

        parts = [part.strip() for part in cookie_string.split(";")]
        name, separator, value = parts[0].partition("=")
        if not separator or not name:
            raise ValueError("document.cookie assignment must contain a name and value")

        attributes = self._parse_attributes(parts[1:])
        domain = attributes.get("domain", hostname).lstrip(".")
        if not self._domain_matches(hostname, domain):
            raise ValueError("document.cookie domain must match the current page host")

        path = attributes.get("path", self._default_path(parsed.path))
        if not path.startswith("/"):
            raise ValueError("document.cookie path must start with '/'")

        cookie_key = self._cookie_key(name, domain, path)
        if cookie_key in self._http_only_cookie_keys:
            return

        if attributes.get("max-age") == "0":
            self._curl_session.cookies.delete(name, domain=domain, path=path)
            self._http_only_cookie_keys.discard(cookie_key)

            return

        self._curl_session.cookies.set(
            name,
            value,
            domain=domain,
            path=path,
            secure="secure" in attributes,
        )
        self._http_only_cookie_keys.discard(cookie_key)

    @staticmethod
    def _parse_attributes(parts: list[str]) -> dict[str, str]:
        attributes: dict[str, str] = {}
        for part in parts:
            key, separator, value = part.partition("=")
            attributes[key.strip().lower()] = value.strip() if separator else ""
        return attributes

    @staticmethod
    def _domain_matches(hostname: str, domain: str | None) -> bool:
        if domain is None:
            return True
        normalized_domain = domain.lstrip(".").lower()
        normalized_host = hostname.lower()
        return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")

    @staticmethod
    def _path_matches(current_path: str, cookie_path: str) -> bool:
        if current_path == cookie_path:
            return True
        return current_path.startswith(cookie_path.rstrip("/") + "/")

    @staticmethod
    def _default_path(path: str) -> str:
        if not path or path == "/":
            return "/"
        return path.rsplit("/", 1)[0] or "/"

    @staticmethod
    def _cookie_key(name: str, domain: str, path: str) -> tuple[str, str, str]:
        return name, domain.lstrip(".").lower(), path
