from collections.abc import Set

from phantom_curl.models import Cookie


def cookiejar_to_tuple(jar, http_only_cookie_keys: Set[tuple[str, str, str]] = frozenset()) -> tuple[Cookie, ...]:
    """
    Converts a http.cookiejar.CookieJar-like object into a tuple
    of PhantomCurl Cookie objects.
    """
    result = []
    for raw_cookie in jar:
        key = (raw_cookie.name, raw_cookie.domain.lstrip(".").lower(), raw_cookie.path)
        http_only = raw_cookie.get_nonstandard_attr("http_only")
        result.append(
            Cookie(
                name=raw_cookie.name,
                value=raw_cookie.value,
                domain=raw_cookie.domain,
                path=raw_cookie.path,
                expires=float(raw_cookie.expires) if raw_cookie.expires is not None else None,
                secure=raw_cookie.secure,
                http_only=key in http_only_cookie_keys or http_only == "True",
                same_site=raw_cookie.get_nonstandard_attr("SameSite"),
            )
        )
    return tuple(result)
