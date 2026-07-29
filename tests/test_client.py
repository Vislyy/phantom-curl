from phantom_curl import PhantomClient, StealthConfig, StorageState


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


def test_page_uses_final_redirect_url_and_executes_only_classic_scripts(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/redirect-page")
    body = page.query_selector("body")

    assert page.url == f"{http_server}/page/"
    assert body is not None
    assert body.get_attribute("inline-ran") == "yes"
    assert body.get_attribute("external-ran") == "yes"
    assert body.get_attribute("module-ran") is None
    assert page.script_errors == []
