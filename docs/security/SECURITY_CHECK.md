# AEGIS security check

Run 2026-11-21 20:14 against API `http://localhost:8001` and console `http://localhost:8080` with `python scripts/security_check.py`.
Categories follow the external checks described by [ArgosX](https://getargosx.com): leaked secrets, database exposure, logged-out access, cross-account access control, cookies, security headers, CORS and TLS.

**35 passed, 0 failed, 4 informational.**

## All checks

| Result | Severity | Category | Check | Detail |
|---|---|---|---|---|
| PASS | critical | 1. Leaked secrets | No API keys in served pages or JS bundles | scanned 47,909 served + 728,051 bundled chars |
| PASS | critical | 1. Leaked secrets | Configured secrets never reach the browser | 3 configured secrets checked |
| PASS | high | 1. Leaked secrets | No .env, database or key files tracked in git |  |
| PASS | critical | 1. Leaked secrets | Configured secrets not committed to tracked files |  |
| PASS | high | 2. Database exposure | Neo4j Browser (:7474) not reachable from the network |  |
| PASS | high | 2. Database exposure | Neo4j Bolt (:7687) not reachable from the network |  |
| PASS | high | 2. Database exposure | AEGIS API (:8001) not reachable from the network |  |
| PASS | critical | 2. Database exposure | Neo4j rejects the default password (neo4j/password) | HTTP 401 with default credentials |
| PASS | critical | 2. Database exposure | Neo4j HTTP API requires credentials | HTTP 401 without credentials |
| PASS | critical | 2. Database exposure | SQLite stores and env files are not served |  |
| PASS | critical | 3. Logged-out access | Every protected route refuses signed-out callers (43 probed) |  |
| PASS | medium | 3. Logged-out access | Public health endpoint reveals no configuration secrets |  |
| info | low | 3. Logged-out access | Interactive API docs disabled in production | exposed (fine locally; set AEGIS_DOCS_ENABLED=0 when deployed) |
| PASS | info | 4. Access control (second account) | Low-privilege viewer can sign in and read |  |
| PASS | critical | 4. Access control (second account) | Viewer cannot perform admin or reviewer actions | 6 actions refused |
| PASS | high | 4. Access control (second account) | Cookie-authenticated write from a foreign origin is refused (CSRF) | HTTP 403 |
| PASS | info | 4. Access control (second account) | Temporary account removed | HTTP 200 |
| PASS | high | 5. Sessions & cookies | Session cookie is HttpOnly |  |
| PASS | medium | 5. Sessions & cookies | Session cookie is SameSite=Strict |  |
| PASS | low | 5. Sessions & cookies | Session cookie expires (Max-Age) |  |
| info | info | 5. Sessions & cookies | Session cookie is Secure | HTTP locally; the Secure flag is set automatically behind HTTPS |
| PASS | high | 5. Sessions & cookies | Logged-out session token can't be replayed | HTTP 401 |
| PASS | high | 5. Sessions & cookies | Forged session token is refused | HTTP 401 |
| PASS | medium | 6. Sign-in hardening | Same response for wrong password and unknown account | 401 vs 401 |
| PASS | high | 6. Sign-in hardening | Repeated failed sign-ins are rate limited | responses: [401, 401, 401, 401, 401, 429, 429] |
| PASS | medium | 7. Headers, CORS, TLS | API sends x-content-type-options | nosniff |
| PASS | medium | 7. Headers, CORS, TLS | API sends x-frame-options | DENY |
| PASS | medium | 7. Headers, CORS, TLS | API sends content-security-policy | default-src 'none'; frame-ancestors 'none' |
| PASS | low | 7. Headers, CORS, TLS | API sends referrer-policy | no-referrer |
| PASS | low | 7. Headers, CORS, TLS | API sends cache-control | no-store |
| PASS | low | 7. Headers, CORS, TLS | API hides its server software (no Server header) |  |
| PASS | medium | 7. Headers, CORS, TLS | Console sends x-content-type-options | nosniff |
| PASS | medium | 7. Headers, CORS, TLS | Console sends x-frame-options | DENY |
| PASS | low | 7. Headers, CORS, TLS | Console sends referrer-policy | strict-origin-when-cross-origin |
| PASS | medium | 7. Headers, CORS, TLS | Console sends a Content-Security-Policy | default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' http://localhost:8001; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none' |
| PASS | high | 7. Headers, CORS, TLS | CORS does not trust arbitrary origins |  |
| PASS | critical | 7. Headers, CORS, TLS | CORS never combines a wildcard with credentials |  |
| info | info | 7. Headers, CORS, TLS | API served over HTTPS with HSTS | local HTTP; deploy behind TLS (HSTS is sent automatically on HTTPS) |
| info | info | 7. Headers, CORS, TLS | Console served over HTTPS with HSTS | local HTTP; deploy behind TLS (HSTS is sent automatically on HTTPS) |

This is an automated outside-in check, not a penetration test or certification.
