"""Authentication and authorisation for the AEGIS API."""

from __future__ import annotations

import logging
import os

from app.auth.middleware import AuthMiddleware, SecurityHeadersMiddleware
from app.auth.passwords import password_problems
from app.auth.ratelimit import LoginLimiter
from app.auth.routes import router as auth_router
from app.auth.store import UserStore

logger = logging.getLogger(__name__)

__all__ = ["AuthMiddleware", "SecurityHeadersMiddleware", "LoginLimiter", "UserStore",
           "auth_router", "auth_enabled_from_env", "api_keys_from_env", "ensure_admin"]


def auth_enabled_from_env() -> bool:
    return os.environ.get("AEGIS_AUTH_ENABLED", "1").lower() not in ("0", "false", "no")


def api_keys_from_env() -> list[str]:
    return [k.strip() for k in os.environ.get("AEGIS_API_KEYS", "").split(",") if k.strip()]


def ensure_admin(store: UserStore) -> None:
    """Create the admin from AEGIS_ADMIN_EMAIL / AEGIS_ADMIN_PASSWORD if missing.

    The password is only ever read from the environment and stored hashed.
    Set AEGIS_ADMIN_RESET=1 to overwrite an existing admin's password.
    """
    email = os.environ.get("AEGIS_ADMIN_EMAIL", "").strip()
    password = os.environ.get("AEGIS_ADMIN_PASSWORD", "")
    if not email or not password:
        if not store.list_users():
            logger.warning("Auth is on but no users exist: set AEGIS_ADMIN_EMAIL and "
                           "AEGIS_ADMIN_PASSWORD to create the first admin.")
        return
    problems = password_problems(password)
    if problems:
        logger.error("AEGIS_ADMIN_PASSWORD is too weak (needs %s); admin not created.",
                     ", ".join(problems))
        return
    existing = store.get(email)
    if existing is None:
        store.create_user(email, password, "admin")
        logger.info("Created admin account %s", email)
    elif os.environ.get("AEGIS_ADMIN_RESET") == "1":
        store.set_password(email, password)
        logger.info("Reset password for admin account %s", email)
