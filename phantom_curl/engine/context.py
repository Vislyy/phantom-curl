"""
phantom_curl.engine.context
==============================

A thin wrapper around quickjs.Context providing safe JavaScript
execution with timeout/memory limits and PhantomCurl's own error
handling.
"""

from __future__ import annotations

from typing import Any

import quickjs

from phantom_curl.exceptions import JSRuntimeError


class JSContext:
    """
    Wraps a QuickJS execution context, adding safety limits and
    translating quickjs's own exceptions into PhantomCurl's
    JSRuntimeError.
    """

    def __init__(
        self,
        time_limit: float = 5.0,
        memory_limit: int = 64 * 1024 * 1024,  # 64 MB
    ) -> None:
        """
        Creates a new JS execution context.

        Args:
            time_limit: Maximum time (in seconds) a single eval() call
                is allowed to run before being aborted. Protects
                against infinite loops in untrusted page scripts.
            memory_limit: Maximum memory (in bytes) the JS runtime is
                allowed to allocate. Protects against memory
                exhaustion attacks.
        """
        self._context = quickjs.Context()
        self._context.set_time_limit(time_limit)
        self._context.set_memory_limit(memory_limit)

    def eval(self, code: str) -> Any:
        """
        Executes a JavaScript expression/statement and returns its
        result, converted to the corresponding Python type.

        Args:
            code: JavaScript source code to execute.

        Returns:
            The result of the evaluation, converted to a Python value
            (int, float, str, bool, list, dict, or None).

        Raises:
            JSRuntimeError: If the JS code raises an exception or
                contains a syntax error.
        """
        try:
            result = self._context.eval(code)
        except quickjs.JSException as e:
            full_message = str(e)
            first_line = full_message.split("\n")[0]
            raise JSRuntimeError(
                first_line,
                js_stack=full_message,
                source=code,
            ) from e
        
        return result