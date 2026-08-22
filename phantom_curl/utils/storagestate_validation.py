from urllib.parse import urlsplit

def is_valid_origin(value: object) -> bool:
    if not isinstance(value, str):
        return False

    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False

    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
    )