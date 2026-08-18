# PhantomCurl Learning Path

This document deliberately gives you goals and acceptance criteria instead of
ready-made implementations. Work on one task at a time, write tests first, and
ask for a review when your solution is ready. Completed milestones remain here
as a record of the supported behavior, not as unfinished work.

## 1. Per-request retry overrides (implemented)

`RetryConfig` applies to the whole `PhantomClient`, while one request can
replace it with `retry_config` or adjust only `max_attempts`. Neither override
mutates the client's default policy.

Research topics: immutable dataclasses, `dataclasses.replace`, HTTP method
idempotency, and the `Retry-After` response header.

Done means:

- a `POST` is not retried by default;
- a caller can opt in to retrying it explicitly;
- a server-provided `Retry-After` value takes precedence over exponential
  backoff when it is valid;
- local tests cover every rule without contacting the internet.

## 2. Session state beyond cookies (implemented)

`StorageState` saves cookies and origin-scoped local-storage data.
`localStorage` is exposed to page JavaScript with `getItem()`, `setItem()`,
`removeItem()`, `clear()`, `key()`, and `length`. Writes persist through the
shared session and are visible to new pages of the same origin.

`sessionStorage` implements the same API, but lives in a single `Page`. It
survives navigation in that page, remains isolated from other pages, and is
not serialized into `StorageState`.

Research topics: origin definition, JSON schema design, backward-compatible
serialization, and validation of untrusted JSON.

Done means:

- old cookie-only JSON remains valid;
- storage for `https://example.test` never appears for `https://other.test`;
- malformed JSON produces a useful `ValueError`, not a partial import;
- a round-trip test proves no data is lost;
- a write in one page is visible to a newly created page of the same origin.
- a `sessionStorage` write survives navigation in one page but is absent in a
  newly created page.

## 3. A minimal `fetch` bridge (implemented)

The current bridge is Promise-based and same-origin. It supports common HTTP
methods, string bodies, JSON/text responses, cookies, Referer, plain-object
headers, the implemented `Headers` subset, and the string-field `FormData`
subset. `FormData` is encoded as `multipart/form-data`, but does not yet
support `Blob`, `File`, or construction from an HTML form. The bridge
deliberately does not implement CORS, redirects, streams, `AbortController`,
`Request`, or response-header access.

Research topics: QuickJS Python `add_callable`, JSON serialization across a
language boundary, URL joining, and QuickJS pending jobs/microtasks.

For a detailed walkthrough of the `Headers` bridge, see
[Headers and the fetch bridge](learning/headers-fetch-bridge.md). For the
equivalent walkthrough of multipart form data, see
[FormData and multipart fetch](learning/form-data-fetch.md).

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

## 5. Browser URL APIs (implemented subset)

`URL` and `URLSearchParams` are installed as globals and on `window` before
page scripts execute. The current implementation resolves relative HTTP(S)
references, provides common URL fields and setters, and keeps `URL.search` and
`URL.searchParams` synchronized. It intentionally excludes object-URL helpers
and the rarest WHATWG URL parsing edge cases.

Research topics: the WHATWG URL Standard, `application/x-www-form-urlencoded`
encoding, the difference between URL paths and query strings, and iterable
JavaScript APIs.

Done means:

- a relative reference resolves against an absolute base;
- `window.URL` is the same constructor as global `URL`;
- `URLSearchParams` preserves duplicate keys and updates a parent URL query.

## 6. Async client (future)

Only introduce it once the synchronous API is well tested. Keep the sync and
async public interfaces aligned rather than allowing them to drift apart.

Research topics: `curl_cffi.AsyncSession`, `asyncio` cancellation, semaphores,
and deterministic asynchronous tests.

Done means:

- concurrent requests honor a configurable limit;
- cancelling one request does not close the whole client;
- the async client has the same retry and storage semantics as the sync one;
- tests use a local server and do not depend on timing guesses.
