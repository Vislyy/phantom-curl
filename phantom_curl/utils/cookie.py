from phantom_curl.models import Cookie

def cookiejar_to_tuple(jar) -> tuple[Cookie, ...]:
    """
    Converts a http.cookiejar.CookieJar-like object into a tuple
    of PhantomCurl Cookie objects.
    """
    result = []
    for raw_cookie in jar:
        result.append(Cookie(
            name=raw_cookie.name,
            value=raw_cookie.value,
            domain=raw_cookie.domain,
            path=raw_cookie.path,
            expires=float(raw_cookie.expires) if raw_cookie.expires is not None else None,
            secure=raw_cookie.secure,
            http_only=raw_cookie.has_nonstandard_attr("HttpOnly"),
            same_site=raw_cookie.get_nonstandard_attr("SameSite"),
        ))
    return tuple(result)