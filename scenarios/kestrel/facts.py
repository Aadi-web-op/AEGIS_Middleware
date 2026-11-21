"""Lock Kestrel's key facts (Fact Lock) and, optionally, play the policy change.

    python scenarios/kestrel/facts.py                 # lock the facts (idempotent)
    python scenarios/kestrel/facts.py --change-leave  # casual leave 18 -> 12 days (2026 policy)

Values are the ones in force *before* the evaluator uploads the 2026 leave
policy, so the change shows which past answers stated the old 18 days.
Signs in with AEGIS_ADMIN_EMAIL / AEGIS_ADMIN_PASSWORD (start.ps1 loads them).
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import BY_KEY  # noqa: E402


def src(key: str) -> dict:
    doc = BY_KEY[key]
    return {"source": doc["source"], "version": doc["version"]}


FACTS = [
    dict(key="casual_leave", label="casual leave", kind="duration", value="18 days", level=2,
         aliases=["casual leaves"], **src("leave_2024")),
    dict(key="paternity_leave", label="paternity leave", kind="duration", value="5 days", level=2,
         **src("leave_2024")),
    dict(key="hotel_limit_metro", label="hotel limit metro", kind="money", value="Rs 7,500", level=3,
         aliases=["hotel limit mumbai", "hotel limit delhi", "hotel limit bengaluru"],
         **src("fin_circular")),
    dict(key="hotel_limit_other", label="hotel limit other cities", kind="money", value="Rs 4,000",
         level=1, aliases=["hotel limit non-metro"], **src("travel")),
    dict(key="expense_claim_deadline", label="expense claim deadline", kind="duration",
         value="15 days", level=2, aliases=["expense claims submitted", "submit expense claims"],
         **src("fin_circular")),
    dict(key="damage_claim_window", label="damage claim window", kind="duration", value="7 days",
         level=3, aliases=["damage claim", "damage claims raised"], **src("sla")),
    dict(key="liability_cap", label="liability cap", kind="money", value="Rs 50,000", level=4,
         aliases=["liability capped", "liability per consignment"], **src("sla")),
    dict(key="oda_surcharge", label="out of delivery area surcharge", kind="money", value="Rs 850",
         level=3, aliases=["oda surcharge", "out-of-delivery-area surcharge"], **src("rates_q4")),
    dict(key="data_request_response", label="personal data request response", kind="duration",
         value="30 days", level=4,
         aliases=["delete personal data", "access personal data", "data deletion request"],
         **src("privacy")),
    dict(key="password_min_length", label="minimum password length", kind="count",
         value="12 characters", unit="characters", level=1,
         aliases=["password length", "passwords characters"], **src("it_security")),
    dict(key="sum_insured", label="sum insured", kind="money", value="Rs 5 lakh", level=3,
         aliases=["floater sum insured", "medical cover"], **src("benefits")),
]

_jar = http.cookiejar.CookieJar()
_open = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar)).open


def call(api: str, path: str, body: dict | None = None, method: str = "GET"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api + path, data, method=method,
                                 headers={"Content-Type": "application/json"})
    with _open(req, timeout=60) as resp:
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8001")
    ap.add_argument("--change-leave", action="store_true",
                    help="apply the 2026 leave policy: casual leave 18 -> 12 days")
    args = ap.parse_args()
    email, password = os.environ.get("AEGIS_ADMIN_EMAIL"), os.environ.get("AEGIS_ADMIN_PASSWORD")
    if not email or not password:
        print("Set AEGIS_ADMIN_EMAIL and AEGIS_ADMIN_PASSWORD (scenarios/kestrel/.env.local).")
        return 1
    call(args.api, "/v1/auth/login", {"email": email, "password": password}, "POST")

    if args.change_leave:
        result = call(args.api, "/v1/facts/casual_leave",
                      {"value": "12 days", **src("leave_2026")}, "PUT")
        impact = result["impact"]
        print(f"casual leave: {result['previous']['value']} -> {result['current']['value']} "
              f"({result['current']['version']})")
        print(f"scanned {impact['scanned']} past answers: {impact['counts']}; "
              f"{impact['delivered_wrong']} wrong answer(s) were delivered")
        for item in impact["affected"]:
            print(f"  {item['request_id'][:8]}  {item['original_decision']:<8} stated "
                  f"{item['stated']:<8} {item['query']}")
        return 0

    locked = 0
    for fact in FACTS:
        try:
            call(args.api, "/v1/facts", fact, "POST")
            locked += 1
        except urllib.error.HTTPError as exc:
            if exc.code != 409:  # 409 = already locked
                print(f"{fact['key']}: HTTP {exc.code} {exc.read().decode()[:200]}")
    print(f"   {locked} new fact(s) locked, {len(FACTS) - locked} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
