from phantom_curl.exceptions import JSRuntimeError


def test_new_page_has_no_navigation_state(phantom_client) -> None:
    page = phantom_client.new_page()

    assert page.is_loaded is False
    assert page.url is None
    assert page.response is None
    assert page.status_code is None
    assert page.ok is None
    assert page.script_errors == []


def test_page_navigation_exposes_document_and_response_state(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/redirect-page")

    assert page.is_loaded is True
    assert page.url == f"{http_server}/page/"
    assert page.status_code == 200
    assert page.ok is True
    assert page.content() == page.html
    assert page.title == ""
    assert page.head is not None
    assert page.body is not None
    assert len(page.query_selector_all("script")) == 4
    assert page.query_selector(".missing") is None


def test_page_executes_supported_scripts_and_skips_unsupported_types(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/redirect-page")
    body = page.body

    assert body is not None
    assert body.get_attribute("inline-ran") == "yes"
    assert body.get_attribute("external-ran") == "yes"
    assert body.get_attribute("module-ran") is None
    assert page.evaluate("document.body.tagName") == "BODY"
    assert page.eval("2 + 2") == 4
    assert page.script_errors == []


def test_page_records_inline_script_errors_and_continues_loading(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/broken-page/")

    assert page.is_loaded is True
    assert page.body is not None
    assert len(page.script_errors) == 1
    assert isinstance(page.script_errors[0], JSRuntimeError)


def test_page_referrer_is_set_correctly(phantom_client, http_server: str) -> None:
    first_url = f"{http_server}/page/?step=one"
    second_url = f"{http_server}/page/?step=two"

    page = phantom_client.new_page(first_url)

    assert page.status_code == 200
    assert page.referrer == page.eval("document.referrer") == ""

    page.goto(second_url)

    assert page.status_code == 200
    assert page.referrer == page.eval("document.referrer") == first_url
