"""ArgosX-style external security check of a running AEGIS deployment.

    python scripts/security_check.py [--api http://localhost:8001]
                                     [--console http://localhost:8080]
                                     [--env-file scenarios/kestrel/.env.local]
                                     [--report docs/security/SECURITY_CHECK.md]

Tests the running app from the outside, like https://getargosx.com does for
AI-built apps, across its categories:

  1. Leaked secrets       keys and passwords in served pages, bundles and git
  2. Database exposure    Neo4j / SQLite reachable or using default credentials
  3. Logged-out access    every API route probed without signing in
  4. Access control       a second, low-privilege account tries admin actions
  5. Sessions & cookies   cookie flags, logout, forged tokens
  6. Sign-in hardening    brute-force limit, account enumeration
  7. Headers, CORS, TLS   security headers, cross-origin rules, transport

Read-only apart from: creating and deleting one temporary viewer account,
and a few failed sign-ins with a throwaway email. Exit code 1 if any
critical or high check fails.
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.cookiejar
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EVIL_ORIGIN = "https://evil.example"

SECRET_PATTERNS = {
    # (?<![\w-]) stops CSS names such as "mask-linear-..." matching; real keys contain digits.
    "OpenAI key": r"(?<![\w-])sk-(?:proj-)?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}",
    "Anthropic key": r"(?<![\w-])sk-ant-[A-Za-z0-9_-]{20,}",
    "Groq key": r"gsk_[A-Za-z0-9]{20,}",
    "Stripe live key": r"sk_live_[A-Za-z0-9]{16,}",
    "SendGrid key": r"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",
    "AWS access key": r"AKIA[0-9A-Z]{16}",
    "Private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "AEGIS service key": r"aegis_sk_[A-Za-z0-9_-]{20,}",
}


@dataclass
class Check:
    category: str
    name: str
    severity: str          # critical | high | medium | low | info
    passed: bool | None    # None = informational / not applicable
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, category, name, severity, passed, detail=""):
        self.checks.append(Check(category, name, severity, passed, detail))
        mark = {True: "PASS", False: "FAIL", None: "INFO"}[passed]
        print(f"  [{mark}] {severity:8s} {name}" + (f" -- {detail}" if detail and passed is not True else ""))


class Http:
    """Tiny HTTP client with an optional cookie jar; never raises on status."""

    def __init__(self, jar: bool = False):
        self.jar = http.cookiejar.CookieJar() if jar else None
        handlers = [urllib.request.HTTPCookieProcessor(self.jar)] if jar else []
        self.opener = urllib.request.build_opener(*handlers)

    def cookie(self, name: str) -> str | None:
        return next((c.value for c in (self.jar or []) if c.name == name), None)

    def request(self, method, url, body=None, headers=None, raw=None):
        headers = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=60) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(), e.headers
        except (urllib.error.URLError, OSError) as e:
            return 0, {}, str(e).encode(), None


def load_env(path: Path) -> dict[str, str]:
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)=(.*)$", line)
            if m:
                values[m.group(1)] = m.group(2)
    return {**values, **{k: v for k, v in os.environ.items() if k.startswith(("AEGIS_", "NEO4J_"))}}


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            return None if ip.startswith("127.") else ip
    except OSError:
        return None


# --------------------------------------------------------------------------- checks
def check_secrets(rep: Report, console: str, env: dict):
    cat = "1. Leaked secrets"
    http_ = Http()
    status, _, html, _ = http_.request("GET", console + "/")
    served = html.decode("utf-8", "replace") if status == 200 else ""
    # Follow the scripts the page loads (dev server modules or built bundles), one level deep.
    for src in re.findall(r'<script[^>]+src="([^"]+)"', served)[:40]:
        url = src if src.startswith("http") else console + src
        if urlparse(url).netloc == urlparse(console).netloc:
            s, _, body, _ = http_.request("GET", url)
            if s == 200:
                served += "\n" + body.decode("utf-8", "replace")
    built = ROOT / "frontend" / ".output" / "public"
    bundle_text = ""
    if built.is_dir():
        for f in built.rglob("*.js"):
            bundle_text += f.read_text(encoding="utf-8", errors="replace")
    haystack = served + bundle_text
    found = [name for name, pat in SECRET_PATTERNS.items() if re.search(pat, haystack)]
    rep.add(cat, "No API keys in served pages or JS bundles", "critical", not found,
            ", ".join(found) or f"scanned {len(served):,} served + {len(bundle_text):,} bundled chars")

    configured = {k: v for k, v in env.items()
                  if k in ("AEGIS_ADMIN_PASSWORD", "NEO4J_PASSWORD", "GROQ_API_KEY") and len(v) >= 6}
    for key in (env.get("AEGIS_API_KEYS") or "").split(","):
        if key.strip():
            configured["AEGIS_API_KEYS"] = key.strip()
    leaked = [k for k, v in configured.items() if v in haystack]
    rep.add(cat, "Configured secrets never reach the browser", "critical", not leaked,
            ", ".join(leaked) or f"{len(configured)} configured secrets checked")

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    risky = [f for f in tracked if re.search(r"(^|/)\.env($|\.)", f) and not f.endswith(".env.example")
             or f.endswith((".db", ".pem", ".key"))]
    rep.add(cat, "No .env, database or key files tracked in git", "high", not risky, ", ".join(risky[:5]))
    in_git = []
    for k, v in configured.items():
        r = subprocess.run(["git", "grep", "-l", "-F", v], cwd=ROOT, capture_output=True, text=True)
        if r.stdout.strip():
            in_git.append(f"{k} in {r.stdout.split()[0]}")
    rep.add(cat, "Configured secrets not committed to tracked files", "critical", not in_git,
            "; ".join(in_git))


def check_database(rep: Report, api: str, env: dict):
    cat = "2. Database exposure"
    ip = lan_ip()
    for port, what in ((7474, "Neo4j Browser"), (7687, "Neo4j Bolt"), (8001, "AEGIS API")):
        if ip is None:
            rep.add(cat, f"{what} not reachable from the network", "high", None, "no LAN address to test from")
            continue
        exposed = port_open(ip, port)
        rep.add(cat, f"{what} (:{port}) not reachable from the network", "high", not exposed,
                f"reachable on {ip}:{port}" if exposed else "")
    status, _, _, _ = Http().request("GET", "http://localhost:7474/db/neo4j/tx/commit",
                                     headers={"Authorization": "Basic bmVvNGo6cGFzc3dvcmQ="})
    rep.add(cat, "Neo4j rejects the default password (neo4j/password)", "critical",
            status in (401, 403) or status == 0, f"HTTP {status} with default credentials")
    status, _, _, _ = Http().request("GET", "http://localhost:7474/db/neo4j/tx/commit")
    rep.add(cat, "Neo4j HTTP API requires credentials", "critical", status in (401, 403) or status == 0,
            f"HTTP {status} without credentials")
    leaked = [p for p in ("/audit.db", "/escalations.db", "/users.db", "/.env", "/.env.local")
              if Http().request("GET", api + p)[0] == 200]
    rep.add(cat, "SQLite stores and env files are not served", "critical", not leaked, ", ".join(leaked))


def check_logged_out(rep: Report, api: str):
    cat = "3. Logged-out access"
    status, _, body, _ = Http().request("GET", api + "/openapi.json")
    paths = json.loads(body).get("paths", {}) if status == 200 else {}
    public = {("GET", "/v1/health"), ("POST", "/v1/auth/login"), ("POST", "/v1/auth/logout"),
              ("GET", "/v1/auth/me")}
    open_routes, probed = [], 0
    for path, ops in paths.items():
        if not path.startswith("/v1/"):
            continue
        concrete = re.sub(r"\{[^}]+\}", "security-check-probe", path)
        for method in ops:
            m = method.upper()
            if (m, path) in public or m not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                continue
            probed += 1
            s, _, _, _ = Http().request(m, api + concrete, body={} if m != "GET" else None)
            if s != 401:
                open_routes.append(f"{m} {path} -> {s}")
    if not paths:
        rep.add(cat, "Route inventory available", "info", None, "openapi.json disabled; probing known routes")
        for m, p in (("GET", "/v1/decisions"), ("GET", "/v1/escalations"), ("POST", "/v1/evaluate"),
                     ("GET", "/v1/intelligence/summary"), ("POST", "/v1/rag/ingest")):
            probed += 1
            s = Http().request(m, api + p, body={} if m != "GET" else None)[0]
            if s != 401:
                open_routes.append(f"{m} {p} -> {s}")
    rep.add(cat, f"Every protected route refuses signed-out callers ({probed} probed)", "critical",
            not open_routes, "; ".join(open_routes[:6]))
    s, _, body, _ = Http().request("GET", api + "/v1/health")
    leaks = [w for w in ("password", "neo4j_uri", "bolt://", "api_key") if w in body.decode().lower()]
    rep.add(cat, "Public health endpoint reveals no configuration secrets", "medium", not leaks, ", ".join(leaks))
    s, _, _, _ = Http().request("GET", api + "/docs")
    rep.add(cat, "Interactive API docs disabled in production", "low", None,
            "exposed (fine locally; set AEGIS_DOCS_ENABLED=0 when deployed)" if s == 200 else "disabled")


def sign_in(api: str, email: str, password: str) -> tuple[Http, int, dict]:
    client = Http(jar=True)
    s, h, _, _ = client.request("POST", api + "/v1/auth/login", body={"email": email, "password": password},
                                headers={"Origin": "http://localhost:8080"})
    return client, s, h


def check_access_control(rep: Report, api: str, admin: Http | None):
    cat = "4. Access control (second account)"
    if admin is None:
        rep.add(cat, "Admin session available for role tests", "high", False, "admin sign-in failed")
        return
    email = f"security-check-{secrets.token_hex(4)}@example.com"
    password = "Sc!" + secrets.token_urlsafe(12) + "9a"
    s, _, body, _ = admin.request("POST", api + "/v1/auth/users",
                                  body={"email": email, "password": password, "role": "viewer"},
                                  headers={"Origin": "http://localhost:8080"})
    if s != 201:
        rep.add(cat, "Create temporary viewer account", "high", False, f"HTTP {s} {body[:120]!r}")
        return
    try:
        viewer, vs, _ = sign_in(api, email, password)
        rep.add(cat, "Low-privilege viewer can sign in and read", "info",
                vs == 200 and viewer.request("GET", api + "/v1/decisions")[0] == 200)
        attempts = {
            "evaluate (write a decision)": ("POST", "/v1/evaluate",
                                            {"query": "q?", "answer": "a.", "evidence": []}),
            "ingest a document": ("POST", "/v1/rag/ingest", {"pdf_path": "C:/Windows/win.ini"}),
            "resolve an escalation": ("PATCH", "/v1/escalations/security-check-probe",
                                      {"status": "resolved"}),
            "list users": ("GET", "/v1/auth/users", None),
            "create an admin": ("POST", "/v1/auth/users",
                                {"email": "evil@example.com", "password": "Evil-Passw0rd!", "role": "admin"}),
            "delete a user": ("DELETE", f"/v1/auth/users/{email}", None),
        }
        allowed = [name for name, (m, p, b) in attempts.items()
                   if viewer.request(m, api + p, body=b, headers={"Origin": "http://localhost:8080"})[0] != 403]
        rep.add(cat, "Viewer cannot perform admin or reviewer actions", "critical", not allowed,
                "allowed: " + ", ".join(allowed) if allowed else f"{len(attempts)} actions refused")
        s = viewer.request("POST", api + "/v1/evaluate", body={"query": "q", "answer": "a", "evidence": []},
                           headers={"Origin": EVIL_ORIGIN})[0]
        rep.add(cat, "Cookie-authenticated write from a foreign origin is refused (CSRF)", "high", s == 403,
                f"HTTP {s}")
    finally:
        s = admin.request("DELETE", api + f"/v1/auth/users/{email}", headers={"Origin": "http://localhost:8080"})[0]
        rep.add(cat, "Temporary account removed", "info", s == 200, f"HTTP {s}")


def check_sessions(rep: Report, api: str, email: str, password: str, login_headers: dict):
    cat = "5. Sessions & cookies"
    cookie = login_headers.get("set-cookie", "")
    low = cookie.lower()
    rep.add(cat, "Session cookie is HttpOnly", "high", "httponly" in low)
    rep.add(cat, "Session cookie is SameSite=Strict", "medium", "samesite=strict" in low)
    rep.add(cat, "Session cookie expires (Max-Age)", "low", "max-age=" in low)
    https = api.startswith("https://")
    rep.add(cat, "Session cookie is Secure", "high" if https else "info",
            ("secure" in low) if https else None,
            "" if https else "HTTP locally; the Secure flag is set automatically behind HTTPS")
    client, s, _ = sign_in(api, email, password)
    token = client.cookie("aegis_session") if s == 200 else None
    client.request("POST", api + "/v1/auth/logout", body={}, headers={"Origin": "http://localhost:8080"})
    replay = Http().request("GET", api + "/v1/decisions", headers={"Cookie": f"aegis_session={token}"})[0]
    rep.add(cat, "Logged-out session token can't be replayed", "high", token is not None and replay == 401,
            f"HTTP {replay}")
    forged = Http().request("GET", api + "/v1/decisions",
                            headers={"Cookie": "aegis_session=" + secrets.token_urlsafe(32)})[0]
    rep.add(cat, "Forged session token is refused", "high", forged == 401, f"HTTP {forged}")


def check_signin(rep: Report, api: str, admin_email: str):
    cat = "6. Sign-in hardening"
    ghost = f"nobody-{secrets.token_hex(3)}@example.com"
    a = Http().request("POST", api + "/v1/auth/login", body={"email": admin_email, "password": "Wrong-Pass-1!"})
    b = Http().request("POST", api + "/v1/auth/login", body={"email": ghost, "password": "Wrong-Pass-1!"})
    rep.add(cat, "Same response for wrong password and unknown account", "medium",
            a[0] == b[0] == 401 and a[2] == b[2], f"{a[0]} vs {b[0]}")
    target = f"bruteforce-{secrets.token_hex(3)}@example.com"
    codes = [Http().request("POST", api + "/v1/auth/login",
                            body={"email": target, "password": f"Guess-{i}-Pass!"})[0] for i in range(7)]
    rep.add(cat, "Repeated failed sign-ins are rate limited", "high", 429 in codes,
            f"responses: {codes}")


def check_headers(rep: Report, api: str, console: str):
    cat = "7. Headers, CORS, TLS"
    _, h, _, _ = Http().request("GET", api + "/v1/health")
    for name, sev in (("x-content-type-options", "medium"), ("x-frame-options", "medium"),
                      ("content-security-policy", "medium"), ("referrer-policy", "low"),
                      ("cache-control", "low")):
        rep.add(cat, f"API sends {name}", sev, name in h, h.get(name, "missing"))
    rep.add(cat, "API hides its server software (no Server header)", "low", "server" not in h,
            h.get("server", ""))
    s, ch, _, _ = Http().request("GET", console + "/")
    if s == 200:
        for name, sev in (("x-content-type-options", "medium"), ("x-frame-options", "medium"),
                          ("referrer-policy", "low")):
            rep.add(cat, f"Console sends {name}", sev, name in ch, ch.get(name, "missing"))
        rep.add(cat, "Console sends a Content-Security-Policy", "medium",
                True if "content-security-policy" in ch else None,
                ch.get("content-security-policy", "not on the dev server (Vite HMR); set by the "
                       "production worker in frontend/src/server.ts"))
    else:
        rep.add(cat, "Console reachable for header checks", "info", None, f"HTTP {s}")
    _, ev, _, _ = Http().request("GET", api + "/v1/health", headers={"Origin": EVIL_ORIGIN})
    acao = ev.get("access-control-allow-origin")
    rep.add(cat, "CORS does not trust arbitrary origins", "high", acao in (None, ""), acao or "")
    _, ok, _, _ = Http().request("OPTIONS", api + "/v1/decisions",
                                 headers={"Origin": "http://localhost:8080",
                                          "Access-Control-Request-Method": "GET"})
    rep.add(cat, "CORS never combines a wildcard with credentials", "critical",
            not (ok.get("access-control-allow-origin") == "*" and
                 ok.get("access-control-allow-credentials") == "true"))
    for name, url in (("API", api), ("Console", console)):
        https = url.startswith("https://")
        rep.add(cat, f"{name} served over HTTPS with HSTS", "high" if https else "info",
                ("strict-transport-security" in (h if name == "API" else ch)) if https else None,
                "" if https else "local HTTP; deploy behind TLS (HSTS is sent automatically on HTTPS)")


# --------------------------------------------------------------------------- report
def write_report(rep: Report, path: Path, api: str, console: str):
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    failed = [c for c in rep.checks if c.passed is False]
    passed = [c for c in rep.checks if c.passed is True]
    lines = [
        "# AEGIS security check",
        "",
        f"Run {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} against API `{api}` and console `{console}` "
        "with `python scripts/security_check.py`.",
        "Categories follow the external checks described by [ArgosX](https://getargosx.com): leaked "
        "secrets, database exposure, logged-out access, cross-account access control, cookies, "
        "security headers, CORS and TLS.",
        "",
        f"**{len(passed)} passed, {len(failed)} failed, "
        f"{len(rep.checks) - len(passed) - len(failed)} informational.**",
        "",
    ]
    if failed:
        lines += ["## Failed checks", "", "| Severity | Category | Check | Detail |", "|---|---|---|---|"]
        for c in sorted(failed, key=lambda c: order[c.severity]):
            lines.append(f"| {c.severity} | {c.category} | {c.name} | {c.detail} |")
        lines.append("")
    lines += ["## All checks", "", "| Result | Severity | Category | Check | Detail |", "|---|---|---|---|---|"]
    for c in rep.checks:
        mark = {True: "PASS", False: "**FAIL**", None: "info"}[c.passed]
        lines.append(f"| {mark} | {c.severity} | {c.category} | {c.name} | {c.detail.replace('|', '/')} |")
    lines += ["", "This is an automated outside-in check, not a penetration test or certification."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8001")
    ap.add_argument("--console", default="http://localhost:8080")
    ap.add_argument("--env-file", default=str(ROOT / "scenarios" / "kestrel" / ".env.local"))
    ap.add_argument("--report", default=str(ROOT / "docs" / "security" / "SECURITY_CHECK.md"))
    args = ap.parse_args()
    env = load_env(Path(args.env_file))
    email, password = env.get("AEGIS_ADMIN_EMAIL", ""), env.get("AEGIS_ADMIN_PASSWORD", "")
    rep = Report()

    if Http().request("GET", args.api + "/v1/health")[0] != 200:
        print(f"API not reachable at {args.api}")
        return 2
    print("1. Leaked secrets"); check_secrets(rep, args.console, env)
    print("2. Database exposure"); check_database(rep, args.api, env)
    print("3. Logged-out access"); check_logged_out(rep, args.api)
    admin, status, login_headers = sign_in(args.api, email, password) if email else (None, 0, {})
    print("4. Access control"); check_access_control(rep, args.api, admin if status == 200 else None)
    print("5. Sessions & cookies")
    if status == 200:
        check_sessions(rep, args.api, email, password, login_headers)
    else:
        rep.add("5. Sessions & cookies", "Admin sign-in works", "high", False, f"HTTP {status}")
    print("6. Sign-in hardening"); check_signin(rep, args.api, email or "admin@example.com")
    print("7. Headers, CORS, TLS"); check_headers(rep, args.api, args.console)

    write_report(rep, Path(args.report), args.api, args.console)
    failed = [c for c in rep.checks if c.passed is False]
    print(f"\n{sum(c.passed is True for c in rep.checks)} passed, {len(failed)} failed. Report: {args.report}")
    return 1 if any(c.severity in ("critical", "high") for c in failed) else 0


if __name__ == "__main__":
    sys.exit(main())
