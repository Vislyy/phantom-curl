# 🕵️‍♂️ PhantomCurl

**PhantomCurl** is a Python library for HTTP requests with TLS impersonation and a lightweight HTML/JavaScript environment powered by `curl_cffi`, QuickJS, and Linkedom.

No Selenium, Playwright, or external browser driver. It can parse a page, run supported classic scripts and static ES modules, and inspect or modify its DOM from Python. It deliberately implements a documented browser-like subset rather than claiming to replace a full browser.

## 🎯 Why PhantomCurl?

- **The `requests`/`httpx` problem:** They can't execute JS. Many sites render content via React/Vue.
- **The Selenium/Playwright problem:** They are heavy, require installing browsers, eat RAM, and are easily detected.
- **The PhantomCurl solution:** A lightweight context (QuickJS) that parses HTML into a DOM tree, executes a supported JavaScript subset, and combines it with the browser-like TLS profiles provided by `curl_cffi`.

## ✨ Key Features

- 🚀 **TLS impersonation:** `curl_cffi` browser profiles such as Chrome and Safari.
- 🧠 **Embedded JavaScript:** QuickJS runs classic scripts and a limited static ES-module subset directly in the Python process.
- 🏗️ **DOM interaction:** Linkedom supports selectors, attributes, clicks, text input, and DOM changes.
- 🍪 **Shared session cookies:** requests, pages, `document.cookie`, and page `fetch()` use the same cookie jar.
- 🌐 **Page fetch:** same-origin Promise-based `fetch()` supports common HTTP methods, string bodies, and JSON/text responses.
- 💾 **Origin-scoped local storage:** `localStorage` persists across new pages for the same origin and is included in `StorageState` exports.
- 🗃️ **Page-scoped session storage:** `sessionStorage` persists across navigations of one `Page`, but is isolated from other pages and exports.
- 🖱️ **DOM events:** Python can click, type, and dispatch custom events; registered JavaScript handlers run in the page context.
- ⏱️ **Page tasks:** Promise jobs and timers are drained by the page runtime; `document.write()` and dynamically inserted classic scripts during navigation are supported.
- 🔁 **Retry policy:** retry transient network failures and selected HTTP status codes with exponential backoff.
- 📦 **Portable session state:** export cookies and origin-scoped local storage to JSON and restore them in another client.
- 🔒 **Execution limits:** each page JavaScript context has time and memory limits.

## Current limitations

- This is not a browser replacement. `XMLHttpRequest`, CORS, streaming fetch bodies, complete browser-fingerprint spoofing, and CAPTCHA solving are not implemented.
- `localStorage` supports `getItem()`, `setItem()`, `removeItem()`, `clear()`, `key()`, and `length`. It does not support named-property access such as `localStorage.theme`, `StorageEvent`, or synchronizing writes into pages that were already created.
- `sessionStorage` has the same supported methods, but belongs to one `Page` and its origins. It survives `page.goto()` in that page, is isolated from other `Page` objects, and is not included in `StorageState`.
- `fetch()` is same-origin only; it has no redirect handling, `FormData`, `AbortController`, or browser `Headers`/`Request` objects.
- ES modules support static same-origin imports and a limited `import`/`export` syntax. Dynamic imports, re-exports, top-level `await`, and live bindings are unsupported.
- Event listeners run synchronously when JavaScript or `Element` triggers an event. `Element.click()`, `type()`, and `dispatch_event()` do not yet drain queued `fetch()` calls or timers automatically, so use `page.run_event_loop()` after an interaction that starts asynchronous work. Linkedom does not perform browser default actions such as form submission or link navigation, and scripts inserted after an interaction are not loaded automatically.

## ⚡ Quick Start

```python
from phantom_curl import PhantomClient, RetryConfig, StealthConfig

with PhantomClient(
    StealthConfig(impersonate="chrome"),
    retry_config=RetryConfig(max_attempts=3, backoff_factor=0.2),
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
3. **Page Layer:** Fetches HTML, scripts, modules, and same-origin page fetches through the shared network session, then exposes DOM elements to Python.

Read more in the [architecture documentation](docs/architecture.md).

## Learning path

Want to contribute features yourself? Start with the [learning path](docs/learning-path.md): it gives scoped exercises, research topics, and testable completion criteria without handing you the implementation.

## 🤝 Contributing

We are open to suggestions! Read [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
