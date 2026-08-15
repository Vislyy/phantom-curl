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
