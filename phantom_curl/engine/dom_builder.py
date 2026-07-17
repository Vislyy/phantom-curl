"""
phantom_curl.engine.dom_builder
==================================

Loads the Linkedom bundle (a lightweight, dependency-free DOM
implementation) into a JSContext, and provides a simple interface
for parsing HTML strings into a live, queryable DOM tree.
"""

from __future__ import annotations

import json

from pathlib import Path

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

    def __init__(self) -> None:
        """
        Creates a new DOMBuilder, immediately loading the required
        polyfills and the Linkedom bundle into a fresh JSContext.

        Raises:
            EngineInitError: If the polyfills or Linkedom bundle fail
                to load into the JS context.
        """
        self._context = JSContext()

        with open(_LINKEDOM_PATH, encoding="utf-8") as file:
            linkedom = file.read()

        with open(_POLYFILLS_PATH, encoding="utf-8") as file:
            polyfills = file.read()

        try:
            self._context.eval(polyfills)
            self._context.eval(linkedom)
        except JSRuntimeError as e:
            raise EngineInitError(
                f"Failed to initialize the DOM engine: {e.message}. "
                f"This usually means the Linkedom bundle or its required "
                f"polyfills (polyfills.js) are missing, corrupted, or "
                f"incompatible with the current QuickJS runtime."
            ) from e

    def parse_html(self, html: str) -> None:
        """
        Parses an HTML string into a DOM document, stored internally as
        a global variable inside the JS context for use by subsequent
        eval() calls.

        Note: Calling this method again will replace the previously
        parsed document. Each DOMBuilder instance holds exactly one
        active document at a time, similar to a single browser tab.

        Args:
            html: The raw HTML source to parse.

        Raises:
            DOMBuildError: If the HTML could not be parsed.
        """
        safe_html_literal = json.dumps(html)
        code = f"globalThis.__phantom_document = parseHTML({safe_html_literal}).document"

        try:
            self._context.eval(code)
        except JSRuntimeError as e:
            raise DOMBuildError(
                message=f"Failed to parse HTML: {e.message}",
                html_snippet=html[:200]
            ) from e
    
    def has_document(self) -> bool:
        """
        Checks whether a document is currently loaded into this context.

        Returns:
            True if parse_html() was successfully called and a document
            is available for querying.
        """
        result = self._context.eval("typeof __phantom_document !== 'undefined'")
        return bool(result)
    
    def get_outer(self) -> str:
        """
        Returns the full HTML of the currently loaded document.

        Returns:
            The serialized HTML of the document's root element.

        Raises:
            DOMBuildError: If no document is currently loaded, or if
                serialization fails.
        """
        if not self.has_document():
            raise DOMBuildError(
                message="No document is currently loaded. Call parse_html() first.",
                html_snippet=""
            )
        
        try:
            result = self._context.eval("__phantom_document.documentElement.outerHTML")
            return str(result)
        except JSRuntimeError as e:
            raise DOMBuildError(message=f"Serialization failed: {e.message}", html_snippet="") from e