#### `SECURITY.md`
```markdown
# Security Policy

## Reporting a Vulnerability

Since this library is used for web scraping and bypassing protections, the concept of "vulnerability" can be twofold:

- **Library Code Vulnerabilities (RCE, Memory Leaks):** If you found a way to execute arbitrary code on the user's machine via QuickJS or cause a memory leak, email me immediately at visslyxd@gmail.com. Do not create a public Issue!
- **Detection Issues (Anti-bot systems updated):** If Cloudflare or another system starts blocking PhantomCurl requests, this is **not a security vulnerability**. Create a regular Issue with the `anti-detect` label.

## Supported Versions

We only support the latest minor version (e.g., 0.2.x).