/**
 * phantom_curl polyfills
 * ========================
 *
 * Minimal polyfills for Node.js/Browser-specific globals that
 * Linkedom (and its internal dependencies like htmlparser2) expect
 * to exist, but which are not part of the QuickJS runtime by default.
 *
 * These must be loaded BEFORE the Linkedom bundle.
 */

/**
 * atob - decodes a base64-encoded string into a binary string,
 * where each character represents one byte of the decoded data.
 *
 * This is a standard Web API function, not part of core ECMAScript,
 * so QuickJS does not provide it out of the box.
 */
if (typeof globalThis.atob === "undefined") {
  globalThis.atob = function (base64) {
    const chars =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    base64 = String(base64).replace(/[^A-Za-z0-9+/]/g, "");
    let result = "";
    let i = 0;
    while (i < base64.length) {
      const enc1 = chars.indexOf(base64.charAt(i++));
      const enc2 = chars.indexOf(base64.charAt(i++));
      const enc3 = chars.indexOf(base64.charAt(i++));
      const enc4 = chars.indexOf(base64.charAt(i++));

      const chr1 = (enc1 << 2) | (enc2 >> 4);
      const chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
      const chr3 = ((enc3 & 3) << 6) | enc4;

      result += String.fromCharCode(chr1);
      if (enc3 !== -1 && enc3 !== 64) result += String.fromCharCode(chr2);
      if (enc4 !== -1 && enc4 !== 64) result += String.fromCharCode(chr3);
    }
    return result;
  };
}

/**
 * Buffer - a minimal polyfill covering only what Linkedom's internal
 * dependencies (htmlparser2/entities) actually use: decoding a
 * base64-encoded string into a byte array.
 *
 * This is NOT a full Buffer implementation - it does not support
 * the full Node.js Buffer API surface.
 */
if (typeof globalThis.Buffer === "undefined") {
  globalThis.Buffer = {
    from: function (input, encoding) {
      if (encoding === "base64") {
        const binaryString = globalThis.atob(input);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }
        return bytes;
      }
      const encoder = new TextEncoder();
      return encoder.encode(input);
    },
  };
}

/**
 * Navigator Polyfill
 * ==================
 * Provides basic browser environment flags required by modern web scripts
 * and frameworks (e.g. Vue, React, Cloudflare).
 *
 * Note: Temporarily hardcoded. Will be wired to Python Stealth Layer later.
 */
if (typeof globalThis.navigator === "undefined") {
  globalThis.navigator = {
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    appName: "Netscape",
    appVersion: "5.0 (Windows)",
    platform: "Win32",
    language: "en-US",
    languages: ["en-US", "en"],
    cookieEnabled: true,
    onLine: true,
    webdriver: false,
    hardwareConcurrency: 4,
    maxTouchPoints: 0,
  };
}

/**
 * Screen & Window Metrics Polyfills
 * =================================
 * Exposes viewport and screen dimension properties used by responsive
 * design scripts and analytics modules.
 */
if (typeof globalThis.screen === "undefined") {
  globalThis.screen = {
    width: 1920,
    height: 1080,
    availWidth: 1920,
    availHeight: 1040,
    colorDepth: 24,
    pixelDepth: 24,
  };
}

if (typeof globalThis.innerWidth === "undefined") {
  globalThis.innerWidth = 1920;
  globalThis.innerHeight = 1080;
  globalThis.outerWidth = 1920;
  globalThis.outerHeight = 1040;
  globalThis.devicePixelRatio = 1;
}

/**
 * Crypto Polyfill
 * ===============
 * Provides basic Web Crypto API capabilities (`getRandomValues`) required by
 * UUID generation modules, Cloudflare Beacon, and security scripts.
 */
if (
  typeof globalThis.crypto === "undefined" ||
  typeof globalThis.crypto.getRandomValues === "undefined"
) {
  globalThis.crypto = {
    getRandomValues: function (array) {
      if (!array || (!array.length && array.length !== 0)) {
        throw new TypeError(
          "Failed to execute 'getRandomValues' on 'Crypto': parameter 1 is not of type 'ArrayBufferView'."
        );
      }
      for (let i = 0; i < array.length; i++) {
        array[i] = Math.floor(Math.random() * 256);
      }
      return array;
    },
  };
}

/**
 * document.write / document.writeln polyfill
 * ===========================================
 *
 * Real browsers implement document.write as a streaming parser hook:
 * content written while the document is still being parsed is inserted
 * at the parser's current position (i.e. at the <script> tag that
 * issued the call). Linkedom parses the entire HTML up front via
 * parseHTML(), so by the time any script runs the streaming parser
 * no longer exists, and Linkedom does not provide document.write at
 * all (typeof document.write === 'undefined').
 *
 * This polyfill emulates the streaming behavior by inserting the
 * written markup immediately AFTER the <script> tag that is
 * currently executing. The "currently executing script" is tracked
 * by the Python side (Page.goto) through a global marker:
 *
 *     globalThis.__phantom_current_script
 *
 * which is set to the <script> node before the script's source is
 * evaluated, and cleared afterwards. The polyfill uses
 * insertAdjacentHTML('afterend', ...) on that node, which places the
 * new content as a sibling directly following the <script> tag -
 * mirroring where a real browser's parser would have resumed parsing.
 *
 * If no current script is set (e.g. write() called after page load),
 * the content is appended to document.body, matching the spec's
 * "after load" behavior of writing into the body.
 *
 * Note: this polyfill is installed lazily - globalThis.document is
 * bound by DOMBuilder.parse_html(), which runs AFTER polyfills.js
 * is loaded during DOMBuilder.__init__. Therefore the document is
 * resolved at call-time via globalThis.document rather than captured
 * at definition-time.
 */
(function () {
  function flushInto(targetNode, html) {
    const doc = globalThis.document;
    if (!doc) return;
    if (!targetNode) {
      const body = doc.body;
      if (!body) return;
      body.insertAdjacentHTML("beforeend", html);
      return;
    }
    targetNode.insertAdjacentHTML("afterend", html);
  }

  function writeImpl(args, addNewline) {
    const markup =
      Array.prototype.slice.call(args).join("") + (addNewline ? "\n" : "");
    const current = globalThis.__phantom_current_script || null;
    flushInto(current, markup);
  }

  function ensureInstalled() {
    const doc = globalThis.document;
    if (!doc || doc.__phantom_write_installed) return;
    doc.write = function () {
      writeImpl(arguments, false);
    };
    doc.writeln = function () {
      writeImpl(arguments, true);
    };
    doc.__phantom_write_installed = true;
  }

  // Install once a document exists. parse_html() also calls this
  // after assigning globalThis.document, so the lazy guard above is
  // enough to be idempotent.
  ensureInstalled();
  globalThis.__phantom_ensure_write = ensureInstalled;
})();

if (typeof globalThis.console === "undefined") {
  globalThis.console = {
    log: typeof print === "function" ? print : function () {},
    error: typeof print === "function" ? print : function () {},
    warn: typeof print === "function" ? print : function () {},
    info: typeof print === "function" ? print : function () {},
    debug: typeof print === "function" ? print : function () {},
  };
}

/**
 * URL and URLSearchParams polyfills
 * ================================
 *
 * QuickJS provides ECMAScript primitives, but not browser URL APIs.  These
 * implementations cover the HTTP(S)-oriented surface that page scripts use
 * most often: resolving relative URLs, inspecting URL components, and reading
 * or updating query parameters.
 */
(function () {
  function formEncode(value) {
    return encodeURIComponent(String(value))
      .replace(/%20/g, "+")
      .replace(/[!'()~]/g, function (character) {
        return "%" + character.charCodeAt(0).toString(16).toUpperCase();
      });
  }

  function formDecode(value) {
    const source = String(value).replace(/\+/g, " ");
    try {
      return decodeURIComponent(source);
    } catch (_) {
      // Native URLSearchParams replaces malformed escapes instead of making
      // a page fail. Keeping the original value is the safest lightweight
      // fallback without implementing the full UTF-8 decoder here.
      return source;
    }
  }

  class PhantomURLSearchParams {
    constructor(init, onChange) {
      this._entries = [];
      this._onChange = typeof onChange === "function" ? onChange : null;

      if (init === undefined || init === null) {
        return;
      }

      if (init instanceof PhantomURLSearchParams) {
        this._entries = init._entries.map(function (entry) {
          return [entry[0], entry[1]];
        });
        return;
      }

      if (typeof init === "string") {
        this._replaceFromString(init, false);
        return;
      }

      if (typeof init[Symbol.iterator] === "function") {
        for (const pair of init) {
          const values = Array.from(pair);
          if (values.length !== 2) {
            throw new TypeError("URLSearchParams initializer must contain key-value pairs");
          }
          this._entries.push([String(values[0]), String(values[1])]);
        }
        return;
      }

      for (const key of Object.keys(init)) {
        this._entries.push([String(key), String(init[key])]);
      }
    }

    get size() {
      return this._entries.length;
    }

    _replaceFromString(value, shouldNotify) {
      const source = String(value).replace(/^\?/, "");
      this._entries = [];

      if (source) {
        for (const item of source.split("&")) {
          if (!item) {
            continue;
          }

          const separator = item.indexOf("=");
          const rawName = separator === -1 ? item : item.slice(0, separator);
          const rawValue = separator === -1 ? "" : item.slice(separator + 1);
          this._entries.push([formDecode(rawName), formDecode(rawValue)]);
        }
      }

      if (shouldNotify) {
        this._notify();
      }
    }

    _notify() {
      if (this._onChange) {
        this._onChange(this.toString());
      }
    }

    append(name, value) {
      this._entries.push([String(name), String(value)]);
      this._notify();
    }

    delete(name, value) {
      const key = String(name);
      const matchesValue = arguments.length > 1;
      const targetValue = String(value);
      this._entries = this._entries.filter(function (entry) {
        return entry[0] !== key || (matchesValue && entry[1] !== targetValue);
      });
      this._notify();
    }

    get(name) {
      const key = String(name);
      for (const entry of this._entries) {
        if (entry[0] === key) {
          return entry[1];
        }
      }
      return null;
    }

    getAll(name) {
      const key = String(name);
      return this._entries
        .filter(function (entry) {
          return entry[0] === key;
        })
        .map(function (entry) {
          return entry[1];
        });
    }

    has(name, value) {
      const key = String(name);
      const matchesValue = arguments.length > 1;
      const targetValue = String(value);
      return this._entries.some(function (entry) {
        return entry[0] === key && (!matchesValue || entry[1] === targetValue);
      });
    }

    set(name, value) {
      const key = String(name);
      const stringValue = String(value);
      let replaced = false;
      const entries = [];

      for (const entry of this._entries) {
        if (entry[0] !== key) {
          entries.push(entry);
        } else if (!replaced) {
          entries.push([key, stringValue]);
          replaced = true;
        }
      }

      if (!replaced) {
        entries.push([key, stringValue]);
      }

      this._entries = entries;
      this._notify();
    }

    sort() {
      this._entries = this._entries
        .map(function (entry, index) {
          return { entry: entry, index: index };
        })
        .sort(function (left, right) {
          if (left.entry[0] < right.entry[0]) return -1;
          if (left.entry[0] > right.entry[0]) return 1;
          return left.index - right.index;
        })
        .map(function (item) {
          return item.entry;
        });
      this._notify();
    }

    entries() {
      return this._entries.map(function (entry) {
        return [entry[0], entry[1]];
      })[Symbol.iterator]();
    }

    keys() {
      return this._entries.map(function (entry) {
        return entry[0];
      })[Symbol.iterator]();
    }

    values() {
      return this._entries.map(function (entry) {
        return entry[1];
      })[Symbol.iterator]();
    }

    forEach(callback, thisArg) {
      if (typeof callback !== "function") {
        throw new TypeError("URLSearchParams.forEach requires a callback function");
      }

      for (const entry of this._entries) {
        callback.call(thisArg, entry[1], entry[0], this);
      }
    }

    toString() {
      return this._entries
        .map(function (entry) {
          return formEncode(entry[0]) + "=" + formEncode(entry[1]);
        })
        .join("&");
    }

    [Symbol.iterator]() {
      return this.entries();
    }
  }

  function normalizePath(path) {
    const isAbsolute = path.startsWith("/");
    const needsTrailingSlash = /\/(?:\.|\.\.)$/.test(path) || path.endsWith("/");
    const segments = [];

    for (const segment of path.split("/")) {
      if (!segment || segment === ".") {
        continue;
      }
      if (segment === "..") {
        if (segments.length) {
          segments.pop();
        }
        continue;
      }
      segments.push(segment);
    }

    let normalized = (isAbsolute ? "/" : "") + segments.join("/");
    if (needsTrailingSlash && normalized && !normalized.endsWith("/")) {
      normalized += "/";
    }
    return normalized || (isAbsolute ? "/" : "");
  }

  function encodeUrlPart(value) {
    return encodeURI(String(value));
  }

  function formatHost(hostname, port) {
    const host = hostname.includes(":") ? "[" + hostname + "]" : hostname;
    return port ? host + ":" + port : host;
  }

  function parseAuthority(authority) {
    let username = "";
    let password = "";
    let hasPassword = false;
    let hostPort = authority;
    const at = authority.lastIndexOf("@");

    if (at !== -1) {
      const credentials = authority.slice(0, at);
      hostPort = authority.slice(at + 1);
      const separator = credentials.indexOf(":");
      username = encodeURIComponent(separator === -1 ? credentials : credentials.slice(0, separator));
      if (separator !== -1) {
        hasPassword = true;
        password = encodeURIComponent(credentials.slice(separator + 1));
      }
    }

    let hostname = hostPort;
    let port = "";
    if (hostPort.startsWith("[")) {
      const closingBracket = hostPort.indexOf("]");
      if (closingBracket === -1) {
        throw new TypeError("Invalid URL host");
      }
      hostname = hostPort.slice(1, closingBracket).toLowerCase();
      const portPart = hostPort.slice(closingBracket + 1);
      if (portPart && !/^:\d*$/.test(portPart)) {
        throw new TypeError("Invalid URL port");
      }
      port = portPart ? portPart.slice(1) : "";
    } else {
      const colon = hostPort.lastIndexOf(":");
      if (colon !== -1 && hostPort.indexOf(":") === colon) {
        hostname = hostPort.slice(0, colon);
        port = hostPort.slice(colon + 1);
      }
      hostname = hostname.toLowerCase();
    }

    if (!hostname) {
      throw new TypeError("Invalid URL host");
    }
    if (port && (!/^\d+$/.test(port) || Number(port) > 65535)) {
      throw new TypeError("Invalid URL port");
    }

    return { username: username, password: password, hasPassword: hasPassword, hostname: hostname, port: port };
  }

  function createRecord(scheme, authority, path, search, hash, isOpaque) {
    const hasAuthority = authority !== null;
    const credentials = hasAuthority ? parseAuthority(authority) : {};
    let port = credentials.port || "";
    if ((scheme === "http" || scheme === "ws") && port === "80") port = "";
    if ((scheme === "https" || scheme === "wss") && port === "443") port = "";

    return {
      scheme: scheme,
      username: credentials.username || "",
      password: credentials.password || "",
      hasPassword: credentials.hasPassword || false,
      hostname: credentials.hostname || "",
      port: port,
      hasAuthority: hasAuthority,
      pathname: isOpaque ? encodeUrlPart(path) : encodeUrlPart(normalizePath(path || "/")),
      search: search ? "?" + encodeUrlPart(search) : "",
      hash: hash ? "#" + encodeUrlPart(hash) : "",
      isOpaque: isOpaque,
    };
  }

  function parseAbsolute(input) {
    const match = /^([A-Za-z][A-Za-z\d+.-]*):([\s\S]*)$/.exec(input);
    if (!match) {
      throw new TypeError("Invalid URL");
    }

    const scheme = match[1].toLowerCase();
    let rest = match[2];
    let hash = "";
    let search = "";
    const hashIndex = rest.indexOf("#");
    if (hashIndex !== -1) {
      hash = rest.slice(hashIndex + 1);
      rest = rest.slice(0, hashIndex);
    }
    const searchIndex = rest.indexOf("?");
    if (searchIndex !== -1) {
      search = rest.slice(searchIndex + 1);
      rest = rest.slice(0, searchIndex);
    }

    if (rest.startsWith("//")) {
      const authorityAndPath = rest.slice(2);
      const slash = authorityAndPath.indexOf("/");
      const authority = slash === -1 ? authorityAndPath : authorityAndPath.slice(0, slash);
      const path = slash === -1 ? "/" : authorityAndPath.slice(slash);
      return createRecord(scheme, authority, path, search, hash, false);
    }

    return createRecord(scheme, null, rest, search, hash, true);
  }

  function cloneRecord(record) {
    return {
      scheme: record.scheme,
      username: record.username,
      password: record.password,
      hasPassword: record.hasPassword,
      hostname: record.hostname,
      port: record.port,
      hasAuthority: record.hasAuthority,
      pathname: record.pathname,
      search: record.search,
      hash: record.hash,
      isOpaque: record.isOpaque,
    };
  }

  function parseUrl(input, base) {
    const source = String(input).trim();
    if (/^[A-Za-z][A-Za-z\d+.-]*:/.test(source)) {
      return parseAbsolute(source);
    }
    if (base === undefined) {
      throw new TypeError("Invalid URL");
    }

    const baseRecord = parseAbsolute(String(base).trim());
    if (!baseRecord.hasAuthority) {
      throw new TypeError("Cannot resolve a relative URL against an opaque base URL");
    }
    if (source.startsWith("//")) {
      return parseAbsolute(baseRecord.scheme + ":" + source);
    }

    let path = source;
    let hash = "";
    let search = null;
    const hashIndex = path.indexOf("#");
    if (hashIndex !== -1) {
      hash = path.slice(hashIndex + 1);
      path = path.slice(0, hashIndex);
    }
    const searchIndex = path.indexOf("?");
    if (searchIndex !== -1) {
      search = path.slice(searchIndex + 1);
      path = path.slice(0, searchIndex);
    }

    const result = cloneRecord(baseRecord);
    result.hash = hash ? "#" + encodeUrlPart(hash) : "";
    result.search = search === null ? baseRecord.search : (search ? "?" + encodeUrlPart(search) : "?");

    if (path) {
      if (path.startsWith("/")) {
        result.pathname = encodeUrlPart(normalizePath(path));
      } else {
        const lastSlash = baseRecord.pathname.lastIndexOf("/");
        const directory = baseRecord.pathname.slice(0, lastSlash + 1);
        result.pathname = encodeUrlPart(normalizePath(directory + path));
      }
    }

    return result;
  }

  function serialize(record) {
    let result = record.scheme + ":";
    if (record.hasAuthority) {
      let credentials = record.username;
      if (record.hasPassword) {
        credentials += ":" + record.password;
      }
      if (credentials) {
        result += "//" + credentials + "@";
      } else {
        result += "//";
      }
      result += formatHost(record.hostname, record.port);
    }
    return result + record.pathname + record.search + record.hash;
  }

  class PhantomURL {
    constructor(input, base) {
      this._record = parseUrl(input, base);
      this._searchParams = new PhantomURLSearchParams(this._record.search, (value) => {
        this._record.search = value ? "?" + value : "";
      });
    }

    get href() {
      return serialize(this._record);
    }

    set href(value) {
      this._record = parseUrl(value);
      this._searchParams._replaceFromString(this._record.search, false);
    }

    get origin() {
      if (!this._record.hasAuthority || !/^(https?|wss?)$/.test(this._record.scheme)) {
        return "null";
      }
      return this._record.scheme + "://" + formatHost(this._record.hostname, this._record.port);
    }

    get protocol() {
      return this._record.scheme + ":";
    }

    set protocol(value) {
      const match = /^([A-Za-z][A-Za-z\d+.-]*):?$/.exec(String(value));
      if (!match) return;
      this._record.scheme = match[1].toLowerCase();
      if ((this._record.scheme === "http" || this._record.scheme === "ws") && this._record.port === "80") {
        this._record.port = "";
      }
      if ((this._record.scheme === "https" || this._record.scheme === "wss") && this._record.port === "443") {
        this._record.port = "";
      }
    }

    get username() {
      return this._record.username;
    }

    set username(value) {
      if (this._record.hasAuthority) this._record.username = encodeURIComponent(String(value));
    }

    get password() {
      return this._record.password;
    }

    set password(value) {
      if (this._record.hasAuthority) {
        this._record.password = encodeURIComponent(String(value));
        this._record.hasPassword = true;
      }
    }

    get host() {
      return this._record.hasAuthority ? formatHost(this._record.hostname, this._record.port) : "";
    }

    set host(value) {
      if (!this._record.hasAuthority) return;
      const authority = parseAuthority(String(value));
      this._record.hostname = authority.hostname;
      this._record.port = authority.port;
    }

    get hostname() {
      return this._record.hostname;
    }

    set hostname(value) {
      if (!this._record.hasAuthority || !value) return;
      this._record.hostname = String(value).replace(/^\[|\]$/g, "").toLowerCase();
    }

    get port() {
      return this._record.port;
    }

    set port(value) {
      const port = String(value);
      if (!this._record.hasAuthority || (port && (!/^\d+$/.test(port) || Number(port) > 65535))) {
        return;
      }
      this._record.port = port;
    }

    get pathname() {
      return this._record.pathname;
    }

    set pathname(value) {
      const path = String(value);
      if (this._record.isOpaque) {
        this._record.pathname = encodeUrlPart(path);
      } else {
        this._record.pathname = encodeUrlPart(normalizePath(path.startsWith("/") ? path : "/" + path));
      }
    }

    get search() {
      return this._record.search;
    }

    set search(value) {
      const source = String(value);
      this._record.search = source ? "?" + encodeUrlPart(source.replace(/^\?/, "")) : "";
      this._searchParams._replaceFromString(this._record.search, false);
    }

    get searchParams() {
      return this._searchParams;
    }

    get hash() {
      return this._record.hash;
    }

    set hash(value) {
      const source = String(value);
      this._record.hash = source ? "#" + encodeUrlPart(source.replace(/^#/, "")) : "";
    }

    toString() {
      return this.href;
    }

    toJSON() {
      return this.href;
    }

    static canParse(input, base) {
      try {
        parseUrl(input, base);
        return true;
      } catch (_) {
        return false;
      }
    }
  }

  if (typeof globalThis.URLSearchParams === "undefined") {
    globalThis.URLSearchParams = PhantomURLSearchParams;
  }
  if (typeof globalThis.URL === "undefined") {
    globalThis.URL = PhantomURL;
  }
})();

/**
 * Headers polyfill
 * ================
 *
 * Implements the browser-facing container for HTTP header fields. The fetch
 * bridge is intentionally wired separately: this class first gives page code
 * the normal Web API surface, then a later bridge change can serialize it into
 * Python request options.
 */
(function () {
  function normalizeHeaderName(name) {
    const normalized = String(name).toLowerCase();
    if (!/^[!#$%&'*+\-.^_|~0-9a-z]+$/.test(normalized)) {
      throw new TypeError("Invalid HTTP header name");
    }
    return normalized;
  }

  function normalizeHeaderValue(value) {
    const normalized = String(value).trim();
    if (/[\r\n]/.test(normalized)) {
      throw new TypeError("Invalid HTTP header value");
    }
    return normalized;
  }

  class PhantomHeaders {
    constructor(init) {
      this._headers = new Map();

      if (init === undefined || init === null) {
        return;
      }

      if (init instanceof PhantomHeaders) {
        for (const entry of init.entries()) {
          this.set(entry[0], entry[1]);
        }
        return;
      }

      if (typeof init[Symbol.iterator] === "function") {
        for (const pair of init) {
          const values = Array.from(pair);
          if (values.length !== 2) {
            throw new TypeError("Headers initializer must contain name-value pairs");
          }
          this.append(values[0], values[1]);
        }
        return;
      }

      for (const name of Object.keys(init)) {
        this.append(name, init[name]);
      }
    }

    append(name, value) {
      const normalizedName = normalizeHeaderName(name);
      const normalizedValue = normalizeHeaderValue(value);
      const existing = this._headers.get(normalizedName);
      this._headers.set(normalizedName, existing ? existing + ", " + normalizedValue : normalizedValue);
    }

    delete(name) {
      this._headers.delete(normalizeHeaderName(name));
    }

    get(name) {
      const value = this._headers.get(normalizeHeaderName(name));
      return value === undefined ? null : value;
    }

    has(name) {
      return this._headers.has(normalizeHeaderName(name));
    }

    set(name, value) {
      this._headers.set(normalizeHeaderName(name), normalizeHeaderValue(value));
    }

    _sortedEntries() {
      return Array.from(this._headers.entries()).sort(function (left, right) {
        if (left[0] < right[0]) return -1;
        if (left[0] > right[0]) return 1;
        return 0;
      });
    }

    entries() {
      return this._sortedEntries()[Symbol.iterator]();
    }

    keys() {
      return this._sortedEntries()
        .map(function (entry) {
          return entry[0];
        })[Symbol.iterator]();
    }

    values() {
      return this._sortedEntries()
        .map(function (entry) {
          return entry[1];
        })[Symbol.iterator]();
    }

    forEach(callback, thisArg) {
      if (typeof callback !== "function") {
        throw new TypeError("Headers.forEach requires a callback function");
      }

      for (const entry of this._sortedEntries()) {
        callback.call(thisArg, entry[1], entry[0], this);
      }
    }

    [Symbol.iterator]() {
      return this.entries();
    }
  }

  if (typeof globalThis.Headers === "undefined") {
    globalThis.Headers = PhantomHeaders;
  }
})();

/**
 * FormData polyfill
 * =================
 *
 * Provides the string-field subset of the browser FormData API. Binary values
 * and HTML form-element initialization require Blob/File and form controls,
 * which the lightweight runtime does not implement yet.
 */
(function () {
  class PhantomFormData {
    constructor(form) {
      if (form !== undefined) {
        throw new TypeError("PhantomCurl FormData does not support HTML form initialization");
      }
      this._entries = [];
    }

    append(name, value) {
      this._entries.push([String(name), String(value)]);
    }

    delete(name) {
      const targetName = String(name);
      this._entries = this._entries.filter(function (entry) {
        return entry[0] !== targetName;
      });
    }

    get(name) {
      const targetName = String(name);
      for (const entry of this._entries) {
        if (entry[0] === targetName) {
          return entry[1];
        }
      }
      return null;
    }

    getAll(name) {
      const targetName = String(name);
      return this._entries
        .filter(function (entry) {
          return entry[0] === targetName;
        })
        .map(function (entry) {
          return entry[1];
        });
    }

    has(name) {
      const targetName = String(name);
      return this._entries.some(function (entry) {
        return entry[0] === targetName;
      });
    }

    set(name, value) {
      const targetName = String(name);
      const stringValue = String(value);
      let replaced = false;
      const entries = [];

      for (const entry of this._entries) {
        if (entry[0] !== targetName) {
          entries.push(entry);
        } else if (!replaced) {
          entries.push([targetName, stringValue]);
          replaced = true;
        }
      }

      if (!replaced) {
        entries.push([targetName, stringValue]);
      }

      this._entries = entries;
    }

    entries() {
      return this._entries.map(function (entry) {
        return [entry[0], entry[1]];
      })[Symbol.iterator]();
    }

    keys() {
      return this._entries.map(function (entry) {
        return entry[0];
      })[Symbol.iterator]();
    }

    values() {
      return this._entries.map(function (entry) {
        return entry[1];
      })[Symbol.iterator]();
    }

    forEach(callback, thisArg) {
      if (typeof callback !== "function") {
        throw new TypeError("FormData.forEach requires a callback function");
      }

      for (const entry of this._entries) {
        callback.call(thisArg, entry[1], entry[0], this);
      }
    }

    [Symbol.iterator]() {
      return this.entries();
    }
  }

  if (typeof globalThis.FormData === "undefined") {
    globalThis.FormData = PhantomFormData;
  }
})();

class PhantomLocalStorage {
  constructor(entries, recordOperation) {
    this._store = new Map(entries || []);
    this._recordOperation = recordOperation;
  }

  get length() {
    return this._store.size;
  }

  getItem(key) {
    key = String(key);
    return this._store.has(key) ? this._store.get(key) : null;
  }

  setItem(key, value) {
    key = String(key);
    value = String(value);
    this._store.set(key, value);
    this._recordOperation({ type: "set", key, value });
  }

  removeItem(key) {
    key = String(key);
    if (!this._store.has(key)) {
      return;
    }

    this._store.delete(key);
    this._recordOperation({ type: "remove", key });
  }

  clear() {
    if (this._store.size === 0) {
      return;
    }

    this._store.clear();
    this._recordOperation({ type: "clear" });
  }

  key(index) {
    const position = Number(index);
    if (!Number.isInteger(position) || position < 0) {
      return null;
    }

    const keys = Array.from(this._store.keys());
    return position < keys.length ? keys[position] : null;
  }
}

globalThis.__phantom_install_local_storage = function(entries) {
  globalThis.__phantom_pending_local_storage_operations = [];
  const recordOperation = function(operation) {
    globalThis.__phantom_pending_local_storage_operations.push(operation);
  };
  const localStorage = new PhantomLocalStorage(entries, recordOperation);

  globalThis.localStorage = localStorage;
  globalThis.window.localStorage = localStorage;
};

globalThis.__phantom_take_local_storage_operations = function() {
  const operations = globalThis.__phantom_pending_local_storage_operations;
  globalThis.__phantom_pending_local_storage_operations = [];
  return JSON.stringify(operations);
};

class PhantomSessionStorage {
    constructor(entries, recordOperation) {
    this._store = new Map(entries || []);
    this._recordOperation = recordOperation;
  }

  get length() {
    return this._store.size;
  }

  getItem(key) {
    key = String(key);
    return this._store.has(key) ? this._store.get(key) : null;
  }

  setItem(key, value) {
    key = String(key);
    value = String(value);
    this._store.set(key, value);
    this._recordOperation({ type: "set", key, value });
  }

  removeItem(key) {
    key = String(key);
    if (!this._store.has(key)) {
      return;
    }

    this._store.delete(key);
    this._recordOperation({ type: "remove", key });
  }

  clear() {
    if (this._store.size === 0) {
      return;
    }

    this._store.clear();
    this._recordOperation({ type: "clear" });
  }

  key(index) {
    const position = Number(index);
    if (!Number.isInteger(position) || position < 0) {
      return null;
    }

    const keys = Array.from(this._store.keys());
    return position < keys.length ? keys[position] : null;
  }
}

globalThis.__phantom_install_session_storage = function(entries) {
  globalThis.__phantom_pending_session_storage_operations = [];
  const recordOperation = function(operation) {
    globalThis.__phantom_pending_session_storage_operations.push(operation);
  };
  const sessionStorage = new PhantomSessionStorage(entries, recordOperation);

  globalThis.sessionStorage = sessionStorage;
  globalThis.window.sessionStorage = sessionStorage;
};

globalThis.__phantom_take_session_storage_operations = function() {
  const operations = globalThis.__phantom_pending_session_storage_operations;
  globalThis.__phantom_pending_session_storage_operations = [];
  return JSON.stringify(operations);
};
