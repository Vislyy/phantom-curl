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