"""Every threshold and severity rule used by cross-decision intelligence.

This is the single place where AEGIS decides that a pattern across stored
decisions is a *finding* and how severe it is. Nothing here reads data;
`app.intelligence.service` feeds it numbers derived from stored records.

General rules (CONTRACTS.md section 5)
--------------------------------------
* A pattern becomes a finding only when it is observed in at least
  `MIN_DECISIONS_FOR_FINDING` distinct decisions.
* `/summary.data.sufficient` is false below `MIN_GRAPH_DECISIONS`.
* Attribution honesty: a finding is either *direct* (a stored edge links
  the document to the failure: CONTRADICTED_BY, or
  Reason-ABOUT-Evidence-FROM-Document) or *considered* (the document was
  only retrieved in decisions that failed). Considered findings are capped
  at `CONSIDERED_SEVERITY_CAP` and are worded as co-occurrence, never as
  cause.
* A rule that needs a field a stored decision lacks (e.g. `created_at`,
  `topic`) excludes that decision and reports the exclusion; it never
  guesses the value.
"""

from __future__ import annotations

from typing import Iterable, Optional

HIGH = "high"
MEDIUM = "medium"
LOW = "low"
_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: A recurring pattern must be seen in at least this many distinct decisions.
MIN_DECISIONS_FOR_FINDING = 2

#: Below this many Decision nodes the summary is flagged insufficient.
MIN_GRAPH_DECISIONS = 5

#: Most request_ids a finding lists (contract: <=20).
MAX_REQUEST_IDS = 20

#: Considered-only attribution can never be rated above this.
CONSIDERED_SEVERITY_CAP = MEDIUM

#: Outcomes that count as "the decision failed to answer".
GAP_DECISIONS = ("ABSTAIN", "ESCALATE")

#: Outcomes in which the answer was shown to the user.
SHOWN_DECISIONS = ("ANSWER", "CAVEAT")

#: Conflict kinds that are factual disagreements about a value.
VALUE_CONFLICT_KINDS = ("numeric", "date")

# --- unsupported_source -------------------------------------------------
#: Minimum share of non-supported claims, among the claims of decisions
#: that retrieved a document, for a *considered* unsupported_source finding.
UNSUPPORTED_MIN_RATE = 0.5
#: Direct (CONTRADICTED_BY) attribution: high at this many decisions...
UNSUPPORTED_DIRECT_HIGH_DECISIONS = 3
#: ...or at this contradicted-claim rate.
UNSUPPORTED_DIRECT_HIGH_RATE = 0.5

# --- contradiction_hotspot ----------------------------------------------
#: High at this many distinct decisions with a conflict between the pair.
CONTRADICTION_HIGH_DECISIONS = 3

# --- stale_version_in_use -----------------------------------------------
#: High at this many decisions retrieving the superseded version late.
STALE_HIGH_DECISIONS = 3

# --- knowledge_gap ------------------------------------------------------
#: Minimum ABSTAIN+ESCALATE share for a topic to be a gap.
GAP_MIN_RATE = 0.5
#: High when the share reaches this...
GAP_HIGH_RATE = 0.8
#: ...over at least this many decisions on the topic.
GAP_HIGH_DECISIONS = 3

# --- escalation_root_cause ----------------------------------------------
#: High at this many escalations rooted in one document...
ROOT_CAUSE_HIGH_DECISIONS = 3
#: ...or when the document accounts for this share of all escalations.
ROOT_CAUSE_HIGH_SHARE = 0.5

# --- uncertainty_source -------------------------------------------------
#: Minimum share of ABSTAIN/ESCALATE decisions carrying a reason code.
UNCERTAINTY_MIN_SHARE = 0.3
#: High at this share.
UNCERTAINTY_HIGH_SHARE = 0.6


def rate(numerator: int, denominator: int) -> float:
    """numerator/denominator rounded to 4 places; 0.0 for an empty denominator."""
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def cap(severity: str, ceiling: str) -> str:
    """The less severe of `severity` and `ceiling`."""
    return severity if _RANK[severity] >= _RANK[ceiling] else ceiling


def severity_rank(severity: str) -> int:
    return _RANK.get(severity, 9)


def is_recurring(decision_count: int) -> bool:
    """Contract minimum: observed in >= 2 distinct decisions."""
    return decision_count >= MIN_DECISIONS_FOR_FINDING


def unsupported_direct_severity(decisions: int, contradicted_rate: float) -> str:
    """Direct attribution (claims CONTRADICTED_BY this document's evidence).

    high: >= 3 decisions, or contradicted-claim rate >= 0.5; else medium.
    """
    if decisions >= UNSUPPORTED_DIRECT_HIGH_DECISIONS or contradicted_rate >= UNSUPPORTED_DIRECT_HIGH_RATE:
        return HIGH
    return MEDIUM


def unsupported_considered_severity(decisions: int, unsupported_rate: float) -> Optional[str]:
    """Considered attribution (document only retrieved in failing decisions).

    None (no finding) below rate 0.5; medium at rate >= 0.75 with >= 3
    decisions; otherwise low. Never above `CONSIDERED_SEVERITY_CAP`.
    """
    if unsupported_rate < UNSUPPORTED_MIN_RATE:
        return None
    sev = MEDIUM if (unsupported_rate >= 0.75 and decisions >= 3) else LOW
    return cap(sev, CONSIDERED_SEVERITY_CAP)


def contradiction_severity(decisions: int, kinds: Iterable[str], outcomes: Iterable[str]) -> str:
    """high: >= 3 decisions, or a numeric/date conflict in a decision whose
    answer was still shown (ANSWER/CAVEAT); otherwise medium."""
    kinds = set(k for k in kinds if k)
    shown = any(o in SHOWN_DECISIONS for o in outcomes)
    if decisions >= CONTRADICTION_HIGH_DECISIONS:
        return HIGH
    if shown and kinds & set(VALUE_CONFLICT_KINDS):
        return HIGH
    return MEDIUM


def stale_severity(stale_decisions: int, relied_and_shown: int) -> str:
    """high: >= 3 late retrievals, or any decision that showed an answer
    supported by the superseded version; otherwise medium."""
    if stale_decisions >= STALE_HIGH_DECISIONS or relied_and_shown > 0:
        return HIGH
    return MEDIUM


def knowledge_gap_severity(decisions: int, gap_rate: float) -> Optional[str]:
    """None below rate 0.5; high at rate >= 0.8 over >= 3 decisions; else medium."""
    if gap_rate < GAP_MIN_RATE:
        return None
    if gap_rate >= GAP_HIGH_RATE and decisions >= GAP_HIGH_DECISIONS:
        return HIGH
    return MEDIUM


def root_cause_severity(escalations: int, share: float) -> str:
    """Direct attribution. high: >= 3 escalations or share >= 0.5; else medium."""
    if escalations >= ROOT_CAUSE_HIGH_DECISIONS or share >= ROOT_CAUSE_HIGH_SHARE:
        return HIGH
    return MEDIUM


def uncertainty_severity(share: float) -> Optional[str]:
    """None below share 0.3; high at >= 0.6; else medium."""
    if share < UNCERTAINTY_MIN_SHARE:
        return None
    return HIGH if share >= UNCERTAINTY_HIGH_SHARE else MEDIUM
