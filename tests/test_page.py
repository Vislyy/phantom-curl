import json

from phantom_curl import PhantomClient, StealthConfig
from phantom_curl.models import StorageState
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


def test_page_executes_supported_classic_and_module_scripts(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/redirect-page")
    body = page.body

    assert body is not None
    assert body.get_attribute("inline-ran") == "yes"
    assert body.get_attribute("external-ran") == "yes"
    assert body.get_attribute("module-ran") == "yes"
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


def test_page_uses_default_navigator_languages(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    navigator = json.loads(
        page.eval("JSON.stringify({language: navigator.language, languages: navigator.languages})")
    )

    assert navigator == {"language": "en-US", "languages": ["en-US", "en"]}


def test_page_navigator_languages_follow_stealth_config(http_server: str) -> None:
    config = StealthConfig(languages=("uk-UA", "uk", "en-US"))

    with PhantomClient(stealth_config=config) as client:
        page = client.new_page(f"{http_server}/page/")
        navigator = json.loads(
            page.eval("JSON.stringify({language: navigator.language, languages: navigator.languages})")
        )

    assert navigator == {"language": "uk-UA", "languages": ["uk-UA", "uk", "en-US"]}


def test_page_fetches_a_same_origin_get_with_session_state(phantom_client, http_server: str) -> None:
    phantom_client.get(f"{http_server}/set-cookie")
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        "fetch('/api/value')"
        ".then(response => response.json().then(body => ({status: response.status, ok: response.ok, url: response.url, body})))"
        ".then(result => document.body.setAttribute('fetch-result', JSON.stringify(result)));"
    )
    result = json.loads(page.eval("document.body.getAttribute('fetch-result')"))

    assert result == {
        "status": 200,
        "ok": True,
        "url": f"{http_server}/api/value",
        "body": {
            "value": "from-api",
            "referer": f"{http_server}/page/",
            "cookies": {"session_id": "abc123"},
        },
    }


def test_page_scripts_can_use_fetch(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/fetch-page/")
    body = page.body

    assert body is not None
    assert body.get_attribute("fetch-value") == "from-api"
    assert page.script_errors == []


def test_page_fetch_rejects_cross_origin_urls(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        "fetch('https://example.test/api')"
        ".catch(error => document.body.setAttribute('cross-origin-error', error.message));"
    )
    assert "same-origin" in page.eval("document.body.getAttribute('cross-origin-error')")


def test_page_fetches_a_post_with_headers_and_a_string_body(phantom_client, http_server: str) -> None:
    phantom_client.get(f"{http_server}/set-cookie")
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        "fetch('/api/echo', {"
        "method: 'POST', headers: {'Content-Type': 'application/json', 'X-Page': 'yes'}, body: '{\"answer\": 42}'"
        "})"
        ".then(response => response.json())"
        ".then(result => document.body.setAttribute('post-result', JSON.stringify(result)));"
    )
    result = json.loads(page.eval("document.body.getAttribute('post-result')"))

    assert result == {
        "body": '{"answer": 42}',
        "header": "yes",
        "referer": f"{http_server}/page/",
        "cookies": {"session_id": "abc123"},
    }


def test_page_document_cookie_reads_and_writes_the_shared_session(phantom_client, http_server: str) -> None:
    phantom_client.get(f"{http_server}/set-cookie")
    page = phantom_client.new_page(f"{http_server}/page/")

    assert page.eval("document.cookie") == "session_id=abc123"

    page.eval("document.cookie = 'theme=dark; Path=/';")

    assert page.eval("document.cookie") == "session_id=abc123; theme=dark"
    assert phantom_client.get(f"{http_server}/cookies").json() == {"session_id": "abc123", "theme": "dark"}


def test_page_document_cookie_is_available_to_fetch_in_the_same_script(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        "document.cookie = 'page-token=abc; Path=/';"
        "fetch('/api/value')"
        ".then(response => response.json())"
        ".then(result => document.body.setAttribute('fetch-cookies', JSON.stringify(result.cookies)));"
    )

    assert json.loads(page.eval("document.body.getAttribute('fetch-cookies')")) == {"page-token": "abc"}


def test_page_document_cookie_cannot_overwrite_http_only_cookie(phantom_client, http_server) -> None:
    phantom_client.get(f"{http_server}/set-http-only-cookie")

    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval("document.cookie = 'hidden=changed; Path=/';")

    assert page.eval("document.cookie") == "visible=yes"

    assert phantom_client.get(f"{http_server}/cookies").json() == {
        "visible": "yes",
        "hidden": "no",
    }

def test_page_fetch_updates_document_cookie_before_then_callbacks(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        "fetch('/api/set-cookie')"
        ".then(() => document.body.setAttribute('cookie-after-fetch', document.cookie));"
    )

    assert page.eval("document.body.getAttribute('cookie-after-fetch')") == "from_fetch=yes"


def test_page_document_cookie_hides_http_only_session_cookies(phantom_client, http_server: str) -> None:
    phantom_client.get(f"{http_server}/set-http-only-cookie")
    page = phantom_client.new_page(f"{http_server}/page/")

    assert page.eval("document.cookie") == "visible=yes"
    assert phantom_client.get(f"{http_server}/cookies").json() == {"visible": "yes", "hidden": "no"}


def test_page_runs_microtasks_and_zero_delay_timeouts_after_scripts(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/timer-page/")
    body = page.body

    assert body is not None
    assert body.get_attribute("microtask-ran") == "yes"
    assert body.get_attribute("timeout-ran") == "yes"


def test_page_can_clear_a_timeout(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        "const timer = setTimeout(() => document.body.setAttribute('cleared-timeout', 'no'), 0);"
        "clearTimeout(timer);"
    )

    assert page.eval("document.body.getAttribute('cleared-timeout')") is None


def test_page_loads_modules_and_caches_shared_dependencies(
    phantom_client, http_server: str, math_module_request_count
) -> None:
    page = phantom_client.new_page(f"{http_server}/module-page/")
    body = page.body

    assert body is not None
    assert body.get_attribute("first-module-answer") == "42"
    assert body.get_attribute("second-module-answer") == "42"
    assert body.get_attribute("module-default-and-namespace") == "math:42"
    assert body.get_attribute("external-module-ran") == "yes"
    assert math_module_request_count() == 1
    assert page.script_errors == []


def test_page_loads_a_simple_cyclic_module_graph(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/cycle-module-page/")

    assert page.body is not None
    assert page.body.get_attribute("cycle-module-answer") == "a"
    assert page.script_errors == []


def test_page_reports_missing_module_urls_and_importers(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/missing-module-page/")

    assert len(page.script_errors) == 1
    assert "missing.js" in str(page.script_errors[0])
    assert "missing-module-page" in str(page.script_errors[0])

def test_page_set_attribute_with_set_timeout(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        "setTimeout("
        "() => document.body.setAttribute('delayed-timeout', 'yes'), "
        "25"
        ");"
    )

    assert page.eval("document.body.getAttribute('delayed-timeout')") is None

    page.run_event_loop(timeout=0.1)

    assert page.eval("document.body.getAttribute('delayed-timeout')") == "yes"

def test_page_executes_a_dynamically_inserted_script(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/dynamic-script-page/")

    assert page.body is not None
    assert page.body.get_attribute("dynamic-script-ran") == "yes"

def test_page_executes_a_dynamically_inserted_script_chain(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/dynamic-script-chain-page/")

    assert page.body.get_attribute("first-dynamic-script-ran") == "yes"
    assert page.body.get_attribute("second-dynamic-script-ran") == "yes"

def test_page_executes_a_relative_path_script(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/dynamic-script-relative-page/")

    assert page.body.get_attribute("relative-dynamic-script-ran") == "yes"
    assert page.script_errors == []

def test_page_records_errors_from_dynamically_inserted_scripts(
    phantom_client, http_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/dynamic-script-error-page/")

    assert page.is_loaded is True
    assert page.body is not None
    assert len(page.script_errors) == 1
    assert isinstance(page.script_errors[0], JSRuntimeError)
    assert "dynamic script failure" in str(page.script_errors[0])

def test_page_local_storage_reads_imported_state(
    phantom_client, http_server: str
) -> None:
    state = StorageState.from_dict(
        {
            "cookies": [],
            "origins": [
                {
                    "origin": http_server,
                    "localStorage": [
                        {"name": "theme", "value": "dark"},
                    ],
                }
            ],
        }
    )
    phantom_client.import_storage_state(state)

    page = phantom_client.new_page(f"{http_server}/page/")

    assert page.eval("localStorage.getItem('theme')") == "dark"


def test_page_local_storage_persists_writes_to_storage_state(
    phantom_client, http_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval("localStorage.setItem('theme', 'dark');")

    assert phantom_client.export_storage_state().to_dict()["origins"] == [
        {
            "origin": http_server,
            "localStorage": [{"name": "theme", "value": "dark"}],
        }
    ]


def test_page_local_storage_preserves_empty_keys_and_values(
    phantom_client, http_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval("localStorage.setItem('', '');")

    assert page.eval("localStorage.getItem('')") == ""
    assert phantom_client.export_storage_state().to_dict()["origins"] == [
        {
            "origin": http_server,
            "localStorage": [{"name": "", "value": ""}],
        }
    ]


def test_page_local_storage_exposes_length_and_key(
    phantom_client, http_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval("localStorage.setItem('first', '1'); localStorage.setItem('second', '2');")

    assert page.eval("localStorage.length") == 2
    assert page.eval("localStorage.key(0)") == "first"
    assert page.eval("localStorage.key(1)") == "second"
    assert page.eval("localStorage.key(2)") is None


def test_page_local_storage_remove_item_updates_storage_state(
    phantom_client, http_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")
    page.eval("localStorage.setItem('keep', 'yes'); localStorage.setItem('remove', 'no');")

    page.eval("localStorage.removeItem('remove');")

    assert page.eval("localStorage.getItem('remove')") is None
    assert phantom_client.export_storage_state().to_dict()["origins"] == [
        {
            "origin": http_server,
            "localStorage": [{"name": "keep", "value": "yes"}],
        }
    ]


def test_page_local_storage_clear_updates_storage_state(
    phantom_client, http_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")
    page.eval("localStorage.setItem('first', '1'); localStorage.setItem('second', '2');")

    page.eval("localStorage.clear();")

    assert page.eval("localStorage.length") == 0
    assert phantom_client.export_storage_state().to_dict()["origins"] == [
        {
            "origin": http_server,
            "localStorage": [],
        }
    ]
