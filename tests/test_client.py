from unittest.mock import patch

from phantom_curl import PhantomClient, Response, RetryConfig, StealthConfig, StorageState


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
    response = Response(
        url="https://example.test",
        status_code=200,
        headers={},
        cookies=(),
        text="",
        content=b"",
        elapsed=0,
    )
    override = RetryConfig(max_attempts=2, backoff_factor=0)

    with patch.object(phantom_client._session, "request", return_value=response) as request:
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
