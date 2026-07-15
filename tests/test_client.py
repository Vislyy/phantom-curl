from phantom_curl.client import PhantomClient


def test_client_is_active(phantom_client: PhantomClient):
    assert phantom_client is not None


def test_client_get(phantom_client: PhantomClient):
    response = phantom_client.get(
        "https://httpbin.org/get",
        params={"q": "python"},
        headers={"User-Agent": "phantom-curl-0.1.0-dev"},
    )

    assert response.status_code == 200
    assert response.ok is True

    data = response.json()
    assert data["args"]["q"] == "python"
    assert data["headers"]["User-Agent"] == "phantom-curl-0.1.0-dev"


def test_client_post_json(phantom_client: PhantomClient):
    response = phantom_client.post(
        "https://httpbin.org/post",
        json={"key": "value"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["json"] == {"key": "value"}


def test_client_cookies_property(phantom_client: PhantomClient):
    phantom_client.cookies["manual_cookie"] = "manual_value"
    assert phantom_client.cookies["manual_cookie"] == "manual_value"

    response = phantom_client.get("https://httpbin.org/cookies")
    data = response.json()
    assert data["cookies"]["manual_cookie"] == "manual_value"