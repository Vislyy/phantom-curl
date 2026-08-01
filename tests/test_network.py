import pytest

from phantom_curl.exceptions import RequestTimeoutError
from phantom_curl.models import RequestOptions, Response, RetryConfig, StealthConfig
from phantom_curl.network.session import NetworkSession

def test_network_session_request(network_session, http_server: str) -> None:
    options = RequestOptions(
        method="GET",
        url=f"{http_server}/get",
        headers={"User-Agent": "phantom-curl-test"},
        params={"q": "python"},
    )

    response: Response = network_session.request(options)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json()["args"] == {"q": "python"}


def test_network_session_translates_timeouts(network_session, http_server: str) -> None:
    options = RequestOptions(method="GET", url=f"{http_server}/slow", timeout=0.01)

    with pytest.raises(RequestTimeoutError):
        network_session.request(options)


def test_network_session_sends_request_cookies(network_session, http_server: str) -> None:
    options = RequestOptions(
        method="GET",
        url=f"{http_server}/cookies",
        cookies={"manual_cookie": "manual_value"},
    )

    assert network_session.request(options).json() == {"manual_cookie": "manual_value"}


def test_network_session_retries_transient_server_errors(http_server: str) -> None:
    session = NetworkSession(
        StealthConfig(),
        retry_config=RetryConfig(max_attempts=3, backoff_factor=0, retry_status_codes=frozenset({503})),
    )
    try:
        response = session.request(RequestOptions(method="GET", url=f"{http_server}/flaky"))
    finally:
        session.close()

    assert response.status_code == 200
    assert response.json() == {"attempt": 3}
