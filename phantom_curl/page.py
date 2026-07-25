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

from typing import Optional

from phantom_curl.engine.context import JSContext
from phantom_curl.engine.dom_builder import DOMBuilder
from phantom_curl.models import Response
from phantom_curl.exceptions import JSRuntimeError
from phantom_curl.network.session import NetworkSession
from phantom_curl.utils.request_options_builder import build_request_options

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
        self._context = JSContext()
        self._dom_builder = DOMBuilder(self._context)

        self.response: Optional[Response] = None
        self.script_errors: list[Exception] = []

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
            External <script src="..."> tags are not yet fetched or
            executed — that is a planned follow-up step.
        """
        request_options = build_request_options(method="GET", url=url)
        response = self._session.request(request_options)
        self._dom_builder.parse_html(response.text)

        self.script_errors = []
        for script in self._dom_builder.get_inline_scripts():
            try:
                self._context.eval(script)
            except JSRuntimeError as e:
                logger.warning("Inline script execution failed on %s: %s", url, e)
                self.script_errors.append(e)

        self.response = response
        return response