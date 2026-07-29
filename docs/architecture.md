# PhantomCurl Architecture

PhantomCurl combines a network client with a lightweight JavaScript and DOM sandbox. It is deliberately smaller than a real browser: it can make TLS-impersonated HTTP requests, parse HTML, execute supported classic scripts, and expose the resulting DOM to Python.

## Network Layer
Instead of standard `httpx`, the project uses `curl_cffi`. It allows specifying `impersonate="chrome110"`, making the request use that browser's TLS profile. One `NetworkSession` is shared by a `PhantomClient` and every page it creates, so cookies persist across requests.

`RetryConfig` belongs to this layer. It controls retryable status codes, allowed methods, and exponential backoff. Its default is one attempt, so enabling retries is an explicit client decision. `StorageState` is a JSON-serializable snapshot of the cookie jar; applications decide where and how to store it.

## Environment Layer
The environment has two parts:

1. **QuickJS** compiles and executes classic JavaScript in memory. Every page navigation starts a fresh context with time and memory limits, preventing JavaScript state from leaking between origins.
2. **Linkedom** provides the virtual `window` and `document` objects. The network response HTML is parsed into this DOM, which can then be queried and manipulated through `Page` and `Element`.

## Page lifecycle

`Page.goto(url)` fetches the document through the shared network session, uses the final response URL as the base URL, parses the HTML, and runs supported inline and external classic scripts in document order. Relative external scripts are fetched through the same session and receive a `Referer` header.

The current runtime does not implement a browser request bridge: `fetch()`, `XMLHttpRequest`, `localStorage`, and `sessionStorage` are unavailable. ES modules are also unsupported because QuickJS is called in classic-script mode and no module resolver or dependency loader exists.
