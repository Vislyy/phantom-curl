# 🕵️‍♂️ PhantomCurl

[![CI Status](https://img.shields.io/github/actions/workflow/status/Vislyy/phantom-curl/ci.yml?branch=main)](https://github.com/Vislyy/phantom-curl/actions)
[![PyPI version](https://img.shields.io/pypi/v/phantom-curl.svg)](https://pypi.org/project/phantom-curl/)
[![Python Versions](https://img.shields.io/pypi/pyversions/phantom-curl.svg)](https://pypi.org/project/phantom-curl/)

**PhantomCurl** is a Python library for HTTP requests with TLS impersonation and a lightweight HTML/JavaScript environment powered by `curl_cffi`, QuickJS, and Linkedom.

No Selenium, Playwright, or external browser driver. It can parse a page, run classic scripts, and inspect or modify its DOM from Python.

## 🎯 Why PhantomCurl?

- **The `requests`/`httpx` problem:** They can't execute JS. Many sites render content via React/Vue.
- **The Selenium/Playwright problem:** They are heavy, require installing browsers, eat RAM, and are easily detected.
- **The PhantomCurl solution:** A lightweight context (QuickJS) that parses HTML into a DOM tree, executes supported classic scripts, and combines it with the browser-like TLS profiles provided by `curl_cffi`.

## ✨ Key Features

- 🚀 **TLS impersonation:** `curl_cffi` browser profiles such as Chrome and Safari.
- 🧠 **Embedded JavaScript:** QuickJS runs classic scripts and a limited static ES-module subset directly in the Python process.
- 🏗️ **DOM interaction:** Linkedom supports selectors, attributes, clicks, text input, and DOM changes.
- 🍪 **Shared session cookies:** requests, pages, `document.cookie`, and page `fetch()` use the same cookie jar.
- 🌐 **Page fetch:** same-origin Promise-based `fetch()` supports common HTTP methods, string bodies, and JSON/text responses.
- 🔁 **Retry policy:** retry transient network failures and selected HTTP status codes with exponential backoff.
- 💾 **Portable cookie state:** export a session to JSON and restore it in another client.
- 🔒 **Execution limits:** each page JavaScript context has time and memory limits.

## Current limitations

- This is not a browser replacement. `XMLHttpRequest`, the JavaScript `localStorage`/`sessionStorage` APIs, CORS, streaming fetch bodies, browser fingerprint spoofing, and CAPTCHA solving are not implemented. Storage snapshots can already import and export origin-scoped local-storage data.
- `fetch()` is same-origin only; it has no redirect handling, `FormData`, `AbortController`, or browser `Headers`/`Request` objects.
- ES modules support static same-origin imports and a limited `import`/`export` syntax. Dynamic imports, re-exports, top-level `await`, and live bindings are unsupported.
- Page scripts run in a lightweight DOM environment; timers run only while `Page` drains its event loop, automatically for microtasks and zero-delay timeouts or manually through `page.run_event_loop()`.

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

    # Persist cookies; writing the returned JSON is your application's job.
    state_json = client.export_storage_state().to_json()
```

## 📦 Installation

```bash
pip install phantom-curl
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
