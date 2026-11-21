"""Replay three weeks of Kestrel Assist traffic through AEGIS.

    python scenarios/kestrel/traffic.py [--api http://127.0.0.1:8001]

This plays the company's own chatbot. In a real deployment Kestrel's
assistant has its own retriever and LLM; before an answer reaches the
employee or customer, it calls AEGIS:

    POST /v1/evaluate {query, answer, evidence[{text, source, version, date,
                       document_content_hash}], profile, time_sensitive}

Each interaction below is what the bot retrieved and what it answered,
including the usual failure modes: answers from an outdated version,
invented numbers, two documents that disagree, vague questions, and
questions no document covers. Evidence carries the same content hash the
ingested PDF has, so the decisions attach to the same Document nodes in
Neo4j as the live knowledge base.
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from app.graph.identity import content_hash  # noqa: E402
from app.ingestion.loader import load_pdf  # noqa: E402
from corpus import BY_KEY, doc_text_lines  # noqa: E402


def pdf_path(doc: dict) -> Path:
    return HERE / "docs" / ("" if doc["preload"] else "to-upload") / doc["file"]


_HASHES: dict[str, str] = {}


def passage(key: str, *lines: str) -> dict:
    """One retrieved passage: sentences from one document, with its metadata."""
    doc = BY_KEY[key]
    known = doc_text_lines(doc)
    for line in lines:
        if not any(line in k for k in known):
            raise ValueError(f"{key}: passage text not in document: {line!r}")
    if key not in _HASHES:
        _HASHES[key] = content_hash(load_pdf(str(pdf_path(doc))))
    return {"text": " ".join(lines), "source": doc["source"], "version": doc["version"],
            "date": doc["date"], "document_content_hash": _HASHES[key]}


HR, FIN, IT, CS = "HR helpdesk", "Finance helpdesk", "IT helpdesk", "Customer support"

# (channel, profile, time_sensitive, question, bot answer, evidence, expected, why)
TRAFFIC = [
    # ---------------------------------------------------------- HR: leave (old policy in the KB)
    (HR, "standard", False, "How many casual leaves do I get in a year?",
     "You get 18 days of casual leave per calendar year, and unused casual leave can be carried forward for up to 6 months.",
     [passage("leave_2024", "Employees are entitled to 18 days of casual leave per calendar year.",
              "Unused casual leave may be carried forward for up to 6 months into the next year."),
      passage("handbook", "Employees get 18 days of casual leave every year")],
     "ANSWER", "Correct against the KB -- but the KB still has the 2024 policy"),
    (HR, "standard", False, "How many casual leave days do employees get per year?",
     "Employees get 18 casual leave days per year.",
     [passage("leave_2024", "Employees are entitled to 18 days of casual leave per calendar year.")],
     "ANSWER", "Same FAQ, another employee"),
    (HR, "standard", False, "Can I carry forward my unused casual leave to next year?",
     "Yes, unused casual leave can be carried forward for up to 6 months into the next year.",
     [passage("leave_2024", "Unused casual leave may be carried forward for up to 6 months into the next year.")],
     "ANSWER", "Will become wrong when the 2026 policy lands"),
    (HR, "standard", False, "How many days of paternity leave are allowed?",
     "Male employees get 5 days of paternity leave, to be taken within 3 months of the birth or adoption of a child.",
     [passage("leave_2024", "Male employees are entitled to 5 days of paternity leave, to be taken within "
              "3 months of the birth or adoption of a child.")],
     "ANSWER", "Will become wrong when the 2026 policy lands"),
    (HR, "standard", False, "How many days in advance must I apply for leave?",
     "Apply on the PeopleDesk HRMS at least 3 working days in advance, except for sick leave and emergencies.",
     [passage("leave_2024", "Leave must be applied for on the PeopleDesk HRMS at least 3 working days in "
              "advance, except for sick leave and emergencies.")],
     "ANSWER", ""),
    # ---------------------------------------------------------- HR: other
    (HR, "standard", False, "How long is the probation period for new joiners?",
     "The probation period is 6 months from the date of joining.",
     [passage("handbook", "New employees serve a probation period of 6 months from the date of joining."),
      passage("leave_2024", "Probation lasts three months from the date of joining.")],
     "ESCALATE", "Handbook says 6 months, leave policy says 3"),
    (HR, "standard", False, "What is the notice period after confirmation?",
     "The notice period is 60 days for confirmed employees.",
     [passage("handbook", "The notice period is 60 days for confirmed employees and 30 days during probation.")],
     "ANSWER", ""),
    (HR, "standard", False, "How many days can I work from home each week?",
     "You can work from home for up to 2 days per week with approval from your reporting manager.",
     [passage("wfh", "Corporate office employees may work from home for up to 2 days per week with "
              "approval from their reporting manager.")],
     "ANSWER", ""),
    (HR, "standard", False, "Can warehouse supervisors work from home?",
     "No. Work from home is not available to warehouse, fleet and branch operations roles.",
     [passage("wfh", "Work from home is not available to warehouse, fleet and branch operations roles, "
              "or to employees in their first 3 months of service.")],
     "ANSWER", ""),
    (HR, "standard", False, "Can I carry forward unused work from home days to the next week?",
     "Yes, unused work from home days can be carried forward to the following week.",
     [passage("wfh", "Corporate office employees may work from home for up to 2 days per week with "
              "approval from their reporting manager.")],
     "CAVEAT|ESCALATE", "The bot invented a carry-forward rule"),
    (HR, "standard", False, "Are my parents covered under the company health insurance?",
     "Parents are not covered by default, but you can add them through an optional top-up, with the premium deducted from your salary.",
     [passage("benefits", "The policy covers the employee, spouse and up to 2 children. Parents can be added "
              "through an optional top-up, with the premium deducted from salary.")],
     "ANSWER", ""),
    (HR, "standard", False, "What is the maternity cover under the group health insurance?",
     "Maternity expenses are covered up to Rs 75,000 per delivery.",
     [passage("benefits", "Maternity expenses are covered up to Rs 75,000 per delivery.")],
     "ANSWER", ""),
    (HR, "standard", False, "What is the sum insured under the group medical policy?",
     "The group medical policy has a family floater sum insured of Rs 10 lakh per year.",
     [passage("benefits", "All permanent employees are covered under a group medical policy with a family "
              "floater sum insured of Rs 5 lakh per year.")],
     "ESCALATE", "Invented number: 10 lakh vs 5 lakh"),
    # ---------------------------------------------------------- Finance
    (FIN, "standard", False, "What is the hotel limit per night in Mumbai?",
     "The hotel limit in metro cities like Mumbai is Rs 6,000 per night.",
     [passage("travel", "The hotel limit is Rs 6,000 per night in metro cities and Rs 4,000 per night in other cities."),
      passage("fin_circular", "With effect from 15 October 2026, the hotel limit in metro cities is revised to "
              "Rs 7,500 per night.")],
     "ESCALATE", "Policy says 6,000, the October circular says 7,500"),
    (FIN, "standard", False, "What is the hotel limit per night in metro cities?",
     "The hotel limit in metro cities is Rs 6,000 per night.",
     [passage("travel", "The hotel limit is Rs 6,000 per night in metro cities and Rs 4,000 per night in other cities."),
      passage("fin_circular", "With effect from 15 October 2026, the hotel limit in metro cities is revised to "
              "Rs 7,500 per night.")],
     "ESCALATE", "Same conflict, second employee"),
    (FIN, "standard", False, "Within how many days must I submit my travel expense claim?",
     "Expense claims must be submitted on ExpenseHub within 30 days of the end of the trip.",
     [passage("travel", "Expense claims must be submitted on ExpenseHub within 30 days of the end of the trip."),
      passage("fin_circular", "Expense claims must now be submitted within 15 days of the end of the trip.")],
     "ESCALATE", "30 days vs 15 days"),
    (FIN, "standard", False, "What is the daily allowance in metro cities?",
     "The daily allowance is Rs 1,200 per day in metro cities.",
     [passage("travel", "The daily allowance is Rs 1,200 per day in metro cities and Rs 800 per day elsewhere.")],
     "ANSWER", ""),
    (FIN, "standard", False, "Do I need original receipts for expenses?",
     "Original receipts are required for every expense above Rs 500.",
     [passage("travel", "Original receipts are required for every expense above Rs 500.")],
     "ANSWER", ""),
    (FIN, "standard", False, "Can I fly business class for a work trip to Delhi?",
     "No. Only economy class air travel is allowed, for journeys over 500 km.",
     [passage("travel", "Economy class air travel is allowed for journeys over 500 km.")],
     "ANSWER|CAVEAT", ""),
    # ---------------------------------------------------------- IT (internal FAQ: lenient)
    (IT, "lenient", False, "How often do I have to change my password?",
     "Passwords must be changed every 90 days and must be at least 12 characters long.",
     [passage("it_security", "Passwords must be at least 12 characters long and must be changed every 90 days.")],
     "ANSWER", ""),
    (IT, "lenient", False, "Can I use a USB pen drive on my company laptop?",
     "No. USB storage devices are blocked on all company laptops; exceptions need written approval from the IT Security team.",
     [passage("it_security", "USB storage devices are blocked on all company laptops. Exceptions need written "
              "approval from the IT Security team.")],
     "ANSWER", ""),
    (IT, "lenient", False, "I received a suspicious phishing email. What should I do?",
     "Report it to security@kestrel.example within 1 hour using the Report Phish button in Outlook.",
     [passage("it_security", "Suspected phishing emails must be reported to security@kestrel.example within "
              "1 hour, using the Report Phish button in Outlook.")],
     "ANSWER", ""),
    (IT, "lenient", False, "How often are company laptops replaced?",
     "Company laptops are refreshed every 4 years.",
     [passage("it_catalog", "Company laptops are refreshed every 4 years.")],
     "ANSWER", ""),
    (IT, "lenient", False, "What is the resolution time for a priority 1 incident?",
     "Priority 1 incidents get a response within 30 minutes and a resolution target of 4 hours.",
     [passage("it_catalog", "Priority 1 incidents, such as a site-wide outage, get a response within 30 minutes "
              "and a resolution target of 4 hours.")],
     "ANSWER", ""),
    # ---------------------------------------------------------- Customer support (customer-facing: strict)
    (CS, "strict", False, "How many days does a customer have to raise a damage claim?",
     "Damage claims must be raised within 7 days of delivery, with photographs of the package and the proof of delivery.",
     [passage("sla", "Damage claims must be raised within 7 days of delivery, with photographs of the "
              "package and the proof of delivery.")],
     "ANSWER|CAVEAT", ""),
    (CS, "strict", False, "A customer received a damaged parcel 10 days ago. Can they still claim a refund?",
     "Yes, the customer can still claim a full refund for the damaged parcel.",
     [passage("sla", "Damage claims must be raised within 7 days of delivery, with photographs of the "
              "package and the proof of delivery.")],
     "ESCALATE", "The 7-day window has passed"),
    (CS, "strict", False, "What is our liability for a damaged consignment worth Rs 2 lakh without insurance?",
     "Kestrel will reimburse the full declared value of Rs 2 lakh.",
     [passage("sla", "Kestrel's liability is capped at Rs 50,000 per consignment unless the customer has "
              "bought transit insurance.")],
     "ESCALATE", "Liability is capped at Rs 50,000"),
    (CS, "standard", True, "What is the current fuel surcharge?",
     "The fuel surcharge is 12% of the freight charge.",
     [passage("rates_q4", "The fuel surcharge is 12% of the freight charge.")],
     "ANSWER|CAVEAT", "Q4 rate card"),
    (CS, "standard", True, "What is the current fuel surcharge on freight?",
     "The fuel surcharge is 9% of the freight charge.",
     [passage("rates_q3", "The fuel surcharge is 9% of the freight charge.")],
     "CAVEAT", "Retriever picked the superseded Q3 rate card"),
    (CS, "standard", True, "What is the cash on delivery fee?",
     "The cash-on-delivery fee is Rs 40 or 1.5% of the collected amount, whichever is higher.",
     [passage("rates_q3", "The cash-on-delivery fee is Rs 40 or 1.5% of the collected amount, whichever is higher."),
      passage("rates_q4", "The cash-on-delivery fee is Rs 45 or 2% of the collected amount, whichever is higher.")],
     "ESCALATE", "Q3 and Q4 rate cards disagree"),
    (CS, "strict", False, "How long is warehouse CCTV footage kept?",
     "Warehouse CCTV footage is retained for 90 days and then deleted.",
     [passage("privacy", "Warehouse CCTV footage is retained for 90 days and then deleted.")],
     "ANSWER|CAVEAT", ""),
    (CS, "strict", False, "A customer wants their personal data deleted. How long do we have to respond?",
     "Customer requests to delete personal data must be answered within 30 days, in line with the DPDP Act, 2023.",
     [passage("privacy", "Customer requests to access or delete personal data are answered within 30 days, "
              "in line with the Digital Personal Data Protection Act, 2023.")],
     "ANSWER|CAVEAT", ""),
    # ---------------------------------------------------------- vague questions
    (IT, "standard", False, "Is it approved?",
     "Yes, it has been approved.",
     [passage("it_catalog", "New laptops, software and access requests are raised on the ServiceDesk portal "
              "and need reporting manager approval.")],
     "ESCALATE", "What is 'it'?"),
    (FIN, "standard", False, "What's the limit?",
     "The limit is Rs 6,000.",
     [passage("travel", "The hotel limit is Rs 6,000 per night in metro cities and Rs 4,000 per night in other cities.")],
     "ESCALATE", "Which limit?"),
    # ---------------------------------------------------------- knowledge gaps (no document covers these)
    (HR, "standard", False, "What is the employee referral bonus?",
     "The employee referral bonus is Rs 25,000 per successful hire.",
     [passage("handbook", "The notice period is 60 days for confirmed employees and 30 days during probation.")],
     "ABSTAIN|ESCALATE", "No referral policy in the KB"),
    (HR, "standard", False, "What is the employee referral bonus?",
     "You get a referral bonus of Rs 20,000 after the new hire completes probation.",
     [passage("handbook", "New employees serve a probation period of 6 months from the date of joining.")],
     "ABSTAIN|ESCALATE", "Asked again by someone else"),
    (HR, "standard", False, "How is gratuity calculated when I leave?",
     "Gratuity is 15 days of salary for every completed year of service.",
     [passage("handbook", "The notice period is 60 days for confirmed employees and 30 days during probation.")],
     "ABSTAIN|ESCALATE", "No gratuity document"),
    (HR, "standard", False, "How is gratuity calculated when I leave?",
     "Gratuity is paid as one month's salary per year of service.",
     [passage("leave_2024", "Employees earn 15 days of earned leave per year, credited monthly.")],
     "ABSTAIN|ESCALATE", "Asked again"),
    (HR, "standard", False, "What is the night shift allowance for warehouse staff?",
     "Warehouse staff get a night shift allowance of Rs 300 per night.",
     [passage("handbook", "Standard office hours are 9:30 AM to 6:30 PM, Monday to Friday.")],
     "ABSTAIN|ESCALATE", "No allowance document"),
    (HR, "standard", False, "What is the night shift allowance for warehouse staff?",
     "The night shift allowance is Rs 250 per shift.",
     [passage("handbook", "Warehouse and operations staff follow the shift roster published by their branch manager.")],
     "ABSTAIN|ESCALATE", "Asked again"),
]

# A human reviewer has already worked two escalations; the rest stay pending.
REVIEWS = {
    "What is the hotel limit per night in Mumbai?": (
        "resolved", "Finance confirmed circular FIN/2026/07 applies: Rs 7,500 per night in metros. "
        "Employee informed; KB article to be updated."),
    "What is the sum insured under the group medical policy?": (
        "in_review", "HR checking the bot's 'Rs 10 lakh' answer; the 2026 benefits document says Rs 5 lakh."),
}


# Kestrel's chatbot authenticates with a service API key; the human reviewer
# signs in with the admin account (session cookie).
SERVICE_KEY = (os.environ.get("AEGIS_API_KEYS", "").split(",") or [""])[0].strip()
_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _call(api: str, path: str, body: dict | None = None, method: str = "GET",
          service: bool = False):
    headers = {"Content-Type": "application/json"}
    if service and SERVICE_KEY:
        headers["X-API-Key"] = SERVICE_KEY
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api + path, data, method=method, headers=headers)
    with _opener.open(req, timeout=300) as resp:
        return json.load(resp)


def post(api: str, path: str, body: dict, method: str = "POST") -> dict:
    return _call(api, path, body, method, service=(path == "/v1/evaluate"))


def get(api: str, path: str):
    return _call(api, path)


def sign_in_reviewer(api: str) -> bool:
    email, password = os.environ.get("AEGIS_ADMIN_EMAIL"), os.environ.get("AEGIS_ADMIN_PASSWORD")
    if not email or not password:
        return False
    try:
        _call(api, "/v1/auth/login", {"email": email, "password": password}, "POST")
        return True
    except urllib.error.HTTPError as exc:
        print(f"Reviewer sign-in failed ({exc.code}); skipping review actions.")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8001")
    args = ap.parse_args()

    results = []
    print(f"Replaying {len(TRAFFIC)} Kestrel Assist interactions through {args.api}\n")
    for i, (channel, profile, ts, q, a, ev, expected, why) in enumerate(TRAFFIC, 1):
        r = post(args.api, "/v1/evaluate", {"query": q, "answer": a, "evidence": ev,
                                            "profile": profile, "time_sensitive": ts})
        ok = r["decision"] in expected.split("|")
        results.append((q, r))
        codes = ",".join(dict.fromkeys(x["code"] for x in r.get("reasons", [])))
        print(f"{i:2d}. [{channel:16s}] {r['decision']:8s} {'ok ' if ok else 'XX '} "
              f"{q[:62]:62s} {codes}")

    # Human review on two escalations.
    by_query = {q: r for q, r in results}
    escalations = get(args.api, "/v1/escalations?limit=500") if sign_in_reviewer(args.api) else []
    for q, (status, notes) in REVIEWS.items():
        rid = by_query.get(q, {}).get("request_id")
        match = next((e for e in escalations if e["request_id"] == rid), None)
        if match:
            post(args.api, f"/v1/escalations/{match['escalation_id']}",
                 {"status": status, "notes": notes}, method="PATCH")
    counts: dict[str, int] = {}
    for _, r in results:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    print("\nDecisions:", counts)
    mism = sum(1 for (c, p, ts, q, a, ev, exp, why), (_, r) in zip(TRAFFIC, results)
               if r["decision"] not in exp.split("|"))
    print(f"Matched expectations: {len(TRAFFIC) - mism}/{len(TRAFFIC)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
