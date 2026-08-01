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

import logging
import json

from typing import Any, ClassVar, FrozenSet, Optional
from urllib.parse import urljoin

from phantom_curl.engine.context import JSContext
from phantom_curl.engine.dom_builder import DOMBuilder
from phantom_curl.element import Element
from phantom_curl.models import Response
from phantom_curl.exceptions import JSRuntimeError
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
        self._reset_runtime()
        self._generation = 0

        self.response: Optional[Response] = None
        self.script_errors: list[Exception] = []

        self.url: Optional[str] = None

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
        self._dom_builder = DOMBuilder(self._context)

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
        request_options = build_request_options(method="GET", url=url)
        response = self._session.request(request_options)

        self.url = response.url

        self._reset_runtime()
        self._dom_builder.parse_html(response.text, url=self.url)
        self._generation += 1

        self.script_errors = []

        for entry in self._dom_builder.get_scripts():
            if entry["code_type"] == "module":
                logger.info("Skipping unsupported module script on %s", self.url)
                continue
            if entry["code_type"] not in self._CLASSIC_SCRIPT_TYPES:
                continue

            self._context.eval(
                f"globalThis.__phantom_current_script = globalThis.__phantom_elements[{json.dumps(entry['node_id'])}];"
            )
            try:
                if entry["script_type"] == "inline":
                    try:
                        self._context.eval(entry["content"])
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
                    except Exception as e:
                        logger.warning(
                            "External script fetch/execution failed on %s (from %s): %s",
                            script_url, url, e,
                        )
                        self.script_errors.append(e)
            finally:
                self._context.eval("globalThis.__phantom_current_script = null;")

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
        return self._context.eval(js_code)

    def eval(self, js_code: str) -> Any:
        """Alias for :meth:`evaluate`, retained for a concise interactive API."""
        return self.evaluate(js_code)
