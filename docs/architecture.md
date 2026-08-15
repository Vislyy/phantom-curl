# PhantomCurl Architecture

PhantomCurl combines a network client with a lightweight JavaScript and DOM sandbox. It is deliberately smaller than a real browser: it can make TLS-impersonated HTTP requests, parse HTML, execute supported classic scripts and a limited static ES-module subset, and expose the resulting DOM to Python.

## Network Layer
Instead of standard `httpx`, the project uses `curl_cffi`. It allows specifying `impersonate="chrome"`, making the request use a supported browser-like TLS profile. One `NetworkSession` is shared by a `PhantomClient` and every page it creates, so cookies persist across requests.

`RetryConfig` belongs to this layer. It controls retryable status codes, allowed methods, and exponential backoff. Its default is one attempt, so enabling retries is an explicit client decision. A request-level `retry_config` replaces the client's policy for that request, while `max_attempts` changes only the attempt limit and preserves every other field of the selected policy. Neither form mutates the client's configuration.

`StorageState` is a JSON-serializable snapshot of the cookie jar and origin-scoped local-storage data. `NetworkSession` owns this durable state: every new page gets a fresh JavaScript context, but receives the cookies and local-storage entries that belong to its origin.

## Environment Layer
The environment has two parts:

1. **QuickJS** compiles and executes JavaScript in memory. Every page navigation starts a fresh context with time and memory limits, preventing page-local JavaScript and DOM state from leaking between navigations. Promise jobs are drained by `Page`; zero-delay timers run automatically, while delayed timers require `Page.run_event_loop()`.
2. **Linkedom** provides the virtual `window` and `document` objects. The network response HTML is parsed into this DOM, which can then be queried and manipulated through `Page` and `Element`.

## Page lifecycle

`Page.goto(url)` fetches the document through the shared network session, uses the final response URL as the base URL, parses the HTML, and runs supported inline, external, and module scripts in document order. Relative external scripts and static module dependencies are fetched through the same session and receive a `Referer` header. `location`, `document.referrer`, `navigator.languages`, `document.cookie`, `console`, screen metrics, timers, page-local `fetch()`, and `localStorage` are installed before page scripts run.

`document.cookie` writes and `localStorage` mutations are first queued by JavaScript, then persisted to the shared `NetworkSession` while `Page` drains the runtime. The local-storage facade supports `getItem()`, `setItem()`, `removeItem()`, `clear()`, `key()`, and `length`. It is deliberately smaller than the browser API: named-property access, `StorageEvent`, and live synchronization to already-created pages are unavailable.

`fetch()` is Promise-based and same-origin only. It supports `GET`, `HEAD`, `OPTIONS`, `POST`, `PUT`, `PATCH`, and `DELETE`, string request bodies, and `text()`/`json()` response methods, but not CORS, redirects, streams, `FormData`, `AbortController`, `Headers`, or `Request`. The ES-module loader supports static imports plus basic named/default/namespace exports and imports, caches each URL per navigation, and handles simple cycles. Dynamic imports, re-exports, top-level `await`, and live bindings remain unsupported. `XMLHttpRequest` and `sessionStorage` are unavailable.
