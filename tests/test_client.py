from unittest.mock import patch

from phantom_curl import PhantomClient, ProxyConfig, Response, RetryConfig, StealthConfig, StorageState


def _successful_response() -> Response:
    return Response(
        url="https://example.test",
        status_code=200,
        headers={},
        cookies=(),
        text="",
        content=b"",
        elapsed=0,
    )


def test_public_api_exports_client_and_config() -> None:
    client = PhantomClient(StealthConfig(impersonate="chrome"))
    client.close()


def test_client_get_passes_query_parameters_and_headers(phantom_client, http_server: str) -> None:
    response = phantom_client.get(
        f"{http_server}/get",
        params={"q": "python"},
        headers={"User-Agent": "phantom-curl-test"},
    )

    assert response.status_code == 200
    assert response.ok is True
    assert response.json() == {"args": {"q": "python"}, "headers": {"User-Agent": "phantom-curl-test"}}


def test_client_post_serializes_nested_json(phantom_client, http_server: str) -> None:
    payload = {"key": "value", "nested": {"count": 1}, "tags": ["one", "two"]}

    response = phantom_client.post(f"{http_server}/post", json=payload)

    assert response.status_code == 200
    assert response.json() == {"json": payload}


def test_client_persists_session_cookies(phantom_client, http_server: str) -> None:
    response = phantom_client.get(f"{http_server}/set-cookie")

    assert response.status_code == 200
    assert phantom_client.cookies["session_id"] == "abc123"
    assert phantom_client.get(f"{http_server}/cookies").json() == {"session_id": "abc123"}


def test_client_restores_cookie_storage_state(phantom_client, http_server: str) -> None:
    phantom_client.get(f"{http_server}/set-cookie")
    serialized_state = phantom_client.export_storage_state().to_json()

    with PhantomClient() as restored_client:
        restored_client.import_storage_state(StorageState.from_json(serialized_state))
        assert restored_client.get(f"{http_server}/cookies").json() == {"session_id": "abc123"}


def test_client_get_uses_a_per_request_retry_override(phantom_client, http_server: str) -> None:
    override = RetryConfig(max_attempts=3, backoff_factor=0, retry_status_codes=frozenset({503}))

    response = phantom_client.get(f"{http_server}/flaky-override", retry_config=override)

    assert response.status_code == 200
    assert response.json() == {"attempt": 3}
    assert phantom_client.retry_config.max_attempts == 1


def test_each_http_method_forwards_its_retry_override(phantom_client) -> None:
    override = RetryConfig(max_attempts=2, backoff_factor=0)

    with patch.object(phantom_client._session, "request", return_value=_successful_response()) as request:
        phantom_client.get("https://example.test", retry_config=override)
        phantom_client.head("https://example.test", retry_config=override)
        phantom_client.options("https://example.test", retry_config=override)
        phantom_client.post("https://example.test", retry_config=override)
        phantom_client.put("https://example.test", retry_config=override)
        phantom_client.patch("https://example.test", retry_config=override)
        phantom_client.delete("https://example.test", retry_config=override)

    assert [call.args[0].method for call in request.call_args_list] == [
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ]
    assert all(call.args[0].retry_config is override for call in request.call_args_list)


def test_each_http_method_preserves_the_active_retry_policy_when_max_attempts_is_overridden() -> None:
    policy = RetryConfig(
        max_attempts=4,
        backoff_factor=0.75,
        retry_status_codes=frozenset({418}),
        allowed_methods=frozenset({"GET"}),
    )

    with PhantomClient(retry_config=policy) as client:
        with patch.object(client._session, "request", return_value=_successful_response()) as request:
            client.get("https://example.test", max_attempts=2)
            client.head("https://example.test", max_attempts=2)
            client.options("https://example.test", max_attempts=2)
            client.post("https://example.test", max_attempts=2)
            client.put("https://example.test", max_attempts=2)
            client.patch("https://example.test", max_attempts=2)
            client.delete("https://example.test", max_attempts=2)

    effective_policies = [call.args[0].retry_config for call in request.call_args_list]
    assert all(effective is not None for effective in effective_policies)
    assert all(effective.max_attempts == 2 for effective in effective_policies)
    assert all(effective.backoff_factor == 0.75 for effective in effective_policies)
    assert all(effective.retry_status_codes == frozenset({418}) for effective in effective_policies)
    assert all(effective.allowed_methods == frozenset({"GET"}) for effective in effective_policies)
    assert client.retry_config is policy


def test_client_normalizes_proxy_strings_before_the_network_layer(phantom_client) -> None:
    proxy_url = "http://user%20name:pass%2Fword@proxy.test:8080"

    with patch.object(phantom_client._session, "request", return_value=_successful_response()) as request:
        phantom_client.get("https://example.test", proxy=proxy_url)
        phantom_client.get(
            "https://example.test",
            proxies={"http": proxy_url, "https": ProxyConfig(host="secure-proxy.test", port=8443)},
        )

    single_proxy_options = request.call_args_list[0].args[0]
    per_protocol_options = request.call_args_list[1].args[0]

    assert isinstance(single_proxy_options.proxy, ProxyConfig)
    assert single_proxy_options.proxy.url == proxy_url
    assert per_protocol_options.proxies is not None
    assert all(isinstance(proxy, ProxyConfig) for proxy in per_protocol_options.proxies.values())
    assert per_protocol_options.proxies["http"].url == proxy_url
    assert per_protocol_options.proxies["https"].url == "http://secure-proxy.test:8443"


def test_client_get_uses_a_per_request_max_attempts_override(phantom_client, http_server: str) -> None:
    override = RetryConfig(max_attempts=1, backoff_factor=0.1)

    response = phantom_client.get(f"{http_server}/flaky-override", max_attempts=3, retry_config=override)

    assert response.status_code == 200
    assert response.json() == {"attempt": 3}
    assert phantom_client.retry_config.max_attempts == 1


def test_client_get_uses_a_per_request_max_attempts_override_with_no_retry_config(
    phantom_client, http_server: str
) -> None:
    response = phantom_client.get(f"{http_server}/flaky-override", max_attempts=3)

    assert response.status_code == 200
    assert response.json() == {"attempt": 3}
    assert phantom_client.retry_config.max_attempts == 1

def test_client_restores_local_storage_from_storage_state(phantom_client) -> None:
    raw_state = {
        "cookies": [],
        "origins": [
            {
                "origin": "https://one.test",
                "localStorage": [
                    {"name": "language", "value": "en-UK"}
                ]
            }
        ]
    }

    state = StorageState.from_dict(raw_state)

    phantom_client.import_storage_state(state)
    restored = phantom_client.export_storage_state()

    assert state == restored


def test_client_import_storage_state_merges_local_storage_when_not_clearing(phantom_client) -> None:
    initial_state = StorageState.from_dict(
        {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://one.test",
                    "localStorage": [
                        {"name": "theme", "value": "dark"},
                        {"name": "language", "value": "uk"},
                    ],
                },
                {
                    "origin": "https://two.test",
                    "localStorage": [{"name": "layout", "value": "grid"}],
                },
            ],
        }
    )
    update_state = StorageState.from_dict(
        {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://one.test",
                    "localStorage": [{"name": "theme", "value": "light"}],
                },
            ],
        }
    )

    phantom_client.import_storage_state(initial_state)
    phantom_client.import_storage_state(update_state, clear_existing=False)

    assert phantom_client.export_storage_state().to_dict()["origins"] == [
        {
            "origin": "https://one.test",
            "localStorage": [
                {"name": "theme", "value": "light"},
                {"name": "language", "value": "uk"},
            ],
        },
        {
            "origin": "https://two.test",
            "localStorage": [{"name": "layout", "value": "grid"}],
        },
    ]


def test_client_import_storage_state_clears_existing_local_storage(phantom_client) -> None:
    initial_state = StorageState.from_dict(
        {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://one.test",
                    "localStorage": [{"name": "theme", "value": "dark"}],
                },
                {
                    "origin": "https://two.test",
                    "localStorage": [{"name": "layout", "value": "grid"}],
                },
            ],
        }
    )
    replacement_state = StorageState.from_dict(
        {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://one.test",
                    "localStorage": [{"name": "theme", "value": "light"}],
                },
            ],
        }
    )

    phantom_client.import_storage_state(initial_state)
    phantom_client.import_storage_state(replacement_state)

    assert phantom_client.export_storage_state().to_dict()["origins"] == [
        {
            "origin": "https://one.test",
            "localStorage": [{"name": "theme", "value": "light"}],
        }
    ]
