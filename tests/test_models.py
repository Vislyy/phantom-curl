import pytest

from phantom_curl.exceptions import HTTPError
from phantom_curl.models import ProxyConfig, RequestOptions, Response, RetryConfig, StorageState


def test_request_options_freezes_json_without_mutating_source() -> None:
    payload = {"nested": {"value": 1}, "items": ["a"]}
    options = RequestOptions(method="POST", url="https://example.test", json_body=payload)
    payload["nested"]["value"] = 2
    payload["items"].append("b")

    assert options.json_body["nested"]["value"] == 1
    assert options.json_body["items"] == ("a",)
    with pytest.raises(TypeError):
        options.json_body["new"] = "value"


def test_proxy_url_encodes_credentials_and_ipv6_host() -> None:
    proxy = ProxyConfig(
        host="2001:db8::1",
        port=3128,
        username="name@example.com",
        password="pa:ss/word",
    )

    assert proxy.url == "http://name%40example.com:pa%3Ass%2Fword@[2001:db8::1]:3128"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"host": "", "port": 8080}, "host"),
        ({"host": "proxy.test", "port": 0}, "port"),
        ({"host": "proxy.test", "port": 8080, "password": "secret"}, "password"),
    ],
)
def test_proxy_configuration_validates_invalid_values(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ProxyConfig(**kwargs)


def test_response_headers_are_case_insensitive_and_errors_are_exposed() -> None:
    response = Response(
        url="https://example.test/missing",
        status_code=404,
        headers={"Content-Type": "application/json"},
        cookies=(),
        text="{}",
        content=b"{}",
        elapsed=0.01,
    )

    assert response.headers["content-type"] == "application/json"
    with pytest.raises(HTTPError):
        response.raise_for_status()


def test_storage_state_round_trips_and_validates_its_shape() -> None:
    state = StorageState.from_dict(
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": "example.test",
                    "path": "/",
                    "secure": True,
                    "http_only": True,
                    "same_site": "Lax",
                }
            ]
        }
    )

    restored = StorageState.from_json(state.to_json())

    assert restored == state
    with pytest.raises(ValueError, match="cookies"):
        StorageState.from_dict({})
    with pytest.raises(ValueError, match="booleans"):
        StorageState.from_dict({"cookies": [{"name": "a", "value": "b", "secure": "false"}]})


def test_retry_config_normalizes_methods_and_calculates_backoff() -> None:
    config = RetryConfig(max_attempts=3, backoff_factor=0.1, allowed_methods=frozenset({"get"}))

    assert config.should_retry_status("GET", 503)
    assert config.delay_for_retry(3) == pytest.approx(0.4)
    with pytest.raises(ValueError, match="max_attempts"):
        RetryConfig(max_attempts=0)
