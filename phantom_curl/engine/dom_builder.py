"""
phantom_curl.engine.dom_builder
==================================

Loads the Linkedom bundle (a lightweight, dependency-free DOM
implementation) into a JSContext, and provides a simple interface
for parsing HTML strings into a live, queryable DOM tree.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Optional
from urllib.parse import SplitResult, urlsplit

from phantom_curl.engine.context import JSContext
from phantom_curl.exceptions import JSRuntimeError, DOMBuildError, EngineInitError

_JS_BUNDLE_DIR = Path(__file__).parent / "js_bundle"
_POLYFILLS_PATH = _JS_BUNDLE_DIR / "polyfills.js"
_LINKEDOM_PATH = _JS_BUNDLE_DIR / "linkedom.js"


class DOMBuilder:
    """
    Wraps a JSContext pre-loaded with Linkedom, allowing HTML strings
    to be parsed into a live DOM tree that can be queried and
    manipulated via JavaScript.
    """

    def __init__(self, context: JSContext, navigator_languages: tuple[str, ...] = ("en-US", "en")) -> None:
        """
        Creates a new DOMBuilder, immediately loading the required
        polyfills and the Linkedom bundle into a JSContext

        Raises:
            EngineInitError: If the polyfills or Linkedom bundle fail
                to load into the JS context.
        """
        self._context = context

        with open(_LINKEDOM_PATH, encoding="utf-8") as file:
            linkedom = file.read()

        with open(_POLYFILLS_PATH, encoding="utf-8") as file:
            polyfills = file.read()

        try:
            self._context.eval(polyfills)
            self._configure_navigator(navigator_languages)
            self._context.eval(linkedom)
        except JSRuntimeError as e:
            raise EngineInitError(
                f"Failed to initialize the DOM engine: {e.message}. "
                f"This usually means the Linkedom bundle or its required "
                f"polyfills (polyfills.js) are missing, corrupted, or "
                f"incompatible with the current QuickJS runtime."
            ) from e

        self.origin = ""

    def _configure_navigator(self, languages: tuple[str, ...]) -> None:
        """Apply configured language preferences to the JavaScript navigator."""
        if not languages:
            raise ValueError("navigator_languages must contain at least one language code")

        self._context.eval(
            "globalThis.navigator.language = "
            f"{json.dumps(languages[0])};"
            "globalThis.navigator.languages = "
            f"{json.dumps(languages)};"
        )

    def _format_host_for_location(self, parsed_url: SplitResult) -> str:
        """Return browser-style ``location.host`` without credentials.

        The result contains the hostname and, when explicitly present, the
        port. IPv6 literals are wrapped in square brackets. URLs without an
        authority component, such as ``about:blank``, return an empty string.
        """
        hostname = parsed_url.hostname
        if hostname is None:
            return ""

        try:
            ip_address = ipaddress.ip_address(hostname)
        except ValueError:
            final_host = hostname
        else:
            final_host = f"[{ip_address}]" if ip_address.version == 6 else str(ip_address)

        port = parsed_url.port
        return f"{final_host}:{port}" if port is not None else final_host

    def parse_html(self, html: str, url: Optional[str] = None, referrer: Optional[str] = None) -> None:
        """
        Parses an HTML string into a DOM document, stored internally as
        a global variable inside the JS context for use by subsequent
        eval() calls.

        Note: Calling this method again will replace the previously
        parsed document. Each DOMBuilder instance holds exactly one
        active document at a time, similar to a single browser tab.

        Args:
            html: The raw HTML source to parse.
            url: The page URL (optional) used to initialize window.location.
            referrer: The referrer URL (optional) used to initialize
                window.document.referrer.

        Raises:
            DOMBuildError: If the HTML could not be parsed.
        """
        parsed_url = urlsplit(url or "about:blank")

        safe_html_literal = json.dumps(html)
        safe_url_literal = json.dumps(parsed_url.geturl())

        host = self._format_host_for_location(parsed_url)
        hostname = parsed_url.hostname or ""
        port = str(parsed_url.port) if parsed_url.port is not None else ""
        pathname = parsed_url.path if parsed_url.scheme == "about" else parsed_url.path or "/"
        origin = (
            f"{parsed_url.scheme}://{host}"
            if parsed_url.scheme in {"http", "https"} and host
            else "null"
        )

        self.origin = origin

        code = f"""
        const parsed = parseHTML({safe_html_literal});
        globalThis.window = parsed.window;
        globalThis.document = parsed.document;
        globalThis.self = globalThis.window;
        globalThis.__phantom_document = parsed.document;

        globalThis.window.URL = globalThis.URL;
        globalThis.window.URLSearchParams = globalThis.URLSearchParams;
        globalThis.window.Headers = globalThis.Headers;

        globalThis.document.referrer = {json.dumps(referrer or "")};

        const loc = {{
            origin: {json.dumps(origin)},
            href: {safe_url_literal},
            protocol: {json.dumps(parsed_url.scheme + ":")},
            host: {json.dumps(host)},
            hostname: {json.dumps(hostname)},
            port: {json.dumps(port)},
            pathname: {json.dumps(pathname)},
            search: {json.dumps("?" + parsed_url.query if parsed_url.query else "")},
            hash: {json.dumps("#" + parsed_url.fragment if parsed_url.fragment else "")}
        }};
        loc.toString = function() {{
            return this.href;
        }};

        globalThis.window.location = loc;
        globalThis.location = loc;

        // Install document.write/writeln polyfill now that globalThis.document
        // is bound (polyfills.js is loaded before parseHTML runs, so the
        // document did not exist yet at polyfill load time).
        if (typeof globalThis.__phantom_ensure_write === 'function') {{
            globalThis.__phantom_ensure_write();
        }}
        """

        try:
            self._context.eval(code)
        except JSRuntimeError as e:
            raise DOMBuildError(message=f"Failed to parse HTML: {e.message}", html_snippet=html[:200]) from e

    def has_document(self) -> bool:
        """
        Checks whether a document is currently loaded into this context.

        Returns:
            True if parse_html() was successfully called and a document
            is available for querying.
        """
        result = self._context.eval("typeof __phantom_document !== 'undefined'")
        return bool(result)

    def serialize(self) -> str:
        """
        Returns the full HTML of the currently loaded document.

        Returns:
            The serialized HTML of the document's root element.

        Raises:
            DOMBuildError: If no document is currently loaded, or if
                serialization fails.
        """
        if not self.has_document():
            raise DOMBuildError(message="No document is currently loaded. Call parse_html() first.", html_snippet="")

        try:
            result = self._context.eval("__phantom_document.documentElement.outerHTML")
            return str(result)
        except JSRuntimeError as e:
            raise DOMBuildError(message=f"Serialization failed: {e.message}", html_snippet="") from e

    def get_scripts(self) -> list[dict[str, str]]:
        """
        Returns all non-empty <script> tags in the currently loaded
        document, in exact document order, categorized as either
        'inline' or 'external', and paired with a handle ID for the
        underlying <script> node so callers (e.g. Page.goto) can point
        document.write()-style polyfills at the script's position.

        Returns:
            A list of dictionaries, e.g.:
            [
                {"script_type": "external", "code_type": "", "src": "/static/jquery.js", "node_id": "script_1"},
                {"script_type": "inline", "code_type": "", "content": "console.log(1);", "node_id": "script_2"}
            ]

            Script tags that have neither a usable src nor non-empty
            textContent are skipped (mirrors the previous behavior of
            filtering via .filter(Boolean)).

        Raises:
            DOMBuildError: If the underlying JS evaluation fails.
        """
        js = """
        (function () {
            if (!globalThis.__phantom_scripts_ws) globalThis.__phantom_scripts_ws = new WeakSet()
            if (!globalThis.__phantom_scripts_wm) globalThis.__phantom_scripts_wm = new WeakMap()
            if (!globalThis.__phantom_elements) globalThis.__phantom_elements = {};
            if (!globalThis.__phantom_id_counter) globalThis.__phantom_id_counter = 0;

            const out = [];
            const nodes = Array.from(__phantom_document.querySelectorAll('script'));
            for (const s of nodes) {
                let entry = null;
                const codeType = (s.getAttribute('type') || '').trim().toLowerCase();
                if (s.hasAttribute('src') && s.getAttribute('src').trim()) {
                    entry = { script_type: 'external', code_type: codeType, src: s.getAttribute('src').trim()};
                } else if (s.textContent.trim()) {
                    entry = { script_type: 'inline', code_type: codeType, content: s.textContent };
                }
                if (!entry) continue;

                let id;

                if (globalThis.__phantom_scripts_wm.has(s)) {
                    id = globalThis.__phantom_scripts_wm.get(s);
                } else {
                    id = 'script_' + ++globalThis.__phantom_id_counter;
                    globalThis.__phantom_scripts_wm.set(s, id);
                }

                globalThis.__phantom_elements[id] = s;
                entry.node_id = id;
                out.push(entry);
            }
            return JSON.stringify(out);
        })()
        """
        try:
            return json.loads(self._context.eval(js))
        except JSRuntimeError as e:
            raise DOMBuildError(f"Failed to collect document scripts: {e.message}") from e

    def get_inline_scripts(self) -> list[str]:
        """
        Returns the text content of every inline <script> tag in the
        currently loaded document (scripts without a `src` attribute),
        in document order.
        """
        return [s["content"] for s in self.get_scripts() if s.get("script_type") == "inline"]

    def get_external_scripts(self) -> list[str]:
        """
        Returns the `src` URL attributes of every external <script> tag
        in the currently loaded document (scripts with a `src` attribute),
        in document order.
        """
        return [s["src"] for s in self.get_scripts() if s.get("script_type") == "external"]

    def query_selector(self, selector: str) -> Optional[str]:
        """
        Executes document.querySelector(selector) inside JS, registers the node
        in `globalThis.__phantom_elements`, and returns its handle ID (or None).
        """
        js = f"""
        (function() {{
            if (!globalThis.__phantom_elements) globalThis.__phantom_elements = {{}};
            if (!globalThis.__phantom_id_counter) globalThis.__phantom_id_counter = 0;

            const elem = __phantom_document.querySelector({json.dumps(selector)});
            if (!elem) return null;

            const id = 'elem_' + (++globalThis.__phantom_id_counter);
            globalThis.__phantom_elements[id] = elem;
            return id;
        }})()
        """
        try:
            result = self._context.eval(js)
            return str(result) if result is not None else None
        except JSRuntimeError as e:
            raise DOMBuildError(f"query_selector failed for {selector!r}: {e.message}") from e

    def query_selector_all(self, selector: str) -> list[str]:
        """
        Executes document.querySelectorAll(selector) inside JS, registers each node
        in `globalThis.__phantom_elements`, and returns a list of handle IDs.
        """
        js = f"""
        (function() {{
            if (!globalThis.__phantom_elements) globalThis.__phantom_elements = {{}};
            if (!globalThis.__phantom_id_counter) globalThis.__phantom_id_counter = 0;

            const elems = Array.from(__phantom_document.querySelectorAll({json.dumps(selector)}));
            return JSON.stringify(elems.map(elem => {{
                const id = 'elem_' + (++globalThis.__phantom_id_counter);
                globalThis.__phantom_elements[id] = elem;
                return id;
            }}));
        }})()
        """
        try:
            return json.loads(self._context.eval(js))
        except JSRuntimeError as e:
            raise DOMBuildError(f"query_selector_all failed for {selector!r}: {e.message}") from e
