"""
phantom_curl.element
====================

Defines the Element class — a proxy representation of a live DOM node
inside the Linkedom / JS execution context.
"""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Callable, Optional, TYPE_CHECKING, TypeVar

from phantom_curl.exceptions import StaleElementError

if TYPE_CHECKING:
    from phantom_curl.engine.context import JSContext
    from phantom_curl.page import Page


ElementMethod = TypeVar("ElementMethod", bound=Callable[..., Any])


def _ensure_valid(method: ElementMethod) -> ElementMethod:
    """
    Decorator for automatic element validation for freshness
    """
    @wraps(method)
    def wrapper(self: "Element", *args: Any, **kwargs: Any) -> Any:
        if not self._is_valid:
            raise StaleElementError(
                f"Element '{self.selector}' is no longer attached to the current DOM.",
                selector=self.selector,
                created_url=self.created_url,
                current_url=self._page.url,
                created_generation=self._generation,
                current_generation=self._page._generation,
            )
        return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class Element:
    """
    A proxy object representing a single DOM element node inside a Page's
    live JavaScript context.

    Element allows reading properties (`text`, `inner_html`, `outer_html`),
    retrieving attributes (`get_attribute`), and triggering interactive
    actions like `click()` or `type()`.
    """

    def __init__(
        self,
        page: "Page",
        context: "JSContext",
        handle_id: str,
        generation: int,
        selector: str,
        created_url: Optional[str],
    ) -> None:
        """
        Creates an Element proxy referencing a DOM node stored in the JS
        global node registry under `handle_id`.

        Args:
            context: The JSContext owning the loaded document.
            handle_id: The unique string handle identifying the node in
                `globalThis.__phantom_elements[handle_id]`.
        """
        self._page = page
        self._context = context
        self._handle_id = handle_id
        self._generation = generation

        self.selector = selector
        self.created_url = created_url

    @property
    @_ensure_valid
    def text(self) -> str:
        """
        Returns the text content of this element (equivalent to JS `textContent`).
        """
        js = f"globalThis.__phantom_elements[{self._handle_id!r}] ? globalThis.__phantom_elements[{self._handle_id!r}].textContent : ''"
        res = self._context.eval(js)
        return str(res) if res is not None else ""

    @property
    @_ensure_valid
    def inner_html(self) -> str:
        """
        Returns the inner HTML of this element (equivalent to JS `innerHTML`).
        """
        js = f"globalThis.__phantom_elements[{self._handle_id!r}] ? globalThis.__phantom_elements[{self._handle_id!r}].innerHTML : ''"
        res = self._context.eval(js)
        return str(res) if res is not None else ""

    @property
    @_ensure_valid
    def html(self) -> str:
        """
        Returns the outer HTML serialization of this element (equivalent to JS `outerHTML`).
        """
        js = f"globalThis.__phantom_elements[{self._handle_id!r}] ? globalThis.__phantom_elements[{self._handle_id!r}].outerHTML : ''"
        res = self._context.eval(js)
        return str(res) if res is not None else ""

    @property
    @_ensure_valid
    def attrs(self) -> dict[str, str]:
        """Return a copy of the element's attributes keyed by attribute name."""
        js = f"""
        (function() {{
            const element = globalThis.__phantom_elements[{json.dumps(self._handle_id)}];
            if (!element) return "{{}}";
            const attributes = Object.fromEntries(
                element.getAttributeNames().map(name => [name, element.getAttribute(name)])
            );
            return JSON.stringify(attributes);
        }})()
        """
        res = self._context.eval(js)
        return json.loads(res) if res is not None else {}

    @property
    def _is_valid(self) -> bool:
        return self._generation == self._page._generation

    def _create_event_script(
        self,
        event_type: str,
        **kwargs: Any,
    ) -> str:
        js = f"""
        (() => {{
            const elem = globalThis.__phantom_elements[{json.dumps(self._handle_id)}];
            if (!elem) return false;

            const win = (elem.ownerDocument && elem.ownerDocument.defaultView) || globalThis;
            const EventCtor = win.Event || globalThis.Event;
            let event;

            if (EventCtor) {{
                event = new EventCtor({json.dumps(event_type)}, {{
                    bubbles: {str(kwargs.get("bubbles", True)).lower()},
                    cancelable: {str(kwargs.get("cancelable", True)).lower()}
                }});
            }} else if (elem.ownerDocument && typeof elem.ownerDocument.createEvent === 'function') {{
                event = elem.ownerDocument.createEvent('Event');
                event.initEvent(
                    {json.dumps(event_type)},
                    {str(kwargs.get("bubbles", True)).lower()},
                    {str(kwargs.get("cancelable", True)).lower()}
                );
            }} else {{
                return false;
            }}

            return elem.dispatchEvent(event);
        }})()
        """

        return js

    @_ensure_valid
    def get_attribute(self, name: str) -> Optional[str]:
        """
        Returns the value of the named attribute, or None if the attribute
        does not exist.

        Args:
            name: The attribute name (e.g. ' href', 'class', 'value').
        """
        js = f"""
        (function() {{
            const elem = globalThis.__phantom_elements[{self._handle_id!r}];
            if (!elem || typeof elem.getAttribute !== 'function') return null;
            return elem.hasAttribute({name!r}) ? elem.getAttribute({name!r}) : null;
        }})()
        """
        result = self._context.eval(js)
        return str(result) if result is not None else None

    @_ensure_valid
    def click(self) -> None:
        """
        Simulates a mouse click on this element by executing its `click()`
        method or dispatching a click MouseEvent.
        """
        js = f"""
        (function() {{
            const elem = globalThis.__phantom_elements[{self._handle_id!r}];
            if (!elem) return;

            if (typeof elem.click === 'function') {{
                elem.click();
            }} else {{
                const win = (elem.ownerDocument && elem.ownerDocument.defaultView) || globalThis;
                const EventCtor = win.MouseEvent || win.Event || globalThis.Event;
                if (EventCtor) {{
                    const evt = new EventCtor('click', {{ bubbles: true, cancelable: true }});
                    elem.dispatchEvent(evt);
                }}
            }}
        }})()
        """
        self._context.eval(js)

    @_ensure_valid
    def type(self, text: str) -> None:
        """
        Simulates user typing `text` into an input/textarea element.
        Dispatches standard input, change, and blur events compatible with LinkeDOM.
        """
        safe_text = json.dumps(text)

        js = f"""
        (function() {{
            const elem = globalThis.__phantom_elements[{self._handle_id!r}];
            if (!elem) return;

            const valToSet = {safe_text};
            
            const win = (elem.ownerDocument && elem.ownerDocument.defaultView) || globalThis;
            const proto = Object.getPrototypeOf(elem);
            const valueSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;

            if (valueSetter) {{
                valueSetter.call(elem, valToSet);
            }} else {{
                elem.value = valToSet;
            }}

            // Dispatch standard input/change events
            const EventCtor = win.Event || globalThis.Event;

            const dispatchEventByName = function(eventName) {{
                try {{
                    if (EventCtor) {{
                        const evt = new EventCtor(eventName, {{ bubbles: true, cancelable: true }});
                        elem.dispatchEvent(evt);
                    }} else if (elem.ownerDocument && typeof elem.ownerDocument.createEvent === 'function') {{
                        const evt = elem.ownerDocument.createEvent('Event');
                        evt.initEvent(eventName, true, true);
                        elem.dispatchEvent(evt);
                    }}
                }} catch (e) {{}}
            }};

            dispatchEventByName('input');
            dispatchEventByName('change');
            dispatchEventByName('blur');
        }})()
        """

        self._context.eval(js)

    @_ensure_valid
    def dispatch_event(
        self,
        event_type: str,
        *,
        bubbles: bool = True,
        cancelable: bool = True,
    ) -> bool:
        script = self._create_event_script(
            event_type,
            bubbles=bubbles,
            cancelable=cancelable
        )
        return bool(self._context.eval(script))
