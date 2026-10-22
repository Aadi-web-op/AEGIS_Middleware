"""PROPOSAL -- maps evidence-signal details onto the decision-graph trace.

**This file is a proposal, not an agreed interface.** Aaradhya owns the
trace contract and the central integration (team brief, section 10). No
trace contract exists in the repository yet, so this builder exists to
(a) show concretely how the enriched entailment and contradiction details
map onto the documented node and relationship vocabulary, (b) give the
graph writer and its tests a real trace to consume, and (c) let the
trace-construction step be timed. It is deliberately **not** wired into
`app.core.evaluator`, and it changes no shared schema.

Three things in here need Aaradhya's and Shatakshi's sign-off before any
of it becomes the real contract; they are flagged inline as
`NEEDS APPROVAL`.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.graph.contract import EVIDENCE_PREVIEW_CHARS, truncate_preview

logger = logging.getLogger(__name__)

# NEEDS APPROVAL (1) -- node identity.
#
# A Decision is identified by request_id, which the brief fixes. For the
# rest, Claim and Evidence ids are scoped to the request, while a Document
# id is *global*: "doc:<source>@<version>". That asymmetry is deliberate
# and is the one choice that decides whether Shatakshi's insight queries
# can aggregate at all -- "which document keeps causing conflicts?" needs
# one Document node shared across decisions, whereas a Claim only ever
# belongs to the decision it was extracted for. An Evidence chunk would
# also be worth sharing, but nothing in the retrieval layer currently
# emits a stable chunk id, so it stays request-scoped until one exists; a
# trace may override by supplying `chunk_id` on an evidence item.
_CLAIM_ID = "{request_id}:claim:{index}"
_EVIDENCE_ID = "{request_id}:evidence:{index}"
_REASON_ID = "{request_id}:reason:{index}"
_DOCUMENT_ID = "doc:{source}"
_DOCUMENT_ID_VERSIONED = "doc:{source}@{version}"

# NEEDS APPROVAL (2) -- reason attribution.
#
# The documented ABOUT relationship needs to know which claim or evidence
# a reason is about, and a `{code, message}` reason does not carry that.
# These codes are attributed structurally from the signal details instead
# of being guessed from the message text. Reasons whose code is not listed
# get a BECAUSE edge and no ABOUT edge, rather than a guessed one.
_CLAIM_REASON_CODES = frozenset({"UNSUPPORTED_CLAIM"})
_EVIDENCE_REASON_CODES = frozenset({"CONTRADICTION", "STALE_EVIDENCE"})

_VERSION_PARTS = re.compile(r"\d+")


def _document_id(source: Optional[str], version: Optional[str]) -> Optional[str]:
    if not source:
        return None
    if version:
        return _DOCUMENT_ID_VERSIONED.format(source=source, version=version)
    return _DOCUMENT_ID.format(source=source)


def _version_sort_key(version: Optional[str]) -> Optional[Tuple[int, ...]]:
    """Comparable key for a version label, or None if it is not comparable."""
    if not version:
        return None
    parts = _VERSION_PARTS.findall(str(version))
    return tuple(int(p) for p in parts) if parts else None


def _as_date(value: Any) -> Optional[datetime.date]:
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _supersedes_order(
    meta_a: Mapping[str, Any], meta_b: Mapping[str, Any]
) -> Optional[Tuple[int, int]]:
    """Which of two documents supersedes the other, as (newer, older) sides.

    Returns None when the ordering cannot be established, in which case
    the caller omits the SUPERSEDES edge rather than picking a direction.
    """
    date_a, date_b = _as_date(meta_a.get("date")), _as_date(meta_b.get("date"))
    if date_a and date_b and date_a != date_b:
        return (0, 1) if date_a > date_b else (1, 0)

    key_a = _version_sort_key(meta_a.get("version"))
    key_b = _version_sort_key(meta_b.get("version"))
    if key_a and key_b and len(key_a) == len(key_b) and key_a != key_b:
        return (0, 1) if key_a > key_b else (1, 0)

    return None


def build_trace(
    *,
    request_id: str,
    decision: Optional[str],
    headline: Optional[str] = None,
    evidence: Sequence[Mapping[str, Any]] = (),
    entailment_details: Optional[Mapping[str, Any]] = None,
    contradiction_details: Optional[Mapping[str, Any]] = None,
    reasons: Sequence[Mapping[str, Any]] = (),
    answerability_score: Optional[float] = None,
    policy_version: Optional[str] = None,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a decision-graph trace from one evaluation's signal details.

    `evidence` is the same list, in the same order, that the evidence
    engine was given: index i here is evidence index i in the signal
    details. Each item may carry `text`, `source`, `version`, `date` and
    optionally `chunk_id`.

    Nothing is inferred that the signals did not report. A claim gets a
    SUPPORTED_BY or CONTRADICTED_BY edge only for an index the entailment
    signal actually listed, and a CONFLICTS_WITH edge is drawn only for a
    conflict the contradiction signal marked `graph_edge_eligible`.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    decision_node: Dict[str, Any] = {
        "id": request_id,
        "type": "Decision",
        "request_id": request_id,
        "decision": decision,
    }
    if headline is not None:
        decision_node["headline"] = headline
    if answerability_score is not None:
        decision_node["answerability_score"] = answerability_score
    if policy_version is not None:
        decision_node["policy_version"] = policy_version
    if profile is not None:
        decision_node["profile"] = profile
    nodes.append(decision_node)

    # --- Evidence and Document -------------------------------------------
    evidence_ids: Dict[int, str] = {}
    document_ids: Dict[int, str] = {}
    evidence_meta: List[Mapping[str, Any]] = list(evidence)

    for index, item in enumerate(evidence_meta):
        chunk_id = item.get("chunk_id")
        evidence_id = (
            str(chunk_id)
            if chunk_id
            else _EVIDENCE_ID.format(request_id=request_id, index=index)
        )
        evidence_ids[index] = evidence_id

        source = item.get("source")
        version = item.get("version")
        # `preview` only: the full passage is never carried into the trace,
        # so it cannot reach the graph even if the writer's cap changed.
        nodes.append(
            {
                "id": evidence_id,
                "type": "Evidence",
                "evidence_index": index,
                "preview": truncate_preview(
                    item.get("text") or item.get("preview") or "",
                    EVIDENCE_PREVIEW_CHARS,
                ),
                "source": source,
                "version": version,
                "date": str(item["date"]) if item.get("date") else None,
            }
        )

        document_id = _document_id(source, version)
        if document_id:
            document_ids[index] = document_id
            if not any(n["id"] == document_id for n in nodes):
                nodes.append(
                    {
                        "id": document_id,
                        "type": "Document",
                        "source": source,
                        "version": version,
                        "date": str(item["date"]) if item.get("date") else None,
                    }
                )
            edges.append({"type": "FROM", "from": evidence_id, "to": document_id})

    # --- Claim, SUPPORTED_BY, CONTRADICTED_BY ----------------------------
    claim_ids: Dict[int, str] = {}
    claim_status: Dict[int, Any] = {}
    claims = (entailment_details or {}).get("claims") or []
    for position, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            continue
        claim_index = claim.get("claim_index", position)
        claim_id = _CLAIM_ID.format(request_id=request_id, index=claim_index)
        claim_ids[claim_index] = claim_id
        claim_status[claim_index] = claim.get("status")
        nodes.append(
            {
                "id": claim_id,
                "type": "Claim",
                "claim_index": claim_index,
                "text": claim.get("claim"),
                "status": claim.get("status"),
                "support": claim.get("support", claim.get("score")),
                "nli_available": claim.get("nli_available"),
            }
        )
        edges.append({"type": "HAS_CLAIM", "from": request_id, "to": claim_id})

        for relationship, key in (
            ("SUPPORTED_BY", "supporting_evidence_indices"),
            ("CONTRADICTED_BY", "contradicting_evidence_indices"),
        ):
            for evidence_index in claim.get(key) or []:
                target = evidence_ids.get(evidence_index)
                if target is None:
                    # The signal named an index this trace has no evidence
                    # for. Skip rather than invent a node.
                    logger.warning(
                        "Claim %s names evidence index %s, which is not in the "
                        "evidence list; omitting the %s edge",
                        claim_index,
                        evidence_index,
                        relationship,
                    )
                    continue
                edges.append(
                    {
                        "type": relationship,
                        "from": claim_id,
                        "to": target,
                        "evidence_index": evidence_index,
                        "support": claim.get("support", claim.get("score")),
                    }
                )

    # --- CONFLICTS_WITH and SUPERSEDES -----------------------------------
    conflicted_evidence: List[int] = []
    conflicts = (contradiction_details or {}).get("conflicts") or []
    for conflict in conflicts:
        if not isinstance(conflict, Mapping):
            continue
        if not conflict.get("graph_edge_eligible"):
            # Diagnostics without a reliable source pair stay out of the
            # graph: the brief prefers a missing edge to an invented one.
            continue
        index_a, index_b = conflict.get("index_a"), conflict.get("index_b")
        left, right = evidence_ids.get(index_a), evidence_ids.get(index_b)
        if left is None or right is None:
            continue
        conflicted_evidence.extend([index_a, index_b])

        edges.append(
            {
                "type": "CONFLICTS_WITH",
                "from": left,
                "to": right,
                "kind": conflict.get("kind"),
                "value_a": conflict.get("value_a"),
                "value_b": conflict.get("value_b"),
                "reason": conflict.get("reason"),
                "severity": conflict.get("severity"),
                "score": conflict.get("score"),
            }
        )

        if conflict.get("kind") != "version":
            continue
        doc_a, doc_b = document_ids.get(index_a), document_ids.get(index_b)
        if not doc_a or not doc_b or doc_a == doc_b:
            continue
        order = _supersedes_order(evidence_meta[index_a], evidence_meta[index_b])
        if order is None:
            logger.debug(
                "Versions %r and %r are not comparable; omitting SUPERSEDES",
                conflict.get("value_a"),
                conflict.get("value_b"),
            )
            continue
        newer, older = order
        edges.append(
            {
                "type": "SUPERSEDES",
                "from": (doc_a, doc_b)[newer],
                "to": (doc_a, doc_b)[older],
            }
        )

    # --- Reason, BECAUSE, ABOUT ------------------------------------------
    unsupported_claims = [
        index for index in sorted(claim_ids)
        if claim_status.get(index) != "SUPPORTED"
    ]
    reason_payload: List[Dict[str, Any]] = []

    for index, reason in enumerate(reasons):
        if not isinstance(reason, Mapping):
            continue
        code = reason.get("code")
        code = getattr(code, "value", code)
        message = reason.get("message")
        reason_id = _REASON_ID.format(request_id=request_id, index=index)
        nodes.append(
            {"id": reason_id, "type": "Reason", "code": code, "message": message}
        )
        edges.append({"type": "BECAUSE", "from": request_id, "to": reason_id})
        reason_payload.append({"code": code, "message": message})

        if code in _CLAIM_REASON_CODES:
            for claim_index in unsupported_claims:
                edges.append(
                    {"type": "ABOUT", "from": reason_id, "to": claim_ids[claim_index]}
                )
        elif code in _EVIDENCE_REASON_CODES:
            for evidence_index in sorted(set(conflicted_evidence)):
                edges.append(
                    {
                        "type": "ABOUT",
                        "from": reason_id,
                        "to": evidence_ids[evidence_index],
                    }
                )

    # NEEDS APPROVAL (3) -- `headline`.
    #
    # The brief lists `headline` on the trace, and section 10 gives the
    # explanation templates to Aaradhya. This builder passes a headline
    # through and never composes one, so that the wording stays in one
    # place rather than being duplicated here.
    return {
        "request_id": request_id,
        "decision": decision,
        "headline": headline,
        "nodes": nodes,
        "edges": edges,
        "reasons": reason_payload,
    }
