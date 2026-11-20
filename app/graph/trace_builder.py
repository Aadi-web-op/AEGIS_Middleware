"""Maps evidence-signal details onto the decision-graph trace.

**This module is live.** `app.core.evaluator` imports `build_trace` and
calls it on every evaluation; the result is returned as the `trace` field
of `EvaluateResponse` and handed to the graph sink via
`app.graph.sink.safe_write_trace`. It is what the frontend's Decision
Graph and the Neo4j writer both consume.

It maps the enriched entailment and contradiction details onto the node
and relationship vocabulary in `app.graph.contract`, and it never raises
into the decision path: the evaluator wraps the call, and a failure here
costs the trace, not the decision.

Three design choices in here were originally flagged for team sign-off
and are now load-bearing, because the Neo4j insight queries and the
frontend both depend on them. They are documented inline as
`DESIGN NOTE` so the reasoning is not lost; changing any of them is a
breaking change to the trace contract.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.graph.contract import (
    EVIDENCE_PREVIEW_CHARS,
    QUERY_PREVIEW_CHARS,
    TRACE_VERSION,
    truncate_preview,
)
from app.graph.topics import topic_key

logger = logging.getLogger(__name__)

# DESIGN NOTE (1) -- node identity.
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
from app.graph.identity import content_hash, document_id, normalized_text
_CLAIM_ID = "{request_id}:claim:{index}"
_EVIDENCE_ID = "{request_id}:evidence:{index}"
_REASON_ID = "{request_id}:reason:{index}"

# DESIGN NOTE (2) -- reason attribution.
#
# The documented ABOUT relationship needs to know which claim or evidence
# a reason is about, and a `{code, message}` reason does not carry that.
# These codes are attributed structurally from the signal details instead
# of being guessed from the message text. Reasons whose code is not listed
# get a BECAUSE edge and no ABOUT edge, rather than a guessed one.
_CLAIM_REASON_CODES = frozenset({"UNSUPPORTED_CLAIM"})
# Only CONTRADICTION. The evidence a reason is attributed to here comes from
# the contradiction signal's conflict pairs, which say nothing about which
# passage is stale: STALE_EVIDENCE comes from the freshness signal, which
# reports no evidence indices at all. Attributing it to whatever happened to
# conflict would point the ABOUT edge at the wrong passages -- and at none
# when a decision is stale but has no conflicts. It is left unattributed,
# with its BECAUSE edge only, until freshness names its own indices.
_EVIDENCE_REASON_CODES = frozenset({"CONTRADICTION"})

_VERSION_PARTS = re.compile(r"\d+")


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


def document_sort_keys(meta: Mapping[str, Any]) -> Dict[str, Any]:
    """Sort keys stored on a Document so Cypher can order versions.

    `date_key` is the ISO day and `version_key` the numeric parts of the
    version label -- exactly what `_supersedes_order` compares, so the
    cross-trace linking statement in the writer and the within-trace
    ordering here cannot disagree. A key that cannot be derived is left
    out rather than guessed.
    """
    keys: Dict[str, Any] = {}
    day = _as_date(meta.get("date"))
    if day is not None:
        keys["date_key"] = day.isoformat()[:10]
    version_key = _version_sort_key(meta.get("version"))
    if version_key:
        keys["version_key"] = list(version_key)
    return keys


def utc_now_iso() -> str:
    """Current time as an ISO-8601 UTC string, for a Decision's `created_at`."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def query_preview(query: Any) -> Optional[str]:
    """Secret-redacted, whitespace-collapsed, capped preview of a query."""
    if not isinstance(query, str) or not query.strip():
        return None
    try:
        # Imported lazily: app.audit pulls in the API schemas and routes.
        from app.audit.logger import sanitize_secrets

        cleaned = sanitize_secrets(query) or ""
    except Exception:
        # Never store a query we could not redact.
        logger.exception("Could not sanitise a query preview; omitting it")
        return None
    return truncate_preview(cleaned, QUERY_PREVIEW_CHARS) or None


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
    query: Optional[str] = None,
    created_at: Optional[str] = None,
    degraded: Optional[bool] = None,
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

    `query` is never stored whole: the Decision carries a redacted
    `query_preview` (<=160 chars) and a `topic` keyword key derived from
    it. `created_at` is an ISO-8601 UTC timestamp supplied by the caller,
    which keeps this function deterministic.
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
    if created_at is not None:
        decision_node["created_at"] = str(created_at)
    preview = query_preview(query)
    if preview:
        decision_node["query_preview"] = preview
    topic = topic_key(query)
    if topic:
        decision_node["topic"] = topic
    if degraded is not None:
        decision_node["degraded"] = bool(degraded)
    decision_node["trace_version"] = TRACE_VERSION
    nodes.append(decision_node)

    # --- Evidence and Document -------------------------------------------
    evidence_ids: Dict[int, str] = {}
    document_ids: Dict[int, str] = {}
    evidence_meta: List[Mapping[str, Any]] = list(evidence)
    used_evidence_ids: set[str] = set()
    document_evidence: dict[str, list[str]] = {}

    for index, item in enumerate(evidence_meta):
        chunk_id = item.get("chunk_id")
        request_scoped_id = _EVIDENCE_ID.format(request_id=request_id, index=index)
        evidence_id = str(chunk_id) if chunk_id else request_scoped_id
        if evidence_id in used_evidence_ids:
            # Two passages claiming one chunk id would otherwise become one
            # node holding one passage's properties while both evidence
            # indices pointed at it -- a claim supported by passage 0 and a
            # conflict found in passage 1 would land on the same node. Fall
            # back to the request-scoped id so the two stay distinct.
            logger.warning(
                "Evidence %s repeats chunk id %r; using the request-scoped id "
                "%r instead so the two passages stay separate nodes",
                index,
                evidence_id,
                request_scoped_id,
            )
            evidence_id = request_scoped_id
        used_evidence_ids.add(evidence_id)
        evidence_ids[index] = evidence_id

        source = item.get("source")
        version = item.get("version")
        text = item.get("text")
        canonical_text = normalized_text(text) if isinstance(text, str) else ""
        revision_hash = item.get("document_content_hash")
        # `preview` only: the full passage is never carried into the trace,
        # so it cannot reach the graph even if the writer's cap changed.
        evidence_node = {
            "id": evidence_id,
            "type": "Evidence",
            "evidence_index": index,
            "preview": truncate_preview(
                canonical_text or item.get("preview") or "",
                EVIDENCE_PREVIEW_CHARS,
            ),
            "source": source,
            "version": version,
            "date": str(item["date"]) if item.get("date") else None,
        }
        if canonical_text:
            evidence_node["content_hash"] = content_hash(canonical_text)
        nodes.append(evidence_node)
        # Every passage the decision considered, cited or not. Without this
        # an uncited passage is only reachable through its Document, and
        # "which decisions retrieved this document?" cannot be answered.
        edges.append(
            {
                "type": "RETRIEVED",
                "from": request_id,
                "to": evidence_id,
                "evidence_index": index,
            }
        )

        doc_id = document_id(source, version, revision_hash)
        if doc_id:
            document_ids[index] = doc_id
            if doc_id not in document_evidence:
                document_evidence[doc_id] = []
                nodes.append(
                    {
                        "id": doc_id,
                        "type": "Document",
                        "source": source,
                        "version": version,
                        "date": str(item["date"]) if item.get("date") else None,
                        **document_sort_keys(item),
                        **({"content_hash": revision_hash} if revision_hash else {}),
                    }
                )
            document_evidence[doc_id].append(evidence_id)
            edges.append({"type": "FROM", "from": evidence_id, "to": doc_id})

    for doc_id, evidence_refs in document_evidence.items():
        edges.append({
            "type": "USES_DOCUMENT",
            "from": request_id,
            "to": doc_id,
            "evidence_ids": evidence_refs,
        })

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
                        "document_id": document_ids.get(evidence_index),
                        "support": claim.get("support", claim.get("score")),
                    }
                )

    # --- CONFLICTS_WITH and SUPERSEDES -----------------------------------
    conflicted_evidence: List[int] = []
    supersedes_seen: set[Tuple[str, str]] = set()

    def _add_supersedes(newer_id: str, older_id: str, derived: str) -> None:
        if (newer_id, older_id) in supersedes_seen or (older_id, newer_id) in supersedes_seen:
            return
        supersedes_seen.add((newer_id, older_id))
        edges.append(
            {"type": "SUPERSEDES", "from": newer_id, "to": older_id, "derived": derived}
        )

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
                "occurrence_id": f"{request_id}:{index_a}:{index_b}",
                "document_a_id": document_ids.get(index_a),
                "document_b_id": document_ids.get(index_b),
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
        if evidence_meta[index_a].get("document_content_hash") and evidence_meta[index_b].get("document_content_hash"):
            continue  # Ingestion records authoritative ordering for these revisions.
        order = _supersedes_order(evidence_meta[index_a], evidence_meta[index_b])
        if order is None:
            logger.debug(
                "Versions %r and %r are not comparable; omitting SUPERSEDES",
                conflict.get("value_a"),
                conflict.get("value_b"),
            )
            continue
        newer, older = order
        _add_supersedes((doc_a, doc_b)[newer], (doc_a, doc_b)[older], "version_conflict")

    # Same-source documents with a comparable date/version supersede one
    # another whether or not the contradiction signal flagged them: two
    # versions of one policy in the same retrieval is a fact about the
    # documents, not about this answer. (The writer applies the same rule
    # across traces.) An order that cannot be established draws no edge.
    by_document: Dict[str, Mapping[str, Any]] = {}
    for index in sorted(document_ids):
        by_document.setdefault(document_ids[index], evidence_meta[index])
    document_list = list(by_document.items())
    for position, (doc_a, meta_a) in enumerate(document_list):
        for doc_b, meta_b in document_list[position + 1:]:
            if not meta_a.get("source") or meta_a.get("source") != meta_b.get("source"):
                continue
            order = _supersedes_order(meta_a, meta_b)
            if order is None:
                continue
            newer, older = order
            _add_supersedes(
                (doc_a, doc_b)[newer], (doc_a, doc_b)[older], "same_source_order"
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
                        "document_id": document_ids.get(evidence_index),
                    }
                )

    # DESIGN NOTE (3) -- `headline`.
    #
    # The brief lists `headline` on the trace, and section 10 gives the
    # explanation templates to Aaradhya. This builder passes a headline
    # through and never composes one, so that the wording stays in one
    # place rather than being duplicated here.
    return {
        "request_id": request_id,
        "decision": decision,
        "headline": headline,
        "trace_version": TRACE_VERSION,
        "nodes": nodes,
        "edges": edges,
        "reasons": reason_payload,
    }
