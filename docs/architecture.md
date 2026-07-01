# PhantomCurl Architecture

PhantomCurl is built on the concept of "hybrid scraping," where the networking part acts as a full browser (TLS fingerprint), and the execution environment acts as a lightweight sandbox.

## Network Layer
Instead of standard `httpx`, which has a Python JA3 fingerprint, we use `curl_cffi`. It allows specifying `impersonate="chrome110"`, making the request look like a real browser at the TCP/TLS level. This layer manages sessions and cookies.

## Environment Layer
We don't use headless Chrome because it's heavy and easily detected. Instead:
1. **QuickJS** — compiles and executes the site's JS code in memory with minimal overhead.
2. **Domino** — a server-side DOM implementation (in pure JS) that creates `window` and `document` objects. The HTML obtained through the network layer is loaded into Domino, creating a virtual DOM tree.

## Bridge Layer
Sites make requests via `fetch()` or `XMLHttpRequest`. In our environment, these functions are monkey-patched. When JS on the site calls `fetch('/api/data')`, the call is intercepted, the data is serialized, and passed back to Python via the QuickJS API. Our network layer then makes the actual request via `curl_cffi`, receives the response, and returns it to JS as a Promise.