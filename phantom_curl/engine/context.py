"""
phantom_curl.engine.context
==============================

A thin wrapper around quickjs.Context providing safe JavaScript
execution with timeout/memory limits and PhantomCurl's own error
handling.
"""

from __future__ import annotations

from typing import Any, Callable

import quickjs

from phantom_curl.exceptions import JSRuntimeError, EngineInitError

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
    
    def add_callable(self, func_name: str, function: Callable[..., Any]) -> None:
        """
        Registers a Python callable into the QuickJS environment's global
        scope under the given name, making it callable from JS code as
        `func_name(...)`.

        Args:
            func_name: The name the function will be exposed under in the
                JS global scope. Must be a valid identifier (ASCII letters,
                digits, underscore; cannot start with a digit).
            function: The Python callable to expose. Its return value must
                be a type that quickjs can convert to JS
                (int, float, str, bool, list, dict, or None).

        Raises:
            TypeError: If `function` is not callable.
            ValueError: If `func_name` is empty, whitespace, or not a
                valid identifier.
            EngineInitError: If the underlying QuickJS context fails to
                register the callable.
        """
        if not callable(function):
            raise TypeError("Provided object is not callable.")

        if not func_name or not func_name.strip():
            raise ValueError("The 'func_name' argument cannot be empty or whitespace.")

        if not func_name.isidentifier():
            raise ValueError(f"{func_name!r} is not a valid JavaScript identifier.")

        try:
            self._context.add_callable(func_name, function)
        except Exception as e:
            raise EngineInitError(
                f"Failed to register callable {func_name!r} in the JS context: {e}"
            ) from e
        
    