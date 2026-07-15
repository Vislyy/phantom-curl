"""
phantom_curl.network.session_cookies
======================================

A mutable, dict-like view over the cookies stored in an active
curl_cffi session, allowing users to read, set, and delete cookies
directly on a live PhantomClient/NetworkSession.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Iterator

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

    def __init__(self, curl_session: "CurlSession") -> None:
        """
        Args:
            curl_session: The underlying curl_cffi session whose
                cookie jar this object wraps.
        """
        self._curl_session = curl_session

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
        return cookiejar_to_tuple(self._curl_session.cookies.jar)