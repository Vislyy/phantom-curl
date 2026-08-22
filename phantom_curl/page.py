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
from urllib.parse import urljoin, urlsplit

from phantom_curl.bridge.interceptor import FetchInterceptor
from phantom_curl.bridge.event_loop import TimerBridge
from phantom_curl.bridge.module_loader import ModuleLoader
from phantom_curl.engine.context import JSContext
from phantom_curl.engine.dom_builder import DOMBuilder
from phantom_curl.element import Element
from phantom_curl.models import OriginPolicy, Response
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
    _MAX_AUTOMATIC_NAVIGATIONS: ClassVar[int] = 10

    def __init__(self, session: NetworkSession, origin_policy: Optional[OriginPolicy] = None):
        """
        Creates a new Page backed by a fresh JS execution context.

        Args:
            network_session: The NetworkSession used to perform real
                HTTP requests for this page. This session is shared
                with (owned by) the caller (typically PhantomClient),
                so that cookies set outside the page are visible to
                requests made from within it, and vice versa.
            origin_policy: Cross-origin access rule for this page's
                JavaScript ``fetch()`` and ``XMLHttpRequest`` calls. It does
                not affect direct requests made through ``NetworkSession``.

        Note:
            A new, isolated JSContext is created for every Page
            instance rather than shared across pages. Each JS context
            holds page-specific global state (the parsed document,
            registered bridge callables, the pending microtask queue),
            which must not leak between unrelated pages/tabs.
        """
        self._session = session
        self._stealth_config = session.stealth_config
        self._origin_policy = origin_policy or OriginPolicy()
        self._fetch_interceptor: Optional[FetchInterceptor] = None
        self._module_loader: Optional[ModuleLoader] = None
        self._timer_bridge: Optional[TimerBridge] = None
        self._automatic_navigation_depth = 0
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

        self._fetch_interceptor = FetchInterceptor(
            self._session,
            self.url,
            self._origin_policy,
        )
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
                cleanupFetchAbort(resolver);

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
                    headers: new Headers(result.headers),
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

            function serializeFetchHeaders(headers) {
                if (!(headers instanceof Headers)) {
                    return headers;
                }

                const serialized = Object.create(null);
                for (const [name, value] of headers) {
                    serialized[name] = value;
                }
                return serialized;
            }

            function hasFetchHeader(headers, name) {
                const targetName = String(name).toLowerCase();
                return Object.keys(headers).some(function (headerName) {
                    return headerName.toLowerCase() === targetName;
                });
            }

            function escapeFormDataName(name) {
                return String(name).replace(/\\r/g, '%0D').replace(/\\n/g, '%0A').replace(/"/g, '%22');
            }

            function serializeFormData(formData, headers) {
                const boundary = '----PhantomCurlFormBoundary' + Math.random().toString(16).slice(2);
                const chunks = [];
                for (const [name, value] of formData) {
                    chunks.push(
                        '--' + boundary + '\\r\\n'
                        + 'Content-Disposition: form-data; name="' + escapeFormDataName(name) + '"\\r\\n\\r\\n'
                        + value + '\\r\\n'
                    );
                }
                chunks.push('--' + boundary + '--\\r\\n');

                const formHeaders = Object.create(null);
                for (const headerName of Object.keys(headers)) {
                    formHeaders[headerName] = headers[headerName];
                }
                if (!hasFetchHeader(formHeaders, 'Content-Type')) {
                    formHeaders['content-type'] = 'multipart/form-data; boundary=' + boundary;
                }

                return {body: chunks.join(''), headers: formHeaders};
            }

            function cleanupFetchAbort(resolver) {
                if (resolver.signal && resolver.abortHandler) {
                    resolver.signal.removeEventListener('abort', resolver.abortHandler);
                }
            }

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

                    const signal = options.signal === undefined || options.signal === null ? null : options.signal;
                    if (signal !== null && !(signal instanceof AbortSignal)) {
                        reject(new TypeError('PhantomCurl fetch signal must be an AbortSignal'));
                        return;
                    }
                    if (signal !== null && signal.aborted) {
                        reject(signal.reason);
                        return;
                    }

                    const id = ++globalThis.__phantom_fetch_id;
                    const method = options.method === undefined ? 'GET' : String(options.method);
                    const rawHeaders = options.headers === undefined ? {} : options.headers;
                    const headers = serializeFetchHeaders(rawHeaders);
                    const rawBody = options.body === undefined ? null : options.body;
                    const serializedFormData = rawBody instanceof FormData
                        ? serializeFormData(rawBody, headers)
                        : null;
                    const body = serializedFormData === null ? rawBody : serializedFormData.body;
                    const requestHeaders = serializedFormData === null ? headers : serializedFormData.headers;
                    const abortHandler = function () {
                        const pendingIndex = globalThis.__phantom_pending_fetches.findIndex(function (request) {
                            return request.id === id;
                        });
                        if (pendingIndex !== -1) {
                            globalThis.__phantom_pending_fetches.splice(pendingIndex, 1);
                        }
                        delete globalThis.__phantom_fetch_resolvers[id];
                        reject(signal.reason);
                    };
                    globalThis.__phantom_fetch_resolvers[id] = {
                        resolve: resolve,
                        reject: reject,
                        signal: signal,
                        abortHandler: signal === null ? null : abortHandler
                    };
                    globalThis.__phantom_pending_fetches.push({
                        id: id,
                        url: input,
                        method: method,
                        headers: requestHeaders,
                        body: body
                    });
                    if (signal !== null) {
                        signal.addEventListener('abort', abortHandler, {once: true});
                    }
                });
            };
            """
        )

    def _install_xhr_bridge(self) -> None:
        """Expose the supported asynchronous XMLHttpRequest subset to page scripts."""
        if self._fetch_interceptor is None:
            return

        self._context.eval(
            """
            globalThis.__phantom_pending_xhrs = [];
            globalThis.__phantom_xhr_instances = Object.create(null);
            globalThis.__phantom_xhr_id = 0;

            globalThis.__phantom_take_xhrs = function () {
                const pending = globalThis.__phantom_pending_xhrs;
                globalThis.__phantom_pending_xhrs = [];
                return JSON.stringify(pending);
            };

            function PhantomXMLHttpRequest() {
                this.readyState = PhantomXMLHttpRequest.UNSENT;
                this.status = 0;
                this.statusText = '';
                this.responseText = '';
                this.response = '';
                this.responseURL = '';
                this.responseType = '';
                this.onreadystatechange = null;
                this.onload = null;
                this.onerror = null;
                this.onabort = null;
                this._method = null;
                this._url = null;
                this._requestHeaders = Object.create(null);
                this._responseHeaders = Object.create(null);
                this._sent = false;
                this._requestId = null;
            }

            PhantomXMLHttpRequest.UNSENT = 0;
            PhantomXMLHttpRequest.OPENED = 1;
            PhantomXMLHttpRequest.HEADERS_RECEIVED = 2;
            PhantomXMLHttpRequest.LOADING = 3;
            PhantomXMLHttpRequest.DONE = 4;

            PhantomXMLHttpRequest.prototype.UNSENT = PhantomXMLHttpRequest.UNSENT;
            PhantomXMLHttpRequest.prototype.OPENED = PhantomXMLHttpRequest.OPENED;
            PhantomXMLHttpRequest.prototype.HEADERS_RECEIVED = PhantomXMLHttpRequest.HEADERS_RECEIVED;
            PhantomXMLHttpRequest.prototype.LOADING = PhantomXMLHttpRequest.LOADING;
            PhantomXMLHttpRequest.prototype.DONE = PhantomXMLHttpRequest.DONE;

            PhantomXMLHttpRequest.prototype._dispatch = function (type) {
                const handler = this['on' + type];
                if (typeof handler === 'function') {
                    handler.call(this, {type: type, target: this, currentTarget: this});
                }
            };

            PhantomXMLHttpRequest.prototype._setReadyState = function (nextState) {
                this.readyState = nextState;
                this._dispatch('readystatechange');
            };

            PhantomXMLHttpRequest.prototype.open = function (method, url, async) {
                if (async === false) {
                    throw new TypeError('PhantomCurl XMLHttpRequest only supports asynchronous requests');
                }

                this._method = String(method);
                this._url = String(url);
                this.status = 0;
                this.statusText = '';
                this.responseText = '';
                this.response = '';
                this.responseURL = '';
                this._requestHeaders = Object.create(null);
                this._responseHeaders = Object.create(null);
                this._sent = false;
                this._requestId = null;
                this._setReadyState(PhantomXMLHttpRequest.OPENED);
            };

            PhantomXMLHttpRequest.prototype.setRequestHeader = function (name, value) {
                if (this.readyState !== PhantomXMLHttpRequest.OPENED || this._sent) {
                    throw new Error('setRequestHeader() requires an opened, unsent XMLHttpRequest');
                }

                const requestedName = String(name);
                const existingName = Object.keys(this._requestHeaders).find(function (headerName) {
                    return headerName.toLowerCase() === requestedName.toLowerCase();
                });
                const headerName = existingName === undefined ? requestedName : existingName;
                const headerValue = String(value);
                this._requestHeaders[headerName] = existingName === undefined
                    ? headerValue
                    : this._requestHeaders[headerName] + ', ' + headerValue;
            };

            PhantomXMLHttpRequest.prototype.send = function (body) {
                if (this.readyState !== PhantomXMLHttpRequest.OPENED || this._sent) {
                    throw new Error('send() requires an opened, unsent XMLHttpRequest');
                }
                if (body !== undefined && body !== null && typeof body !== 'string') {
                    throw new TypeError('PhantomCurl XMLHttpRequest currently supports string request bodies only');
                }

                const id = ++globalThis.__phantom_xhr_id;
                const headers = Object.create(null);
                for (const name of Object.keys(this._requestHeaders)) {
                    headers[name] = this._requestHeaders[name];
                }
                const hasContentType = Object.keys(headers).some(function (name) {
                    return name.toLowerCase() === 'content-type';
                });
                if (typeof body === 'string' && !hasContentType) {
                    headers['content-type'] = 'text/plain;charset=UTF-8';
                }

                this._sent = true;
                this._requestId = id;
                globalThis.__phantom_xhr_instances[id] = this;
                globalThis.__phantom_pending_xhrs.push({
                    id: id,
                    url: this._url,
                    method: this._method,
                    headers: headers,
                    body: body === undefined ? null : body,
                });
            };

            PhantomXMLHttpRequest.prototype.abort = function () {
                if (this._requestId !== null) {
                    const pendingIndex = globalThis.__phantom_pending_xhrs.findIndex(function (request) {
                        return request.id === this._requestId;
                    }, this);
                    if (pendingIndex !== -1) {
                        globalThis.__phantom_pending_xhrs.splice(pendingIndex, 1);
                    }
                    delete globalThis.__phantom_xhr_instances[this._requestId];
                }

                this._requestId = null;
                this._sent = false;
                if (this.readyState !== PhantomXMLHttpRequest.UNSENT) {
                    this._setReadyState(PhantomXMLHttpRequest.DONE);
                    this._dispatch('abort');
                }
            };

            PhantomXMLHttpRequest.prototype.getResponseHeader = function (name) {
                if (this.readyState < PhantomXMLHttpRequest.HEADERS_RECEIVED) {
                    return null;
                }

                const requestedName = String(name).toLowerCase();
                const actualName = Object.keys(this._responseHeaders).find(function (headerName) {
                    return headerName.toLowerCase() === requestedName;
                });
                return actualName === undefined ? null : this._responseHeaders[actualName];
            };

            PhantomXMLHttpRequest.prototype.getAllResponseHeaders = function () {
                if (this.readyState < PhantomXMLHttpRequest.HEADERS_RECEIVED) {
                    return null;
                }
                return Object.keys(this._responseHeaders)
                    .map(function (name) { return name + ': ' + this._responseHeaders[name]; }, this)
                    .join('\\r\\n');
            };

            globalThis.__phantom_complete_xhr = function (id, resultJson) {
                const xhr = globalThis.__phantom_xhr_instances[id];
                delete globalThis.__phantom_xhr_instances[id];
                if (!xhr) {
                    return;
                }

                xhr._requestId = null;
                xhr._sent = false;
                const result = JSON.parse(resultJson);
                if (result.error) {
                    xhr.status = 0;
                    xhr.statusText = '';
                    xhr.responseText = '';
                    xhr.response = '';
                    xhr._setReadyState(PhantomXMLHttpRequest.DONE);
                    xhr._dispatch('error');
                    return;
                }

                xhr.status = result.status;
                xhr.statusText = '';
                xhr.responseURL = result.url;
                xhr._responseHeaders = result.headers;
                xhr._setReadyState(PhantomXMLHttpRequest.HEADERS_RECEIVED);
                xhr.responseText = result.text;
                xhr.response = result.text;
                xhr._setReadyState(PhantomXMLHttpRequest.LOADING);
                xhr._setReadyState(PhantomXMLHttpRequest.DONE);
                xhr._dispatch('load');
            };

            globalThis.XMLHttpRequest = PhantomXMLHttpRequest;
            if (globalThis.window) {
                globalThis.window.XMLHttpRequest = PhantomXMLHttpRequest;
            }
            """
        )

    def _install_navigation_bridge(self) -> None:
        self._context.eval(
            """
            globalThis.__phantom_pending_navigations = [];
            globalThis.__phantom_take_navigations = function () {
                const pending = globalThis.__phantom_pending_navigations;
                globalThis.__phantom_pending_navigations = [];
                return JSON.stringify(pending)
            }

            const locationObject = globalThis.location;
            let currentHref = locationObject.href;

            globalThis.__phantom_set_location_for_history = function (value) {
                const nextLocation = new URL(String(value), currentHref);
                if (nextLocation.origin !== locationObject.origin) {
                    throw new Error('PhantomCurl history only permits same-origin URLs');
                }

                currentHref = nextLocation.href;
                locationObject.origin = nextLocation.origin;
                locationObject.protocol = nextLocation.protocol;
                locationObject.host = nextLocation.host;
                locationObject.hostname = nextLocation.hostname;
                locationObject.port = nextLocation.port;
                locationObject.pathname = nextLocation.pathname;
                locationObject.search = nextLocation.search;
                locationObject.hash = nextLocation.hash;
                return currentHref;
            };

            Object.defineProperty(locationObject, "href", {
                configurable: true,
                enumerable: true,
                get() {
                    return currentHref;
                },
                set(value) {
                    currentHref = String(value);
                    globalThis.__phantom_pending_navigations.push(currentHref);
                }
            });

            locationObject.assign = function (value) {
                locationObject.href = value;
            };
            locationObject.replace = function (value) {
                locationObject.href = value;
            };
            """
        )

    def _install_history_bridge(self) -> None:
        """Install the JSON-state subset of the History API for SPA routing."""
        self._context.eval(
            """
            function cloneHistoryState(state) {
                if (state === undefined) {
                    return null;
                }

                const serialized = JSON.stringify(state);
                if (serialized === undefined) {
                    throw new TypeError('PhantomCurl history state must be JSON-serializable');
                }
                return JSON.parse(serialized);
            }

            const historyEntries = [{
                state: null,
                url: globalThis.location.href,
            }];
            let historyIndex = 0;
            const historyObject = {
                pushState: function (state, unused, url) {
                    const nextState = cloneHistoryState(state);
                    const nextUrl = arguments.length < 3 || url === undefined
                        ? globalThis.location.href
                        : globalThis.__phantom_set_location_for_history(url);

                    historyEntries.splice(historyIndex + 1);
                    historyEntries.push({state: nextState, url: nextUrl});
                    historyIndex = historyEntries.length - 1;
                },
                replaceState: function (state, unused, url) {
                    const nextState = cloneHistoryState(state);
                    const nextUrl = arguments.length < 3 || url === undefined
                        ? globalThis.location.href
                        : globalThis.__phantom_set_location_for_history(url);

                    historyEntries[historyIndex] = {state: nextState, url: nextUrl};
                },
                go: function (delta) {
                    const numericDelta = delta === undefined ? 0 : Number(delta);
                    if (!Number.isFinite(numericDelta)) {
                        return;
                    }

                    const nextIndex = historyIndex + Math.trunc(numericDelta);
                    if (nextIndex < 0 || nextIndex >= historyEntries.length || nextIndex === historyIndex) {
                        return;
                    }

                    historyIndex = nextIndex;
                    const entry = historyEntries[historyIndex];
                    globalThis.__phantom_set_location_for_history(entry.url);

                    const event = new globalThis.window.Event('popstate');
                    event.state = cloneHistoryState(entry.state);
                    globalThis.window.dispatchEvent(event);
                },
                back: function () {
                    this.go(-1);
                },
                forward: function () {
                    this.go(1);
                },
            };

            Object.defineProperty(historyObject, 'length', {
                enumerable: true,
                get: function () {
                    return historyEntries.length;
                },
            });
            Object.defineProperty(historyObject, 'state', {
                enumerable: true,
                get: function () {
                    return cloneHistoryState(historyEntries[historyIndex].state);
                },
            });

            globalThis.history = historyObject;
            globalThis.window.history = historyObject;
            """
        )

    def _initialize_form_control_defaults(self) -> None:
        """Synchronize parsed checked attributes with Linkedom control properties."""
        self._context.eval(
            """
            for (const control of globalThis.document.querySelectorAll('input')) {
                const type = String(control.getAttribute('type') || '').toLowerCase();
                if ((type === 'checkbox' || type === 'radio') && control.hasAttribute('checked')) {
                    control.checked = true;
                }
            }
            """
        )

    def _install_document_lifecycle(self) -> None:
        """Install page-load events and the matching document.readyState values."""
        self._context.eval(
            """
            let phantomDocumentReadyState = 'loading';
            Object.defineProperty(globalThis.document, 'readyState', {
                configurable: true,
                enumerable: true,
                get: function () {
                    return phantomDocumentReadyState;
                },
            });

            globalThis.__phantom_fire_dom_content_loaded = function () {
                phantomDocumentReadyState = 'interactive';
                globalThis.document.dispatchEvent(
                    new globalThis.window.Event('DOMContentLoaded')
                );
            };
            globalThis.__phantom_fire_window_load = function () {
                phantomDocumentReadyState = 'complete';
                globalThis.window.dispatchEvent(new globalThis.window.Event('load'));
            };
            """
        )

    def _finish_document_loading(self) -> None:
        """Dispatch the supported document lifecycle events after page scripts."""
        self._context.eval("globalThis.__phantom_fire_dom_content_loaded();")
        self._drain_runtime()
        self._execute_pending_scripts()
        self._context.eval("globalThis.__phantom_fire_window_load();")
        self._drain_runtime()
        self._execute_pending_scripts()

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

    def _flush_fetch_requests(self) -> bool:
        """Send queued fetch requests and report whether the queue contained work."""
        if self._fetch_interceptor is None:
            return False

        processed_request = False
        while True:
            self._context.execute_pending_jobs()
            self._flush_cookie_writes()
            pending = json.loads(self._context.eval("globalThis.__phantom_take_fetches()"))
            if not pending:
                return processed_request

            for request in pending:
                if not isinstance(request, dict) or not isinstance(request.get("id"), int):
                    raise InterceptorError("fetch bridge received invalid queued request data")

                processed_request = True
                result = self._fetch_interceptor.handle(request)
                self._flush_cookie_writes()
                self._context.eval(
                    "globalThis.__phantom_complete_fetch("
                    f"{request['id']}, {json.dumps(json.dumps(result))}"
                    ");"
                )

    def _flush_xhr_requests(self) -> bool:
        """Send queued XMLHttpRequests and report whether the queue contained work."""
        if self._fetch_interceptor is None:
            return False

        processed_request = False
        while True:
            self._context.execute_pending_jobs()
            self._flush_cookie_writes()
            pending = json.loads(self._context.eval("globalThis.__phantom_take_xhrs()"))
            if not pending:
                return processed_request

            for request in pending:
                if not isinstance(request, dict) or not isinstance(request.get("id"), int):
                    raise InterceptorError("XMLHttpRequest bridge received invalid queued request data")

                processed_request = True
                result = self._fetch_interceptor.handle(request)
                self._flush_cookie_writes()
                self._context.eval(
                    "globalThis.__phantom_complete_xhr("
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

    def _take_pending_navigations(self) -> Optional[str]:
        pending_navigations = json.loads(self._context.eval("__phantom_take_navigations()"))
        if not pending_navigations:
            return None

        requested_url = pending_navigations[-1]
        if not isinstance(requested_url, str) or not requested_url:
            return None

        if self.url is None:
            return None

        final_url = urljoin(self.url, requested_url)

        if urlsplit(final_url).scheme in ("http", "https"):
            return final_url

        return None

    def _follow_queued_navigation(self) -> Optional[Response]:
        """Follow one queued JS navigation after the current JS work is stable."""
        target_url = self._take_pending_navigations()
        if target_url is None:
            return None

        if self._automatic_navigation_depth >= self._MAX_AUTOMATIC_NAVIGATIONS:
            error = InterceptorError(
                f"Stopped after {self._MAX_AUTOMATIC_NAVIGATIONS} automatic navigations"
            )
            logger.warning("%s on %s", error, self.url)
            self.script_errors.append(error)
            return None

        self._automatic_navigation_depth += 1
        try:
            return self.goto(target_url)
        finally:
            self._automatic_navigation_depth -= 1

    def _drain_runtime(self, timeout: float = 0.0) -> None:
        """Run microtasks, queued fetches and timers due within ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            self._flush_local_storage_operations()
            self._flush_session_storage_operations()
            processed_network_request = self._flush_fetch_requests()
            processed_network_request = self._flush_xhr_requests() or processed_network_request
            self._flush_local_storage_operations()
            self._flush_session_storage_operations()
            if processed_network_request:
                continue

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
            self._module_loader = ModuleLoader(
                self._context,
                self._session,
                self.url,
                self._origin_policy,
            )

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
        is_classic_script = entry["code_type"] != "module"

        self._context.eval(
            f"""
            globalThis.__phantom_current_script = globalThis.__phantom_elements[{json.dumps(entry['node_id'])}];
            globalThis.document.currentScript = {"globalThis.__phantom_current_script" if is_classic_script else "null"};
            """
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
                except JSRuntimeError as error:
                    script_error = JSRuntimeError(
                        f"External script execution failed for {script_url!r}: {error}",
                        js_stack=error.js_stack,
                        source=error.source,
                    )
                    logger.warning(
                        "External script fetch/execution failed on %s (from %s): %s",
                        script_url, url, script_error,
                    )
                    self.script_errors.append(script_error)
                except Exception as e:
                    logger.warning(
                        "External script fetch/execution failed on %s (from %s): %s",
                        script_url, url, e,
                    )
                    self.script_errors.append(e)
        finally:
            self._context.eval(
                "globalThis.__phantom_current_script = null;"
                "globalThis.document.currentScript = null;"
            )

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
        self._install_navigation_bridge()
        self._install_history_bridge()
        self._initialize_form_control_defaults()
        self._install_document_lifecycle()
        self._install_local_storage_bridge()
        self._install_fetch_bridge()
        self._install_xhr_bridge()
        self._install_timer_bridge()
        self._install_module_loader()
        self._install_session_storage_bridge()

        self._generation += 1

        self.script_errors = []

        self._execute_pending_scripts()
        self._finish_document_loading()

        self.response = response
        followed_response = self._follow_queued_navigation()
        return response if followed_response is None else followed_response

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
        self._execute_pending_scripts()
        self._follow_queued_navigation()
        return result

    def run_event_loop(self, timeout: float = 0.0) -> None:
        """Run timers and pending browser tasks for at most ``timeout`` seconds."""
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._drain_runtime(timeout)
        self._execute_pending_scripts()
        self._follow_queued_navigation()

    def eval(self, js_code: str) -> Any:
        """Alias for :meth:`evaluate`, retained for a concise interactive API."""
        return self.evaluate(js_code)
