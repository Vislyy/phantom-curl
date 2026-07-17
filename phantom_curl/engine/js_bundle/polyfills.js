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
globalThis.atob = function (base64) {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  base64 = base64.replace(/[^A-Za-z0-9+/]/g, "");
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

/**
 * Buffer - a minimal polyfill covering only what Linkedom's internal
 * dependencies (htmlparser2/entities) actually use: decoding a
 * base64-encoded string into a byte array.
 *
 * This is NOT a full Buffer implementation - it does not support
 * the full Node.js Buffer API surface.
 */
globalThis.Buffer = {
  from: function (input, encoding) {
    if (encoding === "base64") {
      const binaryString = atob(input);
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