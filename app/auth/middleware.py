"""ASGI middleware: authentication, authorisation and security headers.

Pure ASGI (not BaseHTTPMiddleware) so the SSE stream at /v1/graph/events is
not buffered.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from http.cookies import CookieError, SimpleCookie
from typing import Iterable

from app.auth.policy import Principal, authorize
from app.auth.store import UserStore

SESSION_COOKIE = "aegis_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def session_token(headers: dict[str, str]) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    try:
        jar = SimpleCookie()
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(SESSION_COOKIE)
    return morsel.value if morsel else None


async def _send_json(send, status: int, detail: str, extra: Iterable[tuple[bytes, bytes]] = ()):
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()), *extra]})
    await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    def __init__(self, app, store: UserStore, api_keys: Iterable[str], allowed_origins: Iterable[str]):
        self.app = app
        self.store = store
        self._key_hashes = [hashlib.sha256(k.encode()).digest() for k in api_keys if k]
        self.allowed_origins = set(allowed_origins)

    def _api_key_ok(self, key: str) -> bool:
        digest = hashlib.sha256(key.encode()).digest()
        return any(hmac.compare_digest(digest, h) for h in self._key_hashes)

    def principal(self, headers: dict[str, str]) -> tuple[Principal | None, bool]:
        """(principal, authenticated_by_cookie)."""
        key = headers.get("x-api-key")
        auth = headers.get("authorization", "")
        if not key and auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        if key:
            return (Principal("service", "service") if self._api_key_ok(key) else None), False
        token = session_token(headers)
        user = self.store.session_user(token) if token else None
        if user is None:
            return None, False
        return Principal("user", user.role, user.email), True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        headers = _headers(scope)
        principal, by_cookie = self.principal(headers)
        scope.setdefault("state", {})["principal"] = principal

        # CSRF defence in depth (SameSite=Strict already blocks cross-site
        # cookies): a cookie-authenticated write from a foreign origin is refused.
        origin = headers.get("origin")
        if by_cookie and method in UNSAFE_METHODS and origin and origin not in self.allowed_origins:
            return await _send_json(send, 403, "Cross-origin request refused.")

        status = authorize(method, path, principal)
        if status == 401:
            return await _send_json(send, 401, "Sign in required.",
                                    [(b"www-authenticate", b'Bearer realm="aegis"')])
        if status == 403:
            return await _send_json(send, 403, "You do not have permission for this action.")
        return await self.app(scope, receive, send)


API_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-site"),
]
API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware:
    def __init__(self, app, force_hsts: bool = False):
        self.app = app
        self.force_hsts = force_hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        https = scope.get("scheme") == "https" or \
            _headers(scope).get("x-forwarded-proto", "").lower() == "https"

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [h for h in API_HEADERS if h[0] not in existing]
                if not path.startswith(DOCS_PATHS) and API_CSP[0] not in existing:
                    extra.append(API_CSP)  # Swagger UI needs its CDN scripts
                if path.startswith("/v1/") and b"cache-control" not in existing:
                    extra.append((b"cache-control", b"no-store"))
                if https or self.force_hsts:
                    extra.append(HSTS)
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        return await self.app(scope, receive, send_with_headers)
