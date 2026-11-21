"""Who may call what. Deny by default: every /v1 route needs a login unless
it is listed in PUBLIC, and unknown routes fall back to admin-only.

Roles: admin > reviewer > viewer for people; "service" for API keys used by
a company's chatbot to call /v1/evaluate and friends.
"""

from __future__ import annotations

from dataclasses import dataclass

PUBLIC = {
    ("GET", "/v1/health"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/logout"),
    ("GET", "/v1/auth/me"),  # the route itself answers 401 when signed out
}

PEOPLE = {"admin", "reviewer", "viewer"}

# First match wins: (method or "*", path prefix, allowed roles).
RULES: list[tuple[str, str, frozenset]] = [
    ("*", "/v1/auth/users", frozenset({"admin"})),
    ("POST", "/v1/evaluate", frozenset({"admin", "reviewer", "service"})),
    ("POST", "/v1/rag/ask", frozenset({"admin", "reviewer", "service"})),
    ("POST", "/v1/rag/ingest", frozenset({"admin", "service"})),
    ("POST", "/v1/escalations", frozenset({"admin", "reviewer", "service"})),
    ("PATCH", "/v1/escalations/", frozenset({"admin", "reviewer"})),
    ("PUT", "/v1/escalations/", frozenset({"admin", "reviewer"})),
    ("GET", "/v1/", frozenset(PEOPLE)),
]
DEFAULT_ROLES = frozenset({"admin"})


@dataclass(frozen=True)
class Principal:
    kind: str  # "user" | "service"
    role: str
    email: str | None = None


def required_roles(method: str, path: str) -> frozenset:
    for rule_method, prefix, roles in RULES:
        if rule_method in ("*", method) and path.startswith(prefix):
            return roles
    return DEFAULT_ROLES


def authorize(method: str, path: str, principal: Principal | None) -> int:
    """HTTP status to refuse with, or 0 when the call is allowed."""
    if not path.startswith("/v1/") or (method, path) in PUBLIC:
        return 0
    if principal is None:
        return 401
    return 0 if principal.role in required_roles(method, path) else 403
