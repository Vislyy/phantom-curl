"""
phantom_curl.page
====================

Defines the Page class — the central orchestrator of the Environment
and Bridge layers.

A Page represents a single "virtual browser tab": one live JS
execution context paired with the DOM document currently loaded into
it. Unlike PhantomClient.get()/post() (which perform a raw HTTP
request and return a passive Response), Page.goto() performs a full
navigation: it fetches the target URL and parses the resulting HTML
into a live DOM tree inside the JS context — mirroring what a real
browser does when loading a page.

A single Page instance can be reused across multiple navigations
(similar to a browser tab navigating to different URLs over time);
calling goto() again replaces the previously loaded document.
"""

from __future__ import annotations

import json
import logging
import time

from typing import Any, ClassVar, FrozenSet, Optional
from urllib.parse import urljoin

from phantom_curl.bridge.interceptor import FetchInterceptor
from phantom_curl.bridge.event_loop import TimerBridge
from phantom_curl.bridge.module_loader import ModuleLoader
from phantom_curl.engine.context import JSContext
from phantom_curl.engine.dom_builder import DOMBuilder
from phantom_curl.element import Element
from phantom_curl.models import Response
from phantom_curl.exceptions import InterceptorError, JSRuntimeError
from phantom_curl.network.session import NetworkSession
from phantom_curl.utils.request_builder import build_request_options

logger = logging.getLogger(__name__)

class Page:
    """
    A single virtual browser tab combining a JS execution context and
    a live DOM document.

    Page ties together the Environment Layer (JSContext + DOMBuilder)
    with the Network Layer, using a shared NetworkSession so that
    cookies set during regular HTTP requests (e.g. via PhantomClient)
    are visible to requests made from within this page, and vice versa.
    """

    _CLASSIC_SCRIPT_TYPES: ClassVar[FrozenSet[str]] = frozenset({
        "",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
        "application/x-javascript",
    })

    def __init__(self, session: NetworkSession):
        """
        Creates a new Page backed by a fresh JS execution context.

        Args:
            network_session: The NetworkSession used to perform real
                HTTP requests for this page. This session is shared
                with (owned by) the caller (typically PhantomClient),
                so that cookies set outside the page are visible to
                requests made from within it, and vice versa.

        Note:
            A new, isolated JSContext is created for every Page
            instance rather than shared across pages. Each JS context
            holds page-specific global state (the parsed document,
            registered bridge callables, the pending microtask queue),
            which must not leak between unrelated pages/tabs.
        """
        self._session = session
        self._stealth_config = session.stealth_config
        self._fetch_interceptor: Optional[FetchInterceptor] = None
        self._module_loader: Optional[ModuleLoader] = None
        self._timer_bridge: Optional[TimerBridge] = None
        self._reset_runtime()

        self._generation = 0
        self._executed_scripts_ids: set[str] = set()

        self._session_storage: dict[str, dict[str, str]] = {}

        self.response: Optional[Response] = None
        self.script_errors: list[Exception] = []

        self.url: Optional[str] = None
        self.origin: str = ""
        self.referrer: str = ""

    @property
    def html(self) -> str:
        return self._dom_builder.serialize()

    @property
    def title(self) -> str:
        title = self.query_selector("title")
        return title.text if title else ""

    @property
    def text(self) -> str:
        body = self.query_selector("body")
        return body.text if body else ""

    @property
    def body(self) -> Optional[Element]:
        return self.query_selector("body")

    @property
    def head(self) -> Optional[Element]:
        return self.query_selector("head")

    @property
    def status_code(self) -> Optional[int]:
        return self.response.status_code if self.response is not None else None

    @property
    def ok(self) -> Optional[bool]:
        return self.response.ok if self.response is not None else None

    @property
    def is_loaded(self) -> bool:
        """Whether this page has completed at least one navigation."""
        return self.response is not None
        
    def _reset_runtime(self) -> None:
        """Create a fresh JS environment for each navigation."""
        self._context = JSContext()
        self._fetch_interceptor = None
        self._module_loader = None
        self._timer_bridge = None
        self._dom_builder = DOMBuilder(
            self._context,
            navigator_languages=self._stealth_config.languages,
        )
        self._executed_scripts_ids = set()

    def _install_fetch_bridge(self) -> None:
        """Expose the supported asynchronous fetch subset to page scripts."""
        if self.url is None:
            return

        self._fetch_interceptor = FetchInterceptor(self._session, self.url)
        self._context.eval(
            """
            globalThis.__phantom_pending_fetches = [];
            globalThis.__phantom_fetch_resolvers = Object.create(null);
            globalThis.__phantom_fetch_id = 0;

            globalThis.__phantom_take_fetches = function () {
                const pending = globalThis.__phantom_pending_fetches;
                globalThis.__phantom_pending_fetches = [];
                return JSON.stringify(pending);
            };

            globalThis.__phantom_complete_fetch = function (id, resultJson) {
                const resolver = globalThis.__phantom_fetch_resolvers[id];
                delete globalThis.__phantom_fetch_resolvers[id];
                if (!resolver) {
                    return;
                }

                const result = JSON.parse(resultJson);
                if (result.error) {
                    resolver.reject(new TypeError(result.error));
                    return;
                }

                const body = result.text;
                resolver.resolve({
                    ok: result.ok,
                    status: result.status,
                    url: result.url,
                    text: function () { return Promise.resolve(body); },
                    json: function () {
                        try {
                            return Promise.resolve(JSON.parse(body));
                        } catch (error) {
                            return Promise.reject(error);
                        }
                    }
                });
            };

            globalThis.fetch = function fetch(input, init) {
                return new Promise(function (resolve, reject) {
                    if (typeof input !== 'string') {
                        reject(new TypeError('PhantomCurl fetch requires a string URL'));
                        return;
                    }

                    const options = init === undefined ? {} : init;
                    if (options === null || typeof options !== 'object') {
                        reject(new TypeError('PhantomCurl fetch options must be an object'));
                        return;
                    }

                    const id = ++globalThis.__phantom_fetch_id;
                    const method = options.method === undefined ? 'GET' : String(options.method);
                    const headers = options.headers === undefined ? {} : options.headers;
                    const body = options.body === undefined ? null : options.body;
                    globalThis.__phantom_fetch_resolvers[id] = {resolve: resolve, reject: reject};
                    globalThis.__phantom_pending_fetches.push({
                        id: id,
                        url: input,
                        method: method,
                        headers: headers,
                        body: body
                    });
                });
            };
            """
        )

    def _install_cookie_bridge(self) -> None:
        """Expose the page-visible portion of the session cookie jar to JavaScript."""
        if self.url is None:
            return

        cookie_string = self._session.cookies.document_cookie_string(self.url)
        self._context.eval(
            """
            const phantomCookieStore = {value: ""};
            globalThis.__phantom_pending_cookie_writes = [];

            globalThis.__phantom_take_cookie_writes = function () {
                const pending = globalThis.__phantom_pending_cookie_writes;
                globalThis.__phantom_pending_cookie_writes = [];
                return JSON.stringify(pending);
            };

            globalThis.__phantom_replace_document_cookie = function (value) {
                phantomCookieStore.value = value;
            };

            Object.defineProperty(globalThis.document, 'cookie', {
                configurable: true,
                get: function () {
                    return phantomCookieStore.value;
                },
                set: function (cookie) {
                    if (typeof cookie !== 'string') {
                        return;
                    }

                    const pair = cookie.split(';', 1)[0];
                    const separator = pair.indexOf('=');
                    if (separator <= 0) {
                        return;
                    }

                    const name = pair.slice(0, separator).trim();
                    const value = pair.slice(separator + 1);
                    const values = Object.create(null);
                    if (phantomCookieStore.value) {
                        for (const item of phantomCookieStore.value.split('; ')) {
                            const itemSeparator = item.indexOf('=');
                            values[item.slice(0, itemSeparator)] = item.slice(itemSeparator + 1);
                        }
                    }
                    values[name] = value;
                    phantomCookieStore.value = Object.keys(values)
                        .map(key => key + '=' + values[key])
                        .join('; ');
                    globalThis.__phantom_pending_cookie_writes.push(cookie);
                }
            });
            """
        )
        self._context.eval(f"globalThis.__phantom_replace_document_cookie({json.dumps(cookie_string)});")

    def _install_local_storage_bridge(self) -> None:
        """Install the page localStorage facade from the session's origin state."""
        local_storage = self._session.local_storage_for(self.origin)
        local_storage_entries = [
            [name, value]
            for name, value in local_storage.items()
        ]

        self._context.eval(
            f"globalThis.__phantom_install_local_storage({json.dumps(local_storage_entries)});"
        )

    def _install_session_storage_bridge(self) -> None:
        """Install the page sessionStorage facade from the..."""
        session_storage = self._session_storage.setdefault(self.origin, {})
        session_storage_entries = [
            [name, value]
            for name, value in session_storage.items()
        ]

        self._context.eval(
            f"globalThis.__phantom_install_session_storage({json.dumps(session_storage_entries)});"
        )

    def _install_timer_bridge(self) -> None:
        """Install the page-local timer APIs before page scripts run."""
        self._timer_bridge = TimerBridge(self._context)

    def _flush_cookie_writes(self) -> None:
        """Persist queued document.cookie writes and refresh the JS-visible value."""
        if self.url is None:
            return

        writes = json.loads(self._context.eval("globalThis.__phantom_take_cookie_writes()"))
        for cookie_string in writes:
            if not isinstance(cookie_string, str):
                raise InterceptorError("cookie bridge received invalid cookie data")
            self._session.cookies.set_document_cookie(cookie_string, self.url)

        cookie_string = self._session.cookies.document_cookie_string(self.url)
        self._context.eval(f"globalThis.__phantom_replace_document_cookie({json.dumps(cookie_string)});")

    def _flush_fetch_requests(self) -> None:
        """Send queued fetch requests and settle their JavaScript Promises."""
        if self._fetch_interceptor is None:
            return

        while True:
            self._context.execute_pending_jobs()
            self._flush_cookie_writes()
            pending = json.loads(self._context.eval("globalThis.__phantom_take_fetches()"))
            if not pending:
                return

            for request in pending:
                if not isinstance(request, dict) or not isinstance(request.get("id"), int):
                    raise InterceptorError("fetch bridge received invalid queued request data")

                result = self._fetch_interceptor.handle(request)
                self._flush_cookie_writes()
                self._context.eval(
                    "globalThis.__phantom_complete_fetch("
                    f"{request['id']}, {json.dumps(json.dumps(result))}"
                    ");"
                )

    def _flush_local_storage_operations(self) -> None:
        """Persist localStorage mutations queued by the current JS context."""
        raw_operations = self._context.eval("__phantom_take_local_storage_operations()")
        operations = json.loads(raw_operations)

        for operation in operations:
            if not isinstance(operation, dict):
                raise InterceptorError("localStorage bridge received invalid operation data")

            operation_type = operation.get("type")
            key = operation.get("key")

            if operation_type == "set" and isinstance(key, str):
                value = operation.get("value")
                if not isinstance(value, str):
                    raise InterceptorError("localStorage set operation requires a string value")
                self._session.set_local_storage_item(self.origin, key, value)
            elif operation_type == "remove" and isinstance(key, str):
                self._session.remove_local_storage_item(self.origin, key)
            elif operation_type == "clear":
                self._session.clear_local_storage(self.origin)
            else:
                raise InterceptorError("localStorage bridge received invalid operation data")

    def _flush_session_storage_operations(self) -> None:
        """Persist sessionStorage mutations queued by the current JS context"""
        raw_operations = self._context.eval("__phantom_take_session_storage_operations()")
        operations = json.loads(raw_operations)

        session_storage = self._session_storage.setdefault(self.origin, {})

        for operation in operations:
            if not isinstance(operation, dict):
                raise InterceptorError("sessionStorage bridge received invalid operation data")

            operation_type = operation.get("type")
            key = operation.get("key")

            if operation_type == "set" and isinstance(key, str):
                value = operation.get("value")
                if not isinstance(value, str):
                    raise InterceptorError("sessionStorage set operation requires a string value")
                session_storage[key] = value
            elif operation_type == "remove" and isinstance(key, str):
                session_storage.pop(key, None)
            elif operation_type == "clear":
                session_storage.clear()
            else:
                raise InterceptorError("sessionStorage bridge received invalid operation data")

    def _drain_runtime(self, timeout: float = 0.0) -> None:
        """Run microtasks, queued fetches and timers due within ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            self._flush_local_storage_operations()
            self._flush_session_storage_operations()
            self._flush_fetch_requests()
            self._flush_local_storage_operations()
            self._flush_session_storage_operations()
            if self._timer_bridge is None or not self._timer_bridge.run_due_timers():
                if self._timer_bridge is None:
                    return
                delay = self._timer_bridge.milliseconds_until_next_timer()
                if delay is None or time.monotonic() + delay / 1000 > deadline:
                    return
                time.sleep(delay / 1000)

    def _install_module_loader(self) -> None:
        """Create the page-local module loader before page scripts execute."""
        if self.url is not None:
            self._module_loader = ModuleLoader(self._context, self._session, self.url)

    def _execute_pending_scripts(self) -> None:
        while True:
            new_scripts = [
                script
                for script in self._dom_builder.get_scripts()
                if script["node_id"] not in self._executed_scripts_ids
            ]

            if not new_scripts:
                break

            for script in new_scripts:
                self._executed_scripts_ids.add(script["node_id"])
                if script["code_type"] != "module" and script["code_type"] not in self._CLASSIC_SCRIPT_TYPES:
                    continue

                self._execute_script(script, self.url)

    def _execute_module_script(self, entry: dict[str, str]) -> None:
        """Execute one inline or external module script through the page loader."""
        if self._module_loader is None:
            raise InterceptorError("Module loader is unavailable before a page navigation")

        if entry["script_type"] == "inline":
            self._module_loader.execute_inline(entry["content"], entry["node_id"])
        else:
            self._module_loader.execute_external(entry["src"])
        self._flush_cookie_writes()
        self._drain_runtime()

    def _execute_script(self, entry, url):
        self._context.eval(
            f"globalThis.__phantom_current_script = globalThis.__phantom_elements[{json.dumps(entry['node_id'])}];"
        )
        try:
            if entry["code_type"] == "module":
                try:
                    self._execute_module_script(entry)
                except Exception as e:
                    logger.warning("Module script execution failed on %s: %s", url, e)
                    self.script_errors.append(e)

            elif entry["script_type"] == "inline":
                try:
                    self._context.eval(entry["content"])
                    self._drain_runtime()
                except JSRuntimeError as e:
                    logger.warning("Inline script execution failed on %s: %s", url, e)
                    self.script_errors.append(e)

            elif entry["script_type"] == "external":
                script_url = urljoin(self.url or url, entry["src"])
                try:
                    script_options = build_request_options(
                        method="GET",
                        url=script_url,
                        headers={"Referer": self.url or url},
                    )
                    script_response = self._session.request(script_options)
                    self._context.eval(script_response.text)
                    self._drain_runtime()
                except Exception as e:
                    logger.warning(
                        "External script fetch/execution failed on %s (from %s): %s",
                        script_url, url, e,
                    )
                    self.script_errors.append(e)
        finally:
            self._context.eval("globalThis.__phantom_current_script = null;")

    def goto(self, url: str) -> Response:
        """
        Navigates this page to the given URL.

        Performs a real HTTP GET request for `url`, then parses the
        resulting HTML body into a live DOM document inside this
        page's JS context, replacing any document previously loaded
        via a prior goto() call.

        Args:
            url: The URL to navigate to.

        Returns:
            The raw Response object for the navigation request, in
            case the caller needs access to the status code, headers,
            or cookies set during navigation.

        Raises:
            NetworkError: If the underlying HTTP request fails (see
                NetworkSession.request).
            DOMBuildError: If the response body could not be parsed
                as HTML.

        Note:
            Inline <script> tags found in the loaded document are
            executed in document order after the DOM is built. If an
            inline script raises an error during execution, the error is
            logged and recorded in `self.script_errors`, but execution
            continues with the remaining scripts (mirroring how a real
            browser does not halt page load on a single script error).
            External <script src="..."> tags are fetched and executed.
        """
        previous_url = self.url

        request_options = build_request_options(method="GET", url=url)
        response = self._session.request(request_options)

        self.url = response.url
        self.referrer = previous_url or ""

        self._reset_runtime()
        self._dom_builder.parse_html(response.text, url=self.url, referrer=self.referrer)
        self.origin = self._dom_builder.origin

        self._install_cookie_bridge()
        self._install_local_storage_bridge()
        self._install_fetch_bridge()
        self._install_timer_bridge()
        self._install_module_loader()
        self._install_session_storage_bridge()

        self._generation += 1

        self.script_errors = []

        self._execute_pending_scripts()

        self.response = response
        return response

    def content(self) -> str:
        return self.html

    def query_selector(self, selector: str) -> Optional[Element]:
        """
        Finds the first element matching `selector` in the loaded document.

        Args:
            selector: CSS selector string (e.g. 'h1', '#title', '.btn').

        Returns:
            An Element proxy object, or None if no match is found.
        """
        handle_id = self._dom_builder.query_selector(selector)
        if handle_id is None:
            return None
        return Element(
            page=self,
            context=self._context,
            handle_id=handle_id,
            generation=self._generation,
            selector=selector,
            created_url=self.url,
        )

    def query_selector_all(self, selector: str) -> list[Element]:
        """
        Finds all elements matching `selector` in the loaded document.

        Args:
            selector: CSS selector string (e.g. 'a', 'p.intro').

        Returns:
            A list of Element proxy objects (empty if no matches found).
        """
        handle_ids = self._dom_builder.query_selector_all(selector)
        return [
            Element(
                page=self,
                context=self._context,
                handle_id=handle_id,
                generation=self._generation,
                selector=selector,
                created_url=self.url,
            )
            for handle_id in handle_ids
        ]

    def evaluate(self, js_code: str) -> Any:
        """Evaluate JavaScript in the current page context."""
        result = self._context.eval(js_code)
        self._drain_runtime()
        return result

    def run_event_loop(self, timeout: float = 0.0) -> None:
        """Run timers and pending browser tasks for at most ``timeout`` seconds."""
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._drain_runtime(timeout)
        self._execute_pending_scripts()

    def eval(self, js_code: str) -> Any:
        """Alias for :meth:`evaluate`, retained for a concise interactive API."""
        return self.evaluate(js_code)
