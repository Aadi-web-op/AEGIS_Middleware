"""Synthetic HR policy cases for seeding the Aegis Decision Graph.

Provides 35 realistic, diverse HR request scenarios designed to populate
Neo4j with cross-decision relationships:
- Shared documents (hr-policy.pdf, staff-handbook.pdf, remote-work-policy.pdf, etc.)
- Conflicting versions (numeric and date mismatches between policy versions)
- Outdated document retrievals (superseded versions)
- Unanswered knowledge-base gaps (ABSTAIN topics)
- Multi-document escalations with shared root causes

Matches the specification in "AEGIS Finale Plan: Decisions & Task Split" (Nov 17, 2026):
"Seed data: 30 to 50 synthetic requests over the existing HR documents, so the graph
and Insights have something to show."
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from app.schemas import EvaluateRequest

TODAY = datetime.date.today()
DATE_2023 = datetime.date(2023, 4, 1)
DATE_2024 = datetime.date(2024, 4, 1)
DATE_2025 = datetime.date(2025, 1, 15)


def _case(
    name: str,
    query: str,
    answer: str,
    evidence: List[Dict[str, Any]],
    expected_decision: str,
    expected_reason: str,
    split: str = "dev",
    failure_type: str = "NONE",
) -> Dict[str, Any]:
    return {
        "name": name,
        "request": EvaluateRequest(
            query=query,
            answer=answer,
            evidence=evidence,
        ),
        "expected_decision": expected_decision,
        "expected_reason": expected_reason,
        "split": split,
        "failure_type": failure_type,
    }


SYNTHETIC_HR_CASES: List[Dict[str, Any]] = [
    # --- 1. Casual Leave & Disagreements (hr-policy.pdf) --------------------
    _case(
        name="hr_casual_leave_safe_2024",
        query="How many casual leaves are full-time employees entitled to under the current policy?",
        answer="Full-time employees receive 18 casual leaves per year.",
        evidence=[
            {
                "text": "Full-time employees are entitled to 18 casual leaves per year.",
                "source": "hr-policy.pdf",
                "version": "2024.2",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Backed by current 2024 policy document.",
    ),
    _case(
        name="hr_casual_leave_conflict_12_vs_18",
        query="Can I take 18 casual leaves this calendar year?",
        answer="Employees receive 18 casual leaves according to policy.",
        evidence=[
            {
                "text": "Full-time employees are entitled to 18 casual leaves per year.",
                "source": "hr-policy.pdf",
                "version": "2024.2",
                "date": DATE_2024,
            },
            {
                "text": "Employees are entitled to 12 casual leaves per year.",
                "source": "hr-policy.pdf",
                "version": "2023.1",
                "date": DATE_2023,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Numeric conflict between policy versions (18 vs 12).",
        failure_type="CONTRADICTION",
    ),
    _case(
        name="hr_casual_leave_carryforward_safe",
        query="Can unused casual leaves be carried forward to next year?",
        answer="Up to 5 unused casual leaves can be carried forward into the next calendar year.",
        evidence=[
            {
                "text": "A maximum of 5 unused casual leaves may be carried forward into the subsequent calendar year.",
                "source": "hr-policy.pdf",
                "version": "2024.2",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Directly entails the carryforward limit.",
    ),
    _case(
        name="hr_casual_leave_encashment_unsupported",
        query="Can I encash my unused casual leaves at the end of the year?",
        answer="Casual leaves can be encashed for full basic pay at year end.",
        evidence=[
            {
                "text": "Casual leave cannot be encashed at any time during or upon termination of employment.",
                "source": "hr-policy.pdf",
                "version": "2024.2",
                "date": DATE_2024,
            }
        ],
        expected_decision="ESCALATE",
        expected_reason="Claim of encashment directly contradicts non-encashment policy.",
        failure_type="CONTRADICTION",
    ),

    # --- 2. Probation Period & Confirmation (staff-handbook.pdf) -----------
    _case(
        name="staff_probation_duration_safe",
        query="What is the standard probation period for new joiners?",
        answer="The standard probation period is 3 months from joining date.",
        evidence=[
            {
                "text": "The standard probationary period for all new hires is 3 months.",
                "source": "staff-handbook.pdf",
                "version": "7.0",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Matches staff handbook specification.",
    ),
    _case(
        name="staff_probation_conflict_3_vs_6",
        query="Is the probation period 3 months or 6 months?",
        answer="The probation period is 3 months for all regular employees.",
        evidence=[
            {
                "text": "The probationary period for all regular employees is 3 months.",
                "source": "staff-handbook.pdf",
                "version": "7.0",
                "date": DATE_2024,
            },
            {
                "text": "All new appointments are subject to a 6-month probationary review.",
                "source": "staff-handbook.pdf",
                "version": "6.0",
                "date": DATE_2023,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Conflict between handbook versions 6.0 and 7.0 (6 vs 3 months).",
        failure_type="CONTRADICTION",
    ),
    _case(
        name="staff_probation_extension_caveat",
        query="Can probation be extended if performance targets are missed?",
        answer="Probation can be extended by 3 months with written feedback and performance metrics.",
        evidence=[
            {
                "text": "Management reserves the right to extend probation by up to 3 months upon written notice.",
                "source": "staff-handbook.pdf",
                "version": "7.0",
                "date": DATE_2024,
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="Evidence mentions written notice but misses detailed performance metrics claim.",
        failure_type="UNSUPPORTED_CLAIM",
    ),

    # --- 3. Remote Work & Equipment Allowance (remote-work-policy.pdf) ------
    _case(
        name="remote_work_allowance_conflict_500_vs_1000",
        query="What is the one-time home office setup allowance?",
        answer="Employees are eligible for a $1,000 home office setup allowance.",
        evidence=[
            {
                "text": "A one-time home office allowance of $1000 is provided to eligible remote staff.",
                "source": "remote-work-policy.pdf",
                "version": "2.0",
                "date": DATE_2024,
            },
            {
                "text": "Eligible employees receive a $500 home office equipment subsidy upon approval.",
                "source": "remote-work-policy.pdf",
                "version": "1.0",
                "date": DATE_2023,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Contradicting allowance amounts ($1000 vs $500).",
        failure_type="CONTRADICTION",
    ),
    _case(
        name="remote_work_days_per_week_safe",
        query="How many days per week are hybrid employees required to be in the office?",
        answer="Hybrid employees must work from the office at least 2 days per week.",
        evidence=[
            {
                "text": "Hybrid employees are required to work on-site at the designated office at least 2 days per week.",
                "source": "remote-work-policy.pdf",
                "version": "2.0",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Directly backed by remote work policy v2.0.",
    ),
    _case(
        name="remote_work_ergonomic_chair_caveat",
        query="Will company reimburse ergonomic chair purchases up to $400?",
        answer="The company reimburses ergonomic chair purchases up to $400 under the home office program.",
        evidence=[
            {
                "text": "The one-time home office allowance covers ergonomic chairs, monitors, and desks.",
                "source": "remote-work-policy.pdf",
                "version": "2.0",
                "date": DATE_2024,
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="Allowed items include ergonomic chair but exact $400 cap is unsupported.",
        failure_type="UNSUPPORTED_CLAIM",
    ),

    # --- 4. Travel & Expense Per Diem (travel-expense-policy.pdf) -----------
    _case(
        name="travel_per_diem_conflict_60_vs_85",
        query="What is the daily domestic travel meal allowance?",
        answer="The daily domestic meal per diem is $85 per day.",
        evidence=[
            {
                "text": "Domestic travel per diem meal allowance is fixed at $85 per day.",
                "source": "travel-expense-policy.pdf",
                "version": "2024.1",
                "date": DATE_2024,
            },
            {
                "text": "Domestic travel per diem meal allowance is $60 per day.",
                "source": "travel-expense-policy.pdf",
                "version": "2023.2",
                "date": DATE_2023,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Per diem conflict between 2023 and 2024 policies ($85 vs $60).",
        failure_type="CONTRADICTION",
    ),
    _case(
        name="travel_flight_class_safe",
        query="Can employees book business class flights for domestic trips under 4 hours?",
        answer="Economy class is required for all domestic flights under 6 hours.",
        evidence=[
            {
                "text": "Economy class travel is mandatory for all domestic flights of less than 6 hours duration.",
                "source": "travel-expense-policy.pdf",
                "version": "2024.1",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Strictly supported by flight booking rules.",
    ),
    _case(
        name="travel_hotel_cap_safe",
        query="What is the hotel reimbursement limit for tier-1 cities?",
        answer="The maximum lodging allowance for tier-1 cities is $250 per night.",
        evidence=[
            {
                "text": "Hotel room rates in tier-1 metropolitan cities are capped at $250 per night excluding taxes.",
                "source": "travel-expense-policy.pdf",
                "version": "2024.1",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Direct match on hotel rate limit.",
    ),

    # --- 5. Health Insurance & Benefits (health-insurance.pdf) -------------
    _case(
        name="health_dental_coverage_conflict_1000_vs_1500",
        query="What is the maximum annual dental benefit?",
        answer="The maximum annual dental benefit is $1,500 per covered member.",
        evidence=[
            {
                "text": "Annual dental benefit is capped at $1500 per enrolled member per benefit year.",
                "source": "health-insurance.pdf",
                "version": "2024",
                "date": DATE_2024,
            },
            {
                "text": "Maximum dental coverage is $1000 per member annually.",
                "source": "health-insurance.pdf",
                "version": "2023",
                "date": DATE_2023,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Dental coverage cap conflict ($1500 vs $1000).",
        failure_type="CONTRADICTION",
    ),
    _case(
        name="health_vision_coverage_safe",
        query="Does company health plan cover annual eye examinations?",
        answer="Yes, comprehensive eye exams are covered 100% once every 12 months.",
        evidence=[
            {
                "text": "Preventive vision exams are covered at 100% with no copay once every 12 calendar months.",
                "source": "health-insurance.pdf",
                "version": "2024",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Matches vision benefit terms.",
    ),
    _case(
        name="health_dependent_age_safe",
        query="Up to what age can dependent children remain on the corporate health plan?",
        answer="Dependent children are eligible for coverage until they reach age 26.",
        evidence=[
            {
                "text": "Dependent children may remain covered under the corporate health insurance plan until age 26.",
                "source": "health-insurance.pdf",
                "version": "2024",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Supported by dependent policy definition.",
    ),

    # --- 6. Parental Leave & Family Care (parental-leave-policy.pdf) --------
    _case(
        name="parental_maternity_conflict_16_vs_26_weeks",
        query="How many weeks of paid maternity leave are provided?",
        answer="Employees receive 26 weeks of fully paid maternity leave.",
        evidence=[
            {
                "text": "Primary caregivers are entitled to 26 weeks of fully paid maternity leave.",
                "source": "parental-leave-policy.pdf",
                "version": "2024.1",
                "date": DATE_2024,
            },
            {
                "text": "Paid maternity leave entitlement is 16 weeks for eligible full-time staff.",
                "source": "parental-leave-policy.pdf",
                "version": "2022.1",
                "date": datetime.date(2022, 6, 1),
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Numeric conflict across versions (26 vs 16 weeks).",
        failure_type="CONTRADICTION",
    ),
    _case(
        name="parental_paternity_leave_safe",
        query="What is the paternity leave entitlement for secondary caregivers?",
        answer="Secondary caregivers receive 4 weeks of paid paternity leave.",
        evidence=[
            {
                "text": "Secondary caregivers receive 4 weeks of paid parental leave within the first 12 months.",
                "source": "parental-leave-policy.pdf",
                "version": "2024.1",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Fully supported by parental leave policy.",
    ),

    # --- 7. Code of Conduct & Ethics (code-of-conduct.pdf) ------------------
    _case(
        name="conduct_gift_limit_safe",
        query="What is the maximum monetary value of gifts employees may accept from vendors?",
        answer="Employees may not accept gifts valued at more than $50 without ethics approval.",
        evidence=[
            {
                "text": "Promotional or courtesy gifts valued in excess of $50 must be declined or declared to compliance.",
                "source": "code-of-conduct.pdf",
                "version": "1.0",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Direct statement match for ethics policy.",
    ),
    _case(
        name="conduct_secondary_employment_caveat",
        query="Can full-time staff take up external consulting projects on weekends?",
        answer="External consulting is allowed on weekends as long as there is no direct client conflict.",
        evidence=[
            {
                "text": "Any external secondary employment or consulting requires advance written approval from the Chief Compliance Officer.",
                "source": "code-of-conduct.pdf",
                "version": "1.0",
                "date": DATE_2024,
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="Answer omits mandatory advance written approval requirement.",
        failure_type="UNSUPPORTED_CLAIM",
    ),

    # --- 8. Knowledge-Base Gaps / Missing Documentation (ABSTAIN) ----------
    _case(
        name="kb_gap_crypto_payroll",
        query="Can I request 20% of my salary to be paid in Bitcoin or Ethereum?",
        answer="Employees can receive up to 25% salary in cryptocurrency via direct wallet transfer.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="Zero corporate evidence exists for crypto compensation.",
        failure_type="NO_EVIDENCE",
    ),
    _case(
        name="kb_gap_pet_bereavement",
        query="How many days of paid bereavement leave apply for pet illness or loss?",
        answer="Employees are entitled to 3 days of paid compassionate leave for domestic pets.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="No policy documents cover pet bereavement leave.",
        failure_type="NO_EVIDENCE",
    ),
    _case(
        name="kb_gap_sabbatical_tenure",
        query="How many consecutive years of service are required before applying for unpaid sabbatical?",
        answer="Employees can apply for a 6-month unpaid sabbatical after 5 years of service.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="No sabbatical documentation exists in the corpus.",
        failure_type="NO_EVIDENCE",
    ),
    _case(
        name="kb_gap_relocation_reimbursement",
        query="What is the relocation lump-sum reimbursement for international transfers to Singapore?",
        answer="International transfers to Singapore receive a $15,000 relocation lump sum.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="Zero documentation on international Singapore relocation allowance.",
        failure_type="NO_EVIDENCE",
    ),

    # --- 9. Ambiguous / Underspecified Inquiries (AMBIGUITY) ----------------
    _case(
        name="ambiguity_vague_leave_query",
        query="How much leave?",
        answer="Employees receive 18 leaves.",
        evidence=[
            {
                "text": "Full-time employees receive 18 casual leaves and 15 earned leaves per annum.",
                "source": "hr-policy.pdf",
                "version": "2024.2",
                "date": DATE_2024,
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="Ambiguous query failed to specify casual, sick, or earned leave.",
        failure_type="AMBIGUITY",
    ),
    _case(
        name="ambiguity_notice_period_query",
        query="What is the notice period?",
        answer="The notice period is 30 days during probation and 90 days after confirmation.",
        evidence=[
            {
                "text": "Notice period during probation is 30 days. After confirmation, the notice period is 90 days.",
                "source": "staff-handbook.pdf",
                "version": "7.0",
                "date": DATE_2024,
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="Query lacks employment status context (probationary vs confirmed).",
        failure_type="AMBIGUITY",
    ),

    # --- 10. Performance & Annual Reviews (performance-bonus-guide.pdf) ----
    _case(
        name="perf_bonus_payout_safe",
        query="When is annual performance bonus paid to employees?",
        answer="Performance bonuses are disbursed in the March payroll cycle following the review year.",
        evidence=[
            {
                "text": "Annual performance bonus payouts are processed in the March payroll following final evaluation.",
                "source": "performance-bonus-guide.pdf",
                "version": "2024",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Matches performance bonus payout timing.",
    ),
    _case(
        name="perf_rating_scale_safe",
        query="What rating scale is used for annual performance evaluations?",
        answer="Performance is evaluated on a 5-point scale from Unsatisfactory (1) to Role Model (5).",
        evidence=[
            {
                "text": "The company utilizes a standard 5-point rating scale ranging from 1 (Unsatisfactory) to 5 (Role Model).",
                "source": "performance-bonus-guide.pdf",
                "version": "2024",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Direct match on rating system.",
    ),

    # --- 11. Security & Data Protection (security-guidelines.pdf) -----------
    _case(
        name="security_password_rotation_safe",
        query="How often must corporate account passwords be rotated?",
        answer="Corporate account passwords must be updated every 90 days.",
        evidence=[
            {
                "text": "User passwords for corporate accounts must be rotated at least once every 90 days.",
                "source": "security-guidelines.pdf",
                "version": "3.1",
                "date": DATE_2024,
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Backed by information security standards.",
    ),
    _case(
        name="security_password_length_conflict_12_vs_16",
        query="What is the minimum character length for network passwords?",
        answer="Passwords must be at least 16 characters long.",
        evidence=[
            {
                "text": "Network passwords must contain a minimum of 16 characters including symbols.",
                "source": "security-guidelines.pdf",
                "version": "3.1",
                "date": DATE_2024,
            },
            {
                "text": "Passwords must have a minimum length of 12 characters.",
                "source": "security-guidelines.pdf",
                "version": "2.0",
                "date": DATE_2023,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Conflict between security policy versions (16 vs 12 characters).",
        failure_type="CONTRADICTION",
    ),

    # --- 12. Cross-Document Cross-Referencing Cases ------------------------
    _case(
        name="cross_doc_sick_leave_policy",
        query="How many days of paid sick leave can employees take annually without medical certificate?",
        answer="Employees may take up to 2 consecutive days of sick leave without a doctor certificate.",
        evidence=[
            {
                "text": "Employees may avail up to 2 consecutive sick leave days without submitting a registered medical certificate.",
                "source": "hr-policy.pdf",
                "version": "2024.2",
                "date": DATE_2024,
            },
            {
                "text": "For medical absences exceeding 2 days, a valid physician certificate must be filed in the HR portal within 48 hours.",
                "source": "staff-handbook.pdf",
                "version": "7.0",
                "date": DATE_2024,
            },
        ],
        expected_decision="ANSWER",
        expected_reason="Two documents reinforce the 2-day self-certified sick leave policy.",
    ),
    _case(
        name="cross_doc_overtime_policy_conflict",
        query="What is the overtime pay multiplier for non-exempt employees on public holidays?",
        answer="Overtime on public holidays is paid at double the regular hourly rate (2.0x).",
        evidence=[
            {
                "text": "Non-exempt overtime worked on declared company holidays is compensated at 2.0x base hourly wage.",
                "source": "hr-policy.pdf",
                "version": "2024.2",
                "date": DATE_2024,
            },
            {
                "text": "Public holiday work is reimbursed at 1.5x regular pay plus one compensatory off day.",
                "source": "staff-handbook.pdf",
                "version": "7.0",
                "date": DATE_2024,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Conflict between hr-policy.pdf (2.0x) and staff-handbook.pdf (1.5x + comp off).",
        failure_type="CONTRADICTION",
    ),
    _case(
        name="cross_doc_equipment_return_probation",
        query="When must company laptops be returned upon resignation during probation?",
        answer="Equipment must be returned to IT assets on or before the final working day.",
        evidence=[
            {
                "text": "All company-provided IT hardware must be surrendered on the last active day of service.",
                "source": "remote-work-policy.pdf",
                "version": "2.0",
                "date": DATE_2024,
            },
            {
                "text": "Departing employees must return badge, laptop, and tokens to facilities before departure clearance.",
                "source": "staff-handbook.pdf",
                "version": "7.0",
                "date": DATE_2024,
            },
        ],
        expected_decision="ANSWER",
        expected_reason="Consistent requirements across remote policy and handbook.",
    ),
    _case(
        name="cross_doc_internet_stipend_conflict",
        query="What is the monthly remote internet allowance for full-time employees?",
        answer="The monthly home internet stipend is $75.",
        evidence=[
            {
                "text": "Remote staff receive a monthly internet connectivity reimbursement of up to $75.",
                "source": "remote-work-policy.pdf",
                "version": "2.0",
                "date": DATE_2024,
            },
            {
                "text": "Monthly telecom and broadband expense reimbursement is capped at $50 upon receipt submission.",
                "source": "travel-expense-policy.pdf",
                "version": "2024.1",
                "date": DATE_2024,
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Disagreement between remote work policy ($75) and travel expense policy ($50).",
        failure_type="CONTRADICTION",
    ),
]


def get_all_seed_cases() -> List[Dict[str, Any]]:
    """Return all cases available for Neo4j seeding (DEV cases + 35 synthetic cases)."""
    from tests.benchmark.test_cases import DEV_CASES

    # Avoid duplicate case names if any overlap
    seen_names = set()
    combined: List[Dict[str, Any]] = []

    for c in list(DEV_CASES) + list(SYNTHETIC_HR_CASES):
        if c["name"] not in seen_names:
            seen_names.add(c["name"])
            combined.append(c)

    return combined
