# 🕵️‍♂️ PhantomCurl

**PhantomCurl** is a Python library for HTTP requests with TLS impersonation and a lightweight HTML/JavaScript environment powered by `curl_cffi`, QuickJS, and Linkedom.

No Selenium, Playwright, or external browser driver. It can parse a page, run supported classic scripts and static ES modules, and inspect or modify its DOM from Python. It deliberately implements a documented browser-like subset rather than claiming to replace a full browser.

> [!WARNING]
> **Project status: educational and experimental.** PhantomCurl is a learning project and is not feature-complete or ready for production use. Its JavaScript, DOM, networking, and ES-module support intentionally cover only documented subsets; complex websites may fail or behave differently from a real browser.

## 🎯 Why PhantomCurl?

- **The `requests`/`httpx` problem:** They can't execute JS. Many sites render content via React/Vue.
- **The Selenium/Playwright problem:** They are heavy, require installing browsers, eat RAM, and are easily detected.
- **The PhantomCurl solution:** A lightweight context (QuickJS) that parses HTML into a DOM tree, executes a supported JavaScript subset, and combines it with the browser-like TLS profiles provided by `curl_cffi`.

## ✨ Key Features

- 🚀 **TLS impersonation:** `curl_cffi` browser profiles such as Chrome and Safari.
- 🧠 **Embedded JavaScript:** QuickJS runs classic scripts and a limited static ES-module subset directly in the Python process.
- 🏗️ **DOM interaction:** Linkedom supports selectors, attributes, clicks, text input, and DOM changes.
- 🍪 **Shared session cookies:** requests, pages, `document.cookie`, and page `fetch()` use the same cookie jar.
- 🌐 **Page fetch:** Promise-based `fetch()` supports common HTTP methods, request/response `Headers`, string-field `FormData`, queued-request cancellation with `AbortController`, and an explicit cross-origin allowlist.
- 📮 **Page XHR:** asynchronous `XMLHttpRequest` supports textual requests and responses, headers, ready-state callbacks, load/error/abort handlers, and the same cross-origin policy as `fetch()`.
- 💾 **Origin-scoped local storage:** `localStorage` persists across new pages for the same origin and is included in `StorageState` exports.
- 🗃️ **Page-scoped session storage:** `sessionStorage` persists across navigations of one `Page`, but is isolated from other pages and exports.
- 🔗 **Browser URL APIs:** `URL` resolves relative addresses and exposes common URL fields; `URLSearchParams` reads and mutates query strings.
- 🧭 **SPA History API:** `history.pushState()`, `replaceState()`, `back()`, `forward()`, and `go()` update same-origin client-side routes without fetching a new document.
- 🖼️ **Baseline image API:** `new Image()` creates a detached DOM `<img>` for scripts that configure images before inserting them.
- ⏱️ **Baseline timing API:** `performance.timeOrigin` and `performance.now()` are available to page scripts.
- 🖱️ **DOM events:** Python can click, type, and dispatch custom events; registered JavaScript handlers run in the page context.
- ⏳ **Page tasks:** Promise jobs and timers are drained by the page runtime; `location.href` and `location.assign()` can queue a page navigation, while `document.write()` and dynamically inserted supported scripts are executed after runtime work.
- 📄 **Document lifecycle:** page scripts can use `document.readyState`, `DOMContentLoaded`, and `window.load`.
- 🔁 **Retry policy:** retry transient network failures and selected HTTP status codes with exponential backoff.
- 📦 **Portable session state:** export cookies and origin-scoped local storage to JSON and restore them in another client.
- 🔒 **Execution limits:** each page JavaScript context has time and memory limits.

## Current limitations

- This is not a browser replacement. CORS, streaming fetch bodies, complete browser-fingerprint spoofing, and CAPTCHA solving are not implemented.
- `localStorage` supports `getItem()`, `setItem()`, `removeItem()`, `clear()`, `key()`, and `length`. It does not support named-property access such as `localStorage.theme`, `StorageEvent`, or synchronizing writes into pages that were already created.
- `sessionStorage` has the same supported methods, but belongs to one `Page` and its origins. It survives `page.goto()` in that page, is isolated from other `Page` objects, and is not included in `StorageState`.
- `URL` and `URLSearchParams` support common HTTP(S) URL construction, relative resolution, fields, query mutation, and iteration. They do not implement object-URL helpers or every WHATWG URL parsing edge case, such as internationalized domain names and malformed percent escapes.
- `Image` creates a detached `<img>` element, but it does not load, decode, or render image files and it does not dispatch image `load` or `error` events. `performance` only provides `timeOrigin` and `now()`; resource, navigation, and user-timing entries are unavailable.
- `history` stores JSON-serializable state only and its entries live only for the current document. It supports same-origin route updates and `popstate` from `back()`/`forward()`/`go()`, but not browser session history across documents, `go(0)` reloads, structured-clone edge cases, scroll restoration, or hash-change events.
- The document lifecycle follows the supported script-loading model only: `readyState` changes from `loading` to `interactive` and `complete` while `DOMContentLoaded` and `load` are dispatched. Parser-blocking/deferred/async script distinctions, subresource loading, and load-event timing based on images or stylesheets are not modeled.
- `fetch()` is same-origin by default. `OriginPolicy` can allow specific target origins or all HTTP(S) origins, but it is not browser CORS: PhantomCurl performs neither preflights nor `Access-Control-Allow-*` checks. Cross-origin requests still use the session's normal domain-based cookie jar; browser `credentials` modes are not implemented. Fetch accepts plain-object headers, the implemented `Headers` subset, and string-field `FormData`, which it sends as `multipart/form-data`. `FormData` does not yet support `Blob`, `File`, or construction from an HTML `<form>`. Responses expose a mutable `Headers` snapshot but hide `Set-Cookie`; `Request` objects and redirects are not implemented. An `AbortController` can cancel a queued fetch before Python begins its HTTP request, but cannot interrupt an already running blocking request.
- `XMLHttpRequest` supports asynchronous text requests only: `open()`, `setRequestHeader()`, `send()`, `abort()`, response-header getters, ready states, and the `onreadystatechange`, `onload`, `onerror`, and `onabort` properties. It uses the same URL validation and `OriginPolicy` as `fetch()`. Synchronous XHR, `addEventListener()`, upload progress, `Blob`/`ArrayBuffer`/`Document` response types, timeouts, credentials modes, and interrupting an already running request are unsupported.
- ES modules support static same-origin imports by default and use `OriginPolicy` for explicitly allowed cross-origin modules. Named/default/namespace and side-effect imports, common default exports, named/star/namespace re-exports (`export * as name from ...`), dependency-before-module-body execution, and live export properties through namespace objects are available. Named/default import bindings and full ESM evaluation semantics for complex cycles remain unsupported, alongside dynamic imports, top-level `await`, and `import.meta`; see [the ModuleLoader walkthrough](docs/module-loader-walkthrough.md) for the exact boundary.
- Event listeners run synchronously when JavaScript or `Element` triggers an event. `Element.click()`, `type()`, and `dispatch_event()` automatically drain queued fetches, Promise jobs, and zero-delay timers. Supported scripts inserted during that work are then discovered and executed. Call `page.run_event_loop(timeout)` only for timers scheduled in the future; queued `location.href`, `location.assign()`, and `location.replace()` navigations are followed automatically once the current page operation finishes. `location.replace()` currently has the same document-level effect as `assign()` because full browser session history is not implemented. `Element.click()` follows a normal `<a href>` or supported GET form unless an event handler cancels it. Form POST, files, validation, complex controls, download links, and links targeting another context remain unsupported.

## ⚡ Quick Start

```python
from phantom_curl import OriginPolicy, PhantomClient, RetryConfig, StealthConfig

with PhantomClient(
    StealthConfig(impersonate="chrome"),
    retry_config=RetryConfig(max_attempts=3, backoff_factor=0.2),
    origin_policy=OriginPolicy(allowed_origins={"https://api.example.com"}),
) as client:
    # Make a regular HTTP request
    response = client.get("https://example.com")
    print(response.status_code)

    # Create a virtual page with the same network session and cookies.
    page = client.new_page("https://example.com")
    heading = page.query_selector("h1")
    print(heading.text if heading else "No heading")

    # localStorage changes share the same origin-scoped session state.
    page.eval("localStorage.setItem('visited', 'yes')")

    # Persist cookies and localStorage; writing the JSON is the application's job.
    state_json = client.export_storage_state().to_json()
```

## 📦 Installation

PhantomCurl has not been published to PyPI yet. Install the current version from the repository:

```bash
pip install "git+https://github.com/Vislyy/phantom-curl.git"
```

## 🏗️ Architecture

PhantomCurl currently consists of three implemented layers:
1. **Network Layer:** A wrapper over `curl_cffi` to execute requests with the required TLS fingerprint.
2. **Environment Layer:** QuickJS + Linkedom sandbox that creates an isolated virtual DOM for each page navigation.
3. **Page Layer:** Fetches HTML, scripts, modules, and page fetches through the shared network session, then exposes DOM elements to Python. Page fetches and static modules are same-origin by default and can share an explicit `OriginPolicy` allowlist.

Read more in the [architecture documentation](docs/architecture.md).

## Learning path

Want to contribute features yourself? Start with the [learning path](docs/learning-path.md): it gives scoped exercises, research topics, and testable completion criteria without handing you the implementation.

## 🤝 Contributing

We are open to suggestions! Read [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
