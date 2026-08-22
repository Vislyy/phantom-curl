import json

from phantom_curl import OriginPolicy, PhantomClient, StealthConfig
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


def test_page_exposes_current_script_and_stringifiable_location(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/current-script-page/")
    body = page.body

    assert body is not None
    assert body.get_attribute("current-script-parent") == "BODY"
    assert body.get_attribute("resolved-base-url") == f"{http_server}/current-script-page/"
    assert page.eval("document.currentScript") is None


def test_page_url_constructs_and_resolves_relative_urls(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const url = new URL(
                "../product?id=7#details",
                "https://example.test/catalog/items/",
            );

            JSON.stringify({
                isExposedOnWindow: window.URL === URL && window.URLSearchParams === URLSearchParams,
                href: url.href,
                origin: url.origin,
                protocol: url.protocol,
                hostname: url.hostname,
                pathname: url.pathname,
                search: url.search,
                hash: url.hash,
            });
            """
        )
    )

    assert result == {
        "isExposedOnWindow": True,
        "href": "https://example.test/catalog/product?id=7#details",
        "origin": "https://example.test",
        "protocol": "https:",
        "hostname": "example.test",
        "pathname": "/catalog/product",
        "search": "?id=7",
        "hash": "#details",
    }


def test_page_url_search_params_read_and_update_query_strings(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const params = new URLSearchParams("tag=python&tag=web+api");
            params.append("page", 2);
            params.set("tag", "runtime");

            const url = new URL("https://example.test/articles?sort=recent");
            url.searchParams.append("tag", "browser runtime");

            JSON.stringify({
                tag: params.get("tag"),
                tags: params.getAll("tag"),
                page: params.get("page"),
                encoded: params.toString(),
                href: url.href,
                search: url.search,
            });
            """
        )
    )

    assert result == {
        "tag": "runtime",
        "tags": ["runtime"],
        "page": "2",
        "encoded": "tag=runtime&page=2",
        "href": "https://example.test/articles?sort=recent&tag=browser+runtime",
        "search": "?sort=recent&tag=browser+runtime",
    }


def test_page_headers_normalize_and_iterate_values(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const headers = new Headers({"X-Request-ID": "first", "Accept": "application/json"});
            headers.append("x-request-id", "second");
            headers.set("Content-Type", " text/plain ");

            JSON.stringify({
                isExposedOnWindow: window.Headers === Headers,
                accept: headers.get("ACCEPT"),
                requestId: headers.get("X-Request-ID"),
                hasContentType: headers.has("content-type"),
                missing: headers.get("missing"),
                entries: Array.from(headers),
            });
            """
        )
    )

    assert result == {
        "isExposedOnWindow": True,
        "accept": "application/json",
        "requestId": "first, second",
        "hasContentType": True,
        "missing": None,
        "entries": [
            ["accept", "application/json"],
            ["content-type", "text/plain"],
            ["x-request-id", "first, second"],
        ],
    }


def test_page_form_data_tracks_string_entries(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const formData = new FormData();
            formData.append("tag", "python");
            formData.append("tag", "browser");
            formData.append("page", 2);
            formData.append("obsolete", "remove me");
            formData.delete("obsolete");
            formData.set("tag", "runtime");

            JSON.stringify({
                isExposedOnWindow: window.FormData === FormData,
                tag: formData.get("tag"),
                tags: formData.getAll("tag"),
                page: formData.get("page"),
                hasMissing: formData.has("missing"),
                hasObsolete: formData.has("obsolete"),
                entries: Array.from(formData),
            });
            """
        )
    )

    assert result == {
        "isExposedOnWindow": True,
        "tag": "runtime",
        "tags": ["runtime"],
        "page": "2",
        "hasMissing": False,
        "hasObsolete": False,
        "entries": [["tag", "runtime"], ["page", "2"]],
    }


def test_page_abort_controller_exposes_signal_lifecycle(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const controller = new AbortController();
            const eventTypes = [];
            controller.signal.addEventListener("abort", event => eventTypes.push(event.type));
            controller.abort("stop now");
            controller.abort("ignored");

            let thrownReason = null;
            try {
                controller.signal.throwIfAborted();
            } catch (reason) {
                thrownReason = reason;
            }

            JSON.stringify({
                isExposedOnWindow:
                    window.AbortController === AbortController && window.AbortSignal === AbortSignal,
                aborted: controller.signal.aborted,
                reason: controller.signal.reason,
                eventTypes,
                thrownReason,
            });
            """
        )
    )

    assert result == {
        "isExposedOnWindow": True,
        "aborted": True,
        "reason": "stop now",
        "eventTypes": ["abort"],
        "thrownReason": "stop now",
    }

def test_page_fetch_response_headers_shared_with_js(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        """
        fetch("/api/response-headers")
            .then(response => {
                document.body.setAttribute(
                    "result",
                    JSON.stringify({
                        isHeaders: response.headers instanceof Headers,
                        responseId: response.headers.get("x-response-id"),
                        contentType: response.headers.get("content-type"),
                    })
                );
            });
        """
    )

    result = json.loads(page.eval("document.body.getAttribute('result')"))

    assert result == {
        "isHeaders": True,
        "responseId": "abc123",
        "contentType": "application/json"
    }

def test_page_fetch_aborts_before_the_network_request_starts(
    phantom_client, http_server: str, abortable_request_count
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        """
        const controller = new AbortController();
        fetch("/api/abortable", {signal: controller.signal})
            .catch(error => document.body.setAttribute("abort-error-name", error.name));
        controller.abort();
        """
    )

    assert page.eval("document.body.getAttribute('abort-error-name')") == "AbortError"
    assert abortable_request_count() == 0


def test_page_fetch_sends_string_form_data_as_multipart(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        """
        const formData = new FormData();
        formData.append("name", "Ada");
        formData.append("role", "developer");

        fetch("/api/echo", {method: "POST", body: formData})
            .then(response => response.json())
            .then(result => {
                document.body.setAttribute("form-data-result", JSON.stringify(result));
            });
        """
    )

    result = json.loads(page.eval("document.body.getAttribute('form-data-result')"))

    assert result["content_type"].startswith("multipart/form-data; boundary=----PhantomCurlFormBoundary")
    assert 'Content-Disposition: form-data; name="name"\r\n\r\nAda\r\n' in result["body"]
    assert 'Content-Disposition: form-data; name="role"\r\n\r\ndeveloper\r\n' in result["body"]


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


def test_page_fetch_allows_a_cross_origin_on_its_allowlist(http_server: str, cross_origin_server: str) -> None:
    policy = OriginPolicy(allowed_origins=(cross_origin_server,))

    with PhantomClient(origin_policy=policy) as client:
        page = client.new_page(f"{http_server}/page/")
        page.eval(
            "fetch(" + json.dumps(f"{cross_origin_server}/api/value") + ")"
            ".then(response => response.json())"
            ".then(result => document.body.setAttribute('cross-origin-result', JSON.stringify(result)));"
        )
        result = json.loads(page.eval("document.body.getAttribute('cross-origin-result')"))

    assert result == {
        "value": "from-api",
        "referer": f"{http_server}/page/",
        "cookies": {},
    }


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
        "content_type": "application/json",
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


def test_page_loads_named_and_star_reexports(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/reexport-module-page/")

    assert page.body is not None
    assert page.body.get_attribute("named-reexport-result") == "named"
    assert page.body.get_attribute("star-reexport-result") == "one:two:undefined"
    assert page.body.get_attribute("export-after-brace-result") == "after-brace"
    assert page.script_errors == []


def test_page_handles_common_static_module_export_forms_and_dependency_order(
    phantom_client, http_server: str
) -> None:
    """Static dependencies run before module bodies and common exports remain importable."""
    page = phantom_client.new_page(f"{http_server}/static-module-semantics-page/")

    assert page.body is not None
    assert page.body.get_attribute("static-module-semantics") == (
        "named-default:function:anonymous-function:named-class:anonymous-class:namespace:"
        "dependency-body>entry-body"
    )
    assert page.script_errors == []


def test_page_keeps_supported_imports_and_exports_live_across_a_cycle(
    phantom_client, http_server: str
) -> None:
    """Imports observe a later exported assignment and deferred cyclic read."""
    page = phantom_client.new_page(f"{http_server}/live-binding-module-page/")

    assert page.body is not None
    assert page.body.get_attribute("live-binding-result") == "after:after:ready"
    assert page.script_errors == []


def test_page_reports_a_tdz_read_from_a_live_cyclic_binding(phantom_client, http_server: str) -> None:
    """A real early cyclic read must fail instead of becoming a silent undefined."""
    page = phantom_client.new_page(f"{http_server}/live-binding-tdz-page/")

    assert len(page.script_errors) == 1
    error = str(page.script_errors[0])
    assert "live-tdz-a.js" in error
    assert "live-tdz-b.js" in error
    assert "a is not initialized" in error


def test_page_reports_an_excerpt_for_unsupported_esm_syntax(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/unsupported-module-page/")

    assert len(page.script_errors) == 1
    error = str(page.script_errors[0])
    assert "unsupported-export.js" in error
    assert "unsupported ESM syntax near" in error
    assert "export async function* load()" in error


def test_page_reports_the_module_execution_error_load_chain(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/module-execution-error-page/")

    assert len(page.script_errors) == 1
    error = str(page.script_errors[0])
    assert "execution-error-leaf.js" in error
    assert "execution-error-entry.js" in error
    assert "load chain" in error
    assert "value is not initialized" in error


def test_page_follows_a_navigation_queued_by_location_href(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/start-navigation/")

    page.run_event_loop(timeout=0.1)

    assert page.url == f"{http_server}/navigation-target/"
    assert page.body is not None
    assert page.body.get_attribute("data-navigation-target") == "yes"
    assert page.script_errors == []


def test_page_follows_a_navigation_queued_by_location_replace(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/replace-navigation/")

    assert page.url == f"{http_server}/navigation-target/"
    assert page.body is not None
    assert page.body.get_attribute("data-navigation-target") == "yes"


def test_page_eval_automatically_follows_a_queued_location_navigation(
    phantom_client, http_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval("location.assign('/navigation-target/');")

    assert page.url == f"{http_server}/navigation-target/"
    assert page.body is not None
    assert page.body.get_attribute("data-navigation-target") == "yes"


def test_page_history_changes_spa_routes_without_a_document_navigation(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const popStates = [];
            window.addEventListener('popstate', function (event) {
                popStates.push(event.state);
            });

            const initialUrl = location.href;
            const sourceState = {route: 'search'};
            history.pushState(sourceState, '', '/search?query=phantom#result');
            sourceState.route = 'changed-after-push';
            const copiedState = history.state.route;

            history.replaceState({route: 'results', page: 2}, '', '/results?page=2');
            history.back();
            history.forward();

            JSON.stringify({
                initialUrl: initialUrl,
                href: location.href,
                pathname: location.pathname,
                search: location.search,
                hash: location.hash,
                length: history.length,
                state: history.state,
                copiedState: copiedState,
                popStates: popStates,
                hasWindowHistory: window.history === history,
            });
            """
        )
    )

    assert result == {
        "initialUrl": f"{http_server}/page/",
        "href": f"{http_server}/results?page=2",
        "pathname": "/results",
        "search": "?page=2",
        "hash": "",
        "length": 2,
        "state": {"route": "results", "page": 2},
        "copiedState": "search",
        "popStates": [None, {"route": "results", "page": 2}],
        "hasWindowHistory": True,
    }
    assert page.url == f"{http_server}/page/"


def test_page_history_rejects_cross_origin_routes(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            let error = null;
            try {
                history.pushState({route: 'blocked'}, '', 'https://example.com/other');
            } catch (caught) {
                error = String(caught);
            }
            JSON.stringify({
                href: location.href,
                length: history.length,
                state: history.state,
                error: error,
            });
            """
        )
    )

    assert result == {
        "href": f"{http_server}/page/",
        "length": 1,
        "state": None,
        "error": "Error: PhantomCurl history only permits same-origin URLs",
    }


def test_page_click_follows_a_regular_anchor_link(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/anchor-page/")

    link = page.query_selector("#regular-link")
    assert link is not None
    link.click()

    assert page.url == f"{http_server}/navigation-target/"
    assert page.body is not None
    assert page.body.get_attribute("data-navigation-target") == "yes"


def test_page_click_does_not_follow_a_prevented_anchor_link(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/anchor-page/")

    link = page.query_selector("#prevented-link")
    assert link is not None
    link.click()

    assert page.url == f"{http_server}/anchor-page/"
    assert page.body is not None
    assert page.body.get_attribute("prevented-click-ran") == "yes"


def test_page_click_does_not_follow_an_anchor_for_another_context(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/anchor-page/")

    link = page.query_selector("#new-context-link")
    assert link is not None
    link.click()

    assert page.url == f"{http_server}/anchor-page/"


def test_page_click_submits_a_supported_get_form(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/get-form-page/")

    query = page.query_selector("#query-input")
    submit = page.query_selector("#search-submit")
    assert query is not None
    assert submit is not None

    query.type("phantom curl")
    submit.click()

    assert page.url == f"{http_server}/form-target/?query=phantom+curl&featured=yes"
    assert page.body is not None
    assert page.body.get_attribute("data-query") == "phantom curl"
    assert page.body.get_attribute("data-featured") == "yes"


def test_page_click_does_not_submit_a_prevented_form(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/get-form-page/")

    submit = page.query_selector("#prevented-submit")
    assert submit is not None
    submit.click()

    assert page.url == f"{http_server}/get-form-page/"
    assert page.body is not None
    assert page.body.get_attribute("prevented-submit-ran") == "yes"


def test_page_click_toggles_checkbox_and_dispatches_control_events(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/form-controls-page/")

    checkbox = page.query_selector("#feature-toggle")
    assert checkbox is not None
    assert page.eval("document.querySelector('#feature-toggle').checked") is True

    checkbox.click()

    assert page.eval("document.querySelector('#feature-toggle').checked") is False
    assert page.body is not None
    assert page.body.get_attribute("checkbox-input") == "false"
    assert page.body.get_attribute("checkbox-change") == "false"


def test_page_click_selects_a_radio_and_clears_its_group(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/form-controls-page/")

    second_option = page.query_selector("#second-option")
    assert second_option is not None
    second_option.click()

    assert page.eval("document.querySelector('#first-option').checked") is False
    assert page.eval("document.querySelector('#second-option').checked") is True


def test_page_click_does_not_toggle_a_prevented_checkbox(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/form-controls-page/")

    checkbox = page.query_selector("#prevented-toggle")
    assert checkbox is not None
    checkbox.click()

    assert page.eval("document.querySelector('#prevented-toggle').checked") is True


def test_page_dispatches_document_lifecycle_events_in_order(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/document-lifecycle-page/")

    assert page.body is not None
    assert page.body.get_attribute("state-during-script") == "loading"
    assert page.body.get_attribute("state-during-dom-content-loaded") == "interactive"
    assert page.body.get_attribute("state-during-window-load") == "complete"
    assert page.eval("document.readyState") == "complete"


def test_page_loads_minified_static_module_imports(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        f"""
        const minifiedScript = document.createElement('script');
        minifiedScript.type = 'module';
        minifiedScript.src = '{http_server}/modules/minified-entry.js';
        document.head.appendChild(minifiedScript);
        """
    )

    page.run_event_loop()

    assert page.body.get_attribute("minified-module-ran") == "yes"
    assert page.script_errors == []

def test_page_blocks_cross_origin_modules_without_an_origin_policy(
    phantom_client, http_server: str, cross_origin_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")
    module_url = f"{cross_origin_server}/modules/cross-origin-entry.js"

    page.eval(
        "const crossOriginModule = document.createElement('script');"
        "crossOriginModule.type = 'module';"
        f"crossOriginModule.src = {json.dumps(module_url)};"
        "document.head.appendChild(crossOriginModule);"
    )
    page.run_event_loop()

    assert page.body is not None
    assert page.body.get_attribute("cross-origin-module-ran") is None
    assert len(page.script_errors) == 1
    assert "same-origin" in str(page.script_errors[0])


def test_page_loads_an_allowed_cross_origin_module_and_its_dependencies(
    http_server: str, cross_origin_server: str
) -> None:
    policy = OriginPolicy(allowed_origins=(cross_origin_server,))
    module_url = f"{cross_origin_server}/modules/cross-origin-entry.js"

    with PhantomClient(origin_policy=policy) as client:
        page = client.new_page(f"{http_server}/page/")
        page.eval(
            "const crossOriginModule = document.createElement('script');"
            "crossOriginModule.type = 'module';"
            f"crossOriginModule.src = {json.dumps(module_url)};"
            "document.head.appendChild(crossOriginModule);"
        )
        page.run_event_loop()

    assert page.body is not None
    assert page.body.get_attribute("cross-origin-module-ran") == "yes"
    assert page.script_errors == []

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
    error = page.script_errors[0]
    assert isinstance(error, JSRuntimeError)
    assert f"{http_server}/dynamic-script-error.js" in str(error)
    assert "dynamic script failure" in str(error)
    assert error.js_stack is not None
    assert "dynamic script failure" in error.js_stack
    assert error.source == "throw new Error('dynamic script failure');"


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

def test_page_local_storage_is_shared_by_pages_on_same_origin(phantom_client, http_server: str) -> None:
    first_page = phantom_client.new_page(f"{http_server}/page/")
    first_page.eval("localStorage.setItem('theme', 'dark');")

    second_page = phantom_client.new_page(f"{http_server}/cookies")

    assert second_page.eval("localStorage.getItem('theme');") == "dark"


def test_page_session_storage_is_isolated_between_pages(phantom_client, http_server: str) -> None:
    first_page = phantom_client.new_page(f"{http_server}/page/")
    first_page.eval("sessionStorage.setItem('draft', 'hello')")

    second_page = phantom_client.new_page(f"{http_server}/page/")

    assert first_page.eval("sessionStorage.getItem('draft')") == 'hello'
    assert second_page.eval("sessionStorage.getItem('draft')") is None


def test_page_session_storage_survives_same_page_navigation(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}")
    page.eval("sessionStorage.setItem('draft', 'hello');")

    page.goto(f"{http_server}/cookies")

    assert page.eval("sessionStorage.getItem('draft');") == "hello"


def test_page_session_storage_supports_storage_api(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")
    page.eval("sessionStorage.setItem('first', '1'); sessionStorage.setItem('second', '2');")

    assert page.eval("sessionStorage.length") == 2
    assert page.eval("sessionStorage.key(0)") == "first"
    assert page.eval("sessionStorage.key(1)") == "second"
    assert page.eval("sessionStorage.key(2)") is None

    page.eval("sessionStorage.removeItem('first');")

    assert page.eval("sessionStorage.getItem('first')") is None
    assert page.eval("sessionStorage.length") == 1

    page.eval("sessionStorage.clear();")

    assert page.eval("sessionStorage.length") == 0


def test_page_self_aliases_window(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    assert page.eval("self === window") is True
    assert page.eval("self.document === document") is True

def test_page_button_click_starts_script_execute(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/button")

    button = page.query_selector("#basic-button")
    assert button is not None
    button.click()

    assert page.body is not None
    assert page.body.get_attribute("after-click-script-ran") == "yes"

def test_page_fetch_accepts_headers_instance(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        """
        const requestHeaders = new Headers({"X-Page": "from-headers"});

        fetch("/api/echo", {
            method: "POST",
            headers: requestHeaders,
            body: "payload",
        })
            .then(response => response.json())
            .then(result => {
                document.body.setAttribute(
                    "headers-instance-result",
                    JSON.stringify(result)
                );
            });
        """
    )

    result = json.loads(page.eval("document.body.getAttribute('headers-instance-result')"))

    assert result["header"] == "from-headers"
    assert result["body"] == "payload"


def test_page_image_constructor_creates_a_detached_image_element(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const image = new Image(32, 16);
            image.src = "/images/logo.png";
            JSON.stringify({
                isImageElement: image.tagName === "IMG",
                isDetached: image.parentElement === null,
                width: image.getAttribute("width"),
                height: image.getAttribute("height"),
                src: image.getAttribute("src"),
                canCreateThroughWindow: (new window.Image()).tagName === "IMG",
                canCreateThroughSelf: (new self.Image()).tagName === "IMG",
            });
            """
        )
    )

    assert result == {
        "isImageElement": True,
        "isDetached": True,
        "width": "32",
        "height": "16",
        "src": "/images/logo.png",
        "canCreateThroughWindow": True,
        "canCreateThroughSelf": True,
    }


def test_page_performance_exposes_a_baseline_clock(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    result = json.loads(
        page.eval(
            """
            const firstReading = performance.now();
            const secondReading = performance.now();
            JSON.stringify({
                hasTimeOrigin: Number.isFinite(performance.timeOrigin)
                    && performance.timeOrigin > 0,
                hasNumericReadings: Number.isFinite(firstReading)
                    && Number.isFinite(secondReading),
                hasNonNegativeReadings: firstReading >= 0 && secondReading >= 0,
                isAvailableOnWindow: window.performance === performance,
                isAvailableOnSelf: self.performance === performance,
            });
            """
        )
    )

    assert result == {
        "hasTimeOrigin": True,
        "hasNumericReadings": True,
        "hasNonNegativeReadings": True,
        "isAvailableOnWindow": True,
        "isAvailableOnSelf": True,
    }


def test_page_xml_http_request_sends_text_and_exposes_response_state(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        """
        const xhr = new XMLHttpRequest();
        const states = [];
        xhr.onreadystatechange = function () {
            states.push(xhr.readyState);
        };
        xhr.onload = function () {
            document.body.setAttribute('xhr-result', JSON.stringify({
                state: xhr.readyState,
                status: xhr.status,
                response: JSON.parse(xhr.responseText),
                contentType: xhr.getResponseHeader('content-type'),
                states: states,
                responseURL: xhr.responseURL,
                globalConstructor: window.XMLHttpRequest === XMLHttpRequest,
            }));
        };
        xhr.open('POST', '/api/echo');
        xhr.setRequestHeader('X-Page', 'from-xhr');
        xhr.send('xhr payload');
        """
    )

    assert page.body is not None
    result = json.loads(page.body.get_attribute("xhr-result"))
    assert result == {
        "state": 4,
        "status": 200,
        "response": {
            "body": "xhr payload",
            "header": "from-xhr",
            "content_type": "text/plain;charset=UTF-8",
            "referer": f"{http_server}/page/",
            "cookies": {},
        },
        "contentType": "application/json",
        "states": [1, 2, 3, 4],
        "responseURL": f"{http_server}/api/echo",
        "globalConstructor": True,
    }


def test_page_xml_http_request_respects_the_origin_policy(
    phantom_client, http_server: str, cross_origin_server: str
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        f"""
        const xhr = new XMLHttpRequest();
        const states = [];
        xhr.onreadystatechange = function () {{
            states.push(xhr.readyState);
        }};
        xhr.onerror = function () {{
            document.body.setAttribute('xhr-error-result', JSON.stringify({{
                state: xhr.readyState,
                status: xhr.status,
                responseText: xhr.responseText,
                states: states,
            }}));
        }};
        xhr.open('GET', {json.dumps(f"{cross_origin_server}/api/value")});
        xhr.send();
        """
    )

    assert page.body is not None
    assert json.loads(page.body.get_attribute("xhr-error-result")) == {
        "state": 4,
        "status": 0,
        "responseText": "",
        "states": [1, 4],
    }


def test_page_xml_http_request_abort_removes_a_queued_request(
    phantom_client, http_server: str, abortable_request_count
) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        """
        const xhr = new XMLHttpRequest();
        xhr.onabort = function () {
            document.body.setAttribute('xhr-was-aborted', String(xhr.readyState));
        };
        xhr.open('GET', '/api/abortable');
        xhr.send();
        xhr.abort();
        """
    )

    assert page.body is not None
    assert page.body.get_attribute("xhr-was-aborted") == "4"
    assert abortable_request_count() == 0


def test_page_xml_http_request_load_handler_can_start_fetch(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/page/")

    page.eval(
        """
        const xhr = new XMLHttpRequest();
        xhr.onload = function () {
            fetch('/api/value')
                .then(function (response) { return response.json(); })
                .then(function (result) {
                    document.body.setAttribute('xhr-follow-up-fetch', result.value);
                });
        };
        xhr.open('GET', '/api/value');
        xhr.send();
        """
    )

    assert page.body is not None
    assert page.body.get_attribute("xhr-follow-up-fetch") == "from-api"
