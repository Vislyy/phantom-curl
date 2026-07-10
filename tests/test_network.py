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
        url="https://httpbin.org/delay/5",  # This endpoint delays the response by 5 seconds
        headers={"User-Agent": "phantom-curl-0.1.0-dev"},
        timeout=3,  # Set a timeout of 3 seconds
    )

    try:
        response: Response = network_session.request(options)
    except Exception as e:
        assert isinstance(e, RequestTimeoutError)  # Expecting a timeout error

def test_network_session_request_with_cookies(network_session):
    options = RequestOptions(
        method="GET",
        url="https://httpbin.org/cookies/set?testcookie=value",
        headers={"User-Agent": "phantom-curl-0.1.0-dev"},
    )

    response: Response = network_session.request(options)

    assert response.status_code == 200
    assert response.ok is True

    # Now check if the cookie was set
    options_check = RequestOptions(
        method="GET",
        url="https://httpbin.org/cookies/set?testcookie=value",
        headers={"User-Agent": "phantom-curl-0.1.0-dev"},
    )

    response_check: Response = network_session.request(options_check)
    cookies_data = response_check.json()
    assert cookies_data["cookies"].get("testcookie") == "value"