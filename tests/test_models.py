import pytest

from phantom_curl.exceptions import HTTPError
from phantom_curl.models import ProxyConfig, RequestOptions, Response, RetryConfig, StorageState

from urllib.parse import quote

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

def test_proxy_config_from_string_parses_valid_url() -> None:
    proxy_str = "http://host:8080"
    proxy = ProxyConfig.from_string(proxy_str)
    assert proxy.host == "host"
    assert proxy.port == 8080
    assert proxy.url == proxy_str

def test_proxy_config_from_string_parses_valid_url_with_credentials() -> None:
    proxy_str = "http://user%20code:pass@host:8080"
    proxy = ProxyConfig.from_string(proxy_str)
    assert proxy.username == "user code"
    assert proxy.password == "pass"
    assert proxy.url == proxy_str

def test_proxy_config_from_string_parses_valid_ipv6_url() -> None:
    proxy_str = "http://[::1]:8080"
    proxy = ProxyConfig.from_string(proxy_str)
    assert proxy.host == "::1"
    assert proxy.port == 8080
    assert proxy.url == proxy_str

def test_proxy_config_from_string_parses_valid_ipv6_url_with_credentials() -> None:
    proxy_str = "http://user:pass@[::1]:8080"
    proxy = ProxyConfig.from_string(proxy_str)
    assert proxy.username == "user"
    assert proxy.password == "pass"
    assert proxy.host == "::1"
    assert proxy.port == 8080
    assert proxy.url == proxy_str

def test_proxy_config_from_string_parses_valid_urls_with_credentials() -> None:
    proxies_to_test = {
        "http": "http://user:pass@host:1020",
        "https": "https://user%20123:pa%2F1ss@host:8080",
    }
    proxies = {
        protocol: proxy.url if isinstance(proxy, ProxyConfig) else ProxyConfig.from_string(proxy)
        for protocol, proxy in proxies_to_test.items()
    }

    assert proxies["http"].username == "user"
    assert proxies["http"].port == 1020
    assert proxies["https"].username == "user 123"
    assert proxies["https"].port == 8080

    assert proxies["http"].url == proxies_to_test["http"]
    assert proxies["https"].url == proxies_to_test["https"]

def test_proxy_config_from_string_raises_for_invalid_urls() -> None:
    invalid_urls = [
        "http://host",  # missing port
        "http://:8080",  # missing host
        "http://user:pass@:8080",  # missing host
        "not-a-url",  # not a URL at all
    ]
    for url in invalid_urls:
        with pytest.raises(ValueError, match="Invalid proxy URL"):
            ProxyConfig.from_string(url)

def test_proxy_config_from_string_allows_username_without_password() -> None:
    proxy = ProxyConfig.from_string("http://user@host:8080")

    assert proxy.username == "user"
    assert proxy.password is None
    assert proxy.url == "http://user@host:8080"

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
    assert response.is_redirect is False
    assert response.is_client_error is True
    assert response.is_server_error is False
    assert list(response.iter_bytes(1)) == [b"{", b"}"]
    assert list(response.iter_lines()) == ["{}"]
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