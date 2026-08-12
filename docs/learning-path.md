# PhantomCurl Learning Path

This document deliberately gives you goals and acceptance criteria instead of
ready-made implementations. Work on one task at a time, write tests first, and
ask for a review when your solution is ready.

## 1. Per-request retry overrides

`RetryConfig` currently applies to the whole `PhantomClient`. Extend the public
request API so one request can override that policy without mutating the
client's default configuration.

Research topics: immutable dataclasses, `dataclasses.replace`, HTTP method
idempotency, and the `Retry-After` response header.

Done means:

- a `POST` is not retried by default;
- a caller can opt in to retrying it explicitly;
- a server-provided `Retry-After` value takes precedence over exponential
  backoff when it is valid;
- local tests cover every rule without contacting the internet.

## 2. Session state beyond cookies (implemented, without the JavaScript bridge)

`StorageState` saves cookies and origin-scoped local-storage data. The next
step is to expose that data to page JavaScript; do not add `sessionStorage` at
the same time.

Research topics: origin definition, JSON schema design, backward-compatible
serialization, and validation of untrusted JSON.

Done means:

- the old cookie-only JSON remains valid;
- storage for `https://example.test` never appears for `https://other.test`;
- malformed JSON produces a useful `ValueError`, not a partial import;
- a round-trip test proves no data is lost.

## 3. A minimal `fetch` bridge (implemented)

The current bridge is Promise-based and same-origin. It supports common HTTP
methods, string bodies, JSON/text responses, cookies, and Referer. It
deliberately does not implement CORS, redirects, streams, `FormData`,
`AbortController`, `Headers`, or `Request`.

Research topics: QuickJS Python `add_callable`, JSON serialization across a
language boundary, URL joining, and QuickJS pending jobs/microtasks.

Done means:

- a page script can call `fetch('/api/value')` and read a text or JSON result;
- its request shares the page's cookies and sends a referer;
- cross-origin requests fail with an explanatory error;
- a local HTTP-server test proves the behavior.

## 4. ESM loading (implemented subset)

The current loader resolves static same-origin imports, caches a module URL
for one page navigation, and reports missing module URLs with their importer.
It intentionally does not support dynamic imports, re-exports, top-level
`await`, or live bindings.

Research topics: QuickJS module evaluation API, static versus dynamic imports,
module cache, relative URL resolution, import cycles, and source provenance.

Done means:

- `import './math.js'` resolves relative to the importing module;
- the same URL is evaluated once per page navigation;
- a missing module reports its URL and importer;
- tests cover a relative import and a cyclic import.

## 5. Async client

Only introduce it once the synchronous API is well tested. Keep the sync and
async public interfaces aligned rather than allowing them to drift apart.

Research topics: `curl_cffi.AsyncSession`, `asyncio` cancellation, semaphores,
and deterministic asynchronous tests.

Done means:

- concurrent requests honor a configurable limit;
- cancelling one request does not close the whole client;
- the async client has the same retry and storage semantics as the sync one;
- tests use a local server and do not depend on timing guesses.
