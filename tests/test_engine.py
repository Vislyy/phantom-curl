import json

import pytest

from phantom_curl.engine.context import JSContext
from phantom_curl.engine.dom_builder import DOMBuilder
from phantom_curl.exceptions import JSRuntimeError


def test_dom_builder_collects_scripts_with_normalized_types() -> None:
    builder = DOMBuilder(JSContext())
    builder.parse_html(
        """
        <script type=" Text/JavaScript ">window.inlineRan = true;</script>
        <script src="/static/app.js" type="application/javascript"></script>
        """
    )

    scripts = builder.get_scripts()

    assert [script["script_type"] for script in scripts] == ["inline", "external"]
    assert [script["code_type"] for script in scripts] == ["text/javascript", "application/javascript"]
    assert builder.get_inline_scripts() == ["window.inlineRan = true;"]
    assert builder.get_external_scripts() == ["/static/app.js"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://example.test",
            {
                "origin": "https://example.test",
                "host": "example.test",
                "hostname": "example.test",
                "port": "",
                "pathname": "/",
                "search": "",
                "hash": "",
            },
        ),
        (
            "https://example.test/path?q=1#top",
            {
                "origin": "https://example.test",
                "host": "example.test",
                "hostname": "example.test",
                "port": "",
                "pathname": "/path",
                "search": "?q=1",
                "hash": "#top",
            },
        ),
        (
            "https://user:pass@[2001:db8::1]:8443/path?query=yes#fragment",
            {
                "origin": "https://[2001:db8::1]:8443",
                "host": "[2001:db8::1]:8443",
                "hostname": "2001:db8::1",
                "port": "8443",
                "pathname": "/path",
                "search": "?query=yes",
                "hash": "#fragment",
            },
        ),
        (
            "about:blank",
            {
                "origin": "null",
                "host": "",
                "hostname": "",
                "port": "",
                "pathname": "blank",
                "search": "",
                "hash": "",
            },
        ),
    ],
)
def test_dom_builder_initializes_browser_style_location(url: str, expected: dict[str, str]) -> None:
    context = JSContext()
    builder = DOMBuilder(context)

    builder.parse_html("<html><body></body></html>", url)

    location = json.loads(
        context.eval(
            "JSON.stringify({"
            "origin: location.origin, host: location.host, hostname: location.hostname, "
            "port: location.port, pathname: location.pathname, search: location.search, hash: location.hash"
            "})"
        )
    )
    assert location == expected


def test_quickjs_context_rejects_esm_export_in_classic_script_mode() -> None:
    context = JSContext()

    with pytest.raises(JSRuntimeError, match="unsupported keyword: export"):
        context.eval("export const token = 1")


def test_quickjs_context_executes_pending_promise_jobs() -> None:
    context = JSContext()
    context.eval("globalThis.promise_result = null; Promise.resolve(42).then(value => promise_result = value);")

    assert context.execute_pending_jobs() == 1
    assert context.eval("promise_result") == 42


def test_dom_builder_exposes_browser_globals_through_window() -> None:
    context = JSContext()
    builder = DOMBuilder(context)

    builder.parse_html("<html><body></body></html>", "https://example.test")

    assert context.eval("window.navigator === navigator") is True
    assert context.eval("window.console === console") is True
    assert context.eval("typeof window.console.log") == "function"

    context.eval("window.console.log('Hello from window.console!')")
