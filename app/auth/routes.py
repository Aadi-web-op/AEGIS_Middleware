"""Sign in, sign out, current user, and admin user management."""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.middleware import SESSION_COOKIE, session_token
from app.auth.passwords import password_problems
from app.auth.store import ROLES, SESSION_HOURS

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class NewUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=256)
    role: str = Field(default="viewer")


def _store(request: Request):
    store = getattr(request.app.state, "user_store", None)
    if store is None:
        raise HTTPException(status_code=404, detail="Authentication is disabled on this server.")
    return store


def _secure_cookie(request: Request) -> bool:
    mode = os.environ.get("AEGIS_COOKIE_SECURE", "auto").lower()
    if mode in ("1", "true", "yes"):
        return True
    if mode in ("0", "false", "no"):
        return False
    return request.url.scheme == "https" or \
        request.headers.get("x-forwarded-proto", "").lower() == "https"


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    store = _store(request)
    limiter = request.app.state.login_limiter
    client = request.client.host if request.client else "unknown"
    email = payload.email.strip().lower()
    wait = limiter.retry_after(client, email)
    if wait:
        return JSONResponse(status_code=429, headers={"Retry-After": str(wait)},
                            content={"detail": "Too many failed sign-in attempts. Try again later."})
    user = store.authenticate(email, payload.password)
    if user is None:
        limiter.failed(client, email)
        # Same message for unknown email and wrong password (no account enumeration).
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    limiter.succeeded(client, email)
    response.set_cookie(
        SESSION_COOKIE, store.create_session(user), max_age=SESSION_HOURS * 3600,
        httponly=True, samesite="strict", secure=_secure_cookie(request), path="/",
    )
    return {"email": user.email, "role": user.role}


@router.post("/logout")
def logout(request: Request, response: Response):
    store = getattr(request.app.state, "user_store", None)
    token = session_token({k.lower(): v for k, v in request.headers.items()})
    if store is not None and token:
        store.delete_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return {"signed_out": True}


@router.get("/me")
def me(request: Request):
    if getattr(request.app.state, "user_store", None) is None:
        return {"auth_enabled": False, "email": None, "role": "admin"}
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return {"auth_enabled": True, "email": principal.email, "role": principal.role,
            "kind": principal.kind}


@router.get("/users")
def list_users(request: Request):
    return [{"id": u.id, "email": u.email, "role": u.role} for u in _store(request).list_users()]


@router.post("/users", status_code=201)
def create_user(payload: NewUserRequest, request: Request):
    store = _store(request)
    if payload.role not in ROLES:
        raise HTTPException(status_code=422, detail=f"Role must be one of: {', '.join(ROLES)}.")
    problems = password_problems(payload.password)
    if problems:
        raise HTTPException(status_code=422, detail="Password needs " + ", ".join(problems) + ".")
    try:
        user = store.create_user(payload.email, payload.password, payload.role)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    return {"id": user.id, "email": user.email, "role": user.role}


@router.delete("/users/{email}")
def delete_user(email: str, request: Request):
    store = _store(request)
    principal = getattr(request.state, "principal", None)
    if principal is not None and principal.email == email.strip().lower():
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    if not store.delete_user(email):
        raise HTTPException(status_code=404, detail="No such user.")
    return {"deleted": email.strip().lower()}
