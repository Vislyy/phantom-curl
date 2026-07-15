import pytest

from phantom_curl.exceptions import RequestTimeoutError
from phantom_curl.models import RequestOptions, Response


def test_network_session_is_active(network_session):
    assert network_session is not None


def test_network_session_request(network_session):
    options = RequestOptions(
        method="GET",
        url="https://httpbin.org/get",
        headers={"User-Agent": "phantom-curl-0.1.0-dev"},
    )

    response: Response = network_session.request(options)

    assert response.status_code == 200
    assert response.ok is True
    assert response.headers.get("Content-Type") == "application/json"

    data = response.json()
    assert data["headers"]["User-Agent"] == "phantom-curl-0.1.0-dev"


def test_network_session_request_with_timeout(network_session):
    options = RequestOptions(
        method="GET",
        url="https://httpbin.org/delay/5",
        headers={"User-Agent": "phantom-curl-0.1.0-dev"},
        timeout=3.0,
    )

    with pytest.raises(RequestTimeoutError):
        network_session.request(options)


def test_network_session_request_with_cookies(network_session):
    options = RequestOptions(
        method="GET",
        url="https://httpbin.org/cookies/set",
        headers={"User-Agent": "phantom-curl-0.1.0-dev"},
        params={"testcookie": "1"},
    )

    response: Response = network_session.request(options)

    assert response.status_code == 200
    assert response.ok is True

    cookie = response.get_cookie("testcookie")
    assert cookie is not None
    assert cookie.value == "1"