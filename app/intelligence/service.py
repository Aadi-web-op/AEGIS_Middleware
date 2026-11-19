"""Derives cross-decision findings from stored records.

Two layers:

* pure functions (`build_*`, `*_findings`) that turn query rows into
  tables and `Finding`s -- no I/O, unit-tested from canned rows;
* `IntelligenceService`, which runs the named queries in
  `app.intelligence.queries`, reads the audit log, and degrades when the
  graph is unreachable.

Nothing here invents data: every number is a count over the rows it was
given, every finding lists the request_ids it rests on, and a decision
that lacks a field a rule needs is excluded and reported, not guessed.
Thresholds and severities live only in `app.intelligence.rules`.
"""

from __future__ import annotations

import datetime
import logging
import re
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.intelligence import queries, rules
from app.intelligence.audit import AuditReader, AuditUnavailable
from app.intelligence.models import Exclusion, Finding, Metric, Subject, finding_id

logger = logging.getLogger(__name__)

Row = Dict[str, Any]
TopicFn = Callable[[str], str]


class GraphUnavailable(RuntimeError):
    """Neo4j is not configured or a read failed.

    `unreachable` is True for connectivity failures (server down, session
    expired, timeout), which callers may remember briefly to fail fast.
    The message never carries driver internals; those are logged.
    """

    def __init__(self, message: str, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable


NOT_CONFIGURED = "Neo4j is not configured. The decision graph is unavailable."
UNREACHABLE = "Neo4j is not reachable. The decision graph is unavailable."


def _is_connectivity_error(exc: BaseException) -> bool:
    if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
        return True
    try:
        from neo4j.exceptions import ServiceUnavailable, SessionExpired  # type: ignore

        return isinstance(exc, (ServiceUnavailable, SessionExpired))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _ids(values: Iterable[str]) -> List[str]:
    """Sorted, de-duplicated request ids, capped at the contract maximum."""
    return sorted(set(v for v in values if v))[: rules.MAX_REQUEST_IDS]


def _complete(rows: Sequence[Row], *keys: str) -> List[Row]:
    """Rows that have every key the derivation groups on (a node stored
    without an id cannot be attributed, so it is skipped, not guessed)."""
    return [r for r in rows if all(r.get(k) for k in keys)]


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _doc_label(doc_id: str) -> str:
    return doc_id[4:] if doc_id.startswith("doc:") else doc_id


def default_topic_fn() -> Optional[TopicFn]:
    """`app.graph.topics.topic_key` when the graph model provides it."""
    try:
        from app.graph.topics import topic_key  # type: ignore

        return topic_key
    except Exception:
        return None


_VERSION_PARTS = re.compile(r"\d+")


def _version_key(version: Any) -> Optional[Tuple[int, ...]]:
    parts = _VERSION_PARTS.findall(str(version)) if version else []
    return tuple(int(p) for p in parts) if parts else None


def _date_key(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def newer_older(doc_a: Row, doc_b: Row) -> Optional[Tuple[Row, Row]]:
    """(newer, older) for two documents of one source, or None if the
    order cannot be established. Same rule the trace builder uses for
    SUPERSEDES: differing dates decide, else comparable version labels."""
    date_a, date_b = _date_key(doc_a.get("date")), _date_key(doc_b.get("date"))
    if date_a and date_b and date_a != date_b:
        return (doc_a, doc_b) if date_a > date_b else (doc_b, doc_a)
    key_a, key_b = _version_key(doc_a.get("version")), _version_key(doc_b.get("version"))
    if key_a and key_b and len(key_a) == len(key_b) and key_a != key_b:
        return (doc_a, doc_b) if key_a > key_b else (doc_b, doc_a)
    return None


def supersession_map(
    documents: Sequence[Row], supersedes_edges: Sequence[Row]
) -> Dict[str, Dict[str, str]]:
    """older doc id -> {newer doc id: basis}.

    Basis is "graph_edge" for a stored SUPERSEDES edge, otherwise
    "derived_from_version_or_date" for two Document nodes that share a
    `source` and have a comparable date/version (used when the stored
    graph predates cross-trace SUPERSEDES linking).
    """
    out: Dict[str, Dict[str, str]] = defaultdict(dict)
    for edge in supersedes_edges:
        if edge.get("newer") and edge.get("older") and edge["newer"] != edge["older"]:
            out[edge["older"]][edge["newer"]] = "graph_edge"
    by_source: Dict[str, List[Row]] = defaultdict(list)
    for doc in documents:
        if doc.get("source") and doc.get("doc_id"):
            by_source[doc["source"]].append(doc)
    for docs in by_source.values():
        for i, doc_a in enumerate(docs):
            for doc_b in docs[i + 1:]:
                order = newer_older(doc_a, doc_b)
                if order is None:
                    continue
                newer, older = order
                out[older["doc_id"]].setdefault(newer["doc_id"], "derived_from_version_or_date")
    return {k: dict(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# Per-document reliability table (+ unsupported_source findings)
# ---------------------------------------------------------------------------
def build_document_table(
    overview: Sequence[Row],
    usage: Sequence[Row],
    conflicts: Sequence[Row],
    superseded_by: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Row]:
    """One row per document, with the contract fields plus the id lists
    the findings need (`_request_ids*`, stripped by the route).

    * `decisions`: decisions that considered the document.
    * `supported_claims`: claims with status SUPPORTED and a SUPPORTED_BY
      edge into this document's evidence (direct).
    * `contradicted_claims`: claims with a CONTRADICTED_BY edge into this
      document's evidence (direct).
    * `unsupported_or_contradicted_claims` / `claims_in_decisions`: claims
      that were not SUPPORTED, out of all claims, in the decisions that
      considered the document (co-occurrence, not attribution).
    """
    by_request = {row["request_id"]: row for row in overview}
    conflict_decisions: Dict[str, set] = defaultdict(set)
    for row in _complete(conflicts, "request_id", "doc_a", "doc_b"):
        for key in ("doc_a", "doc_b"):
            conflict_decisions[row[key]].add(row["request_id"])

    docs: Dict[str, Row] = {}
    for row in usage:
        if not row.get("doc_id") or not row.get("request_id"):
            continue
        doc = docs.setdefault(
            row["doc_id"],
            {
                "doc_id": row["doc_id"], "source": row.get("source"),
                "version": row.get("version"), "date": row.get("date"),
                "_all": set(), "_unsupported": set(), "_contradicted": set(),
                "_relied": set(), "_esc": set(), "_abs": set(),
                "supported_claims": 0, "contradicted_claims": 0,
                "claims_in_decisions": 0, "unsupported_or_contradicted_claims": 0,
            },
        )
        rid = row["request_id"]
        if rid in doc["_all"]:
            continue
        doc["_all"].add(rid)
        info = by_request.get(rid, {})
        claims = int(info.get("claims") or 0)
        not_supported = max(claims - int(info.get("supported_claims") or 0), 0)
        doc["claims_in_decisions"] += claims
        doc["unsupported_or_contradicted_claims"] += not_supported
        doc["supported_claims"] += int(row.get("supported_by_doc") or 0)
        doc["contradicted_claims"] += int(row.get("contradicted_by_doc") or 0)
        if not_supported:
            doc["_unsupported"].add(rid)
        if int(row.get("contradicted_by_doc") or 0):
            doc["_contradicted"].add(rid)
        if int(row.get("supported_by_doc") or 0):
            doc["_relied"].add(rid)
        decision = row.get("decision") or info.get("decision")
        if decision == "ESCALATE":
            doc["_esc"].add(rid)
        elif decision == "ABSTAIN":
            doc["_abs"].add(rid)

    table: List[Row] = []
    for doc_id, doc in docs.items():
        table.append(
            {
                "doc_id": doc_id,
                "source": doc["source"],
                "version": doc["version"],
                "date": doc["date"],
                "decisions": len(doc["_all"]),
                "supported_claims": doc["supported_claims"],
                "unsupported_or_contradicted_claims": doc["unsupported_or_contradicted_claims"],
                "unsupported_rate": rules.rate(
                    doc["unsupported_or_contradicted_claims"], doc["claims_in_decisions"]
                ),
                "claims_in_decisions": doc["claims_in_decisions"],
                "contradicted_claims": doc["contradicted_claims"],
                "relied_on_decisions": len(doc["_relied"]),
                "conflicts": len(conflict_decisions.get(doc_id, ())),
                "escalations": len(doc["_esc"]),
                "abstains": len(doc["_abs"]),
                "superseded_by": sorted((superseded_by or {}).get(doc_id, {})),
                "_request_ids": sorted(doc["_all"]),
                "_request_ids_unsupported": sorted(doc["_unsupported"]),
                "_request_ids_contradicted": sorted(doc["_contradicted"]),
            }
        )
    table.sort(key=lambda r: (-r["unsupported_rate"], -r["decisions"], r["doc_id"]))
    return table


def unsupported_source_findings(table: Sequence[Row]) -> List[Finding]:
    """Documents that recur with unsupported or contradicted claims.

    Direct: claims CONTRADICTED_BY the document's own evidence in >= 2
    decisions. Otherwise considered: the document was retrieved in >= 2
    decisions containing non-supported claims (capped at medium, worded as
    co-occurrence).
    """
    findings: List[Finding] = []
    for doc in table:
        label = _doc_label(doc["doc_id"])
        subject = [Subject(type="Document", id=doc["doc_id"])]
        direct_ids = doc["_request_ids_contradicted"]
        considered_ids = doc["_request_ids_unsupported"]
        total_claims = doc["claims_in_decisions"]
        if rules.is_recurring(len(direct_ids)):
            numerator = doc["contradicted_claims"]
            value = rules.rate(numerator, total_claims)
            findings.append(
                Finding(
                    id=finding_id("unsupported_source", doc["doc_id"], "direct"),
                    kind="unsupported_source",
                    severity=rules.unsupported_direct_severity(len(direct_ids), value),
                    title=f"{label} contradicts answer claims",
                    explanation=(
                        f"Evidence from {label} contradicted {_plural(numerator, 'claim')} "
                        f"in {_plural(len(direct_ids), 'decision')}: {numerator} of the "
                        f"{total_claims} claims ({_pct(value)}) made in the "
                        f"{_plural(doc['decisions'], 'decision')} that retrieved it."
                    ),
                    metric=Metric(name="contradicted_claim_rate", value=value,
                                  numerator=numerator, denominator=total_claims),
                    subjects=subject,
                    request_ids=_ids(direct_ids),
                    query="decision_document_usage",
                    attribution="direct",
                    details={"decisions_with_contradicted_claims": len(direct_ids),
                             "decisions_retrieving_document": doc["decisions"]},
                )
            )
            continue
        if not rules.is_recurring(len(considered_ids)):
            continue
        numerator = doc["unsupported_or_contradicted_claims"]
        value = rules.rate(numerator, total_claims)
        severity = rules.unsupported_considered_severity(len(considered_ids), value)
        if severity is None:
            continue
        findings.append(
            Finding(
                id=finding_id("unsupported_source", doc["doc_id"], "considered"),
                kind="unsupported_source",
                severity=severity,
                title=f"{label} recurs alongside unsupported claims",
                explanation=(
                    f"{label} was retrieved in {_plural(len(considered_ids), 'decision')} "
                    f"that contained unsupported or contradicted claims: {numerator} of "
                    f"{total_claims} claims ({_pct(value)}) in the "
                    f"{_plural(doc['decisions'], 'decision')} that retrieved it were not "
                    f"supported. No stored link ties those claims to this document, so "
                    f"this is co-occurrence only."
                ),
                metric=Metric(name="unsupported_claim_rate", value=value,
                              numerator=numerator, denominator=total_claims),
                subjects=subject,
                request_ids=_ids(considered_ids),
                query="decision_document_usage",
                attribution="considered",
                details={"decisions_with_unsupported_claims": len(considered_ids),
                         "decisions_retrieving_document": doc["decisions"]},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Contradictions between documents
# ---------------------------------------------------------------------------
def build_contradiction_pairs(conflicts: Sequence[Row], usage: Sequence[Row]) -> List[Row]:
    """Document pairs with stored CONFLICTS_WITH edges between their evidence."""
    docs_by_request: Dict[str, set] = defaultdict(set)
    for row in _complete(usage, "request_id", "doc_id"):
        docs_by_request[row["request_id"]].add(row["doc_id"])

    pairs: Dict[Tuple[str, str], Row] = {}
    for row in _complete(conflicts, "request_id", "doc_a", "doc_b"):
        swap = row["doc_a"] > row["doc_b"]
        a, b = (row["doc_b"], row["doc_a"]) if swap else (row["doc_a"], row["doc_b"])
        src_a, src_b = (
            (row.get("source_b"), row.get("source_a")) if swap
            else (row.get("source_a"), row.get("source_b"))
        )
        val_a, val_b = (
            (row.get("value_b"), row.get("value_a")) if swap
            else (row.get("value_a"), row.get("value_b"))
        )
        pair = pairs.setdefault(
            (a, b),
            {"doc_a": a, "doc_b": b, "source_a": src_a, "source_b": src_b,
             "conflict_count": 0, "_decisions": {}, "_kinds": set(), "sample_values": []},
        )
        pair["conflict_count"] += 1
        pair["_decisions"][row["request_id"]] = row.get("decision")
        if row.get("kind"):
            pair["_kinds"].add(row["kind"])
        sample = {"kind": row.get("kind"), "value_a": val_a, "value_b": val_b,
                  "request_id": row["request_id"]}
        if (val_a is not None or val_b is not None) and len(pair["sample_values"]) < 5:
            pair["sample_values"].append(sample)

    out: List[Row] = []
    for (a, b), pair in pairs.items():
        together = sorted(
            rid for rid, docs in docs_by_request.items() if a in docs and b in docs
        )
        decisions = pair.pop("_decisions")
        # Every conflicting decision retrieved both documents by definition.
        together_count = len(set(together) | set(decisions))
        pair.update(
            {
                "kinds": sorted(pair.pop("_kinds")),
                "decision_count": len(decisions),
                "decisions_retrieving_both": together_count,
                "conflict_rate": rules.rate(len(decisions), together_count),
                "outcomes": dict(sorted(decisions.items())),
                "request_ids": _ids(decisions),
            }
        )
        out.append(pair)
    out.sort(key=lambda p: (-p["decision_count"], -p["conflict_count"], p["doc_a"], p["doc_b"]))
    return out


def contradiction_findings(pairs: Sequence[Row]) -> List[Finding]:
    findings: List[Finding] = []
    for pair in pairs:
        n = pair["decision_count"]
        if not rules.is_recurring(n):
            continue
        a, b = _doc_label(pair["doc_a"]), _doc_label(pair["doc_b"])
        kinds = ", ".join(pair["kinds"]) or "unspecified"
        shown = sum(1 for o in pair["outcomes"].values() if o in rules.SHOWN_DECISIONS)
        sample = ""
        if pair["sample_values"]:
            s = pair["sample_values"][0]
            sample = f" Example: {s['value_a']} vs {s['value_b']}."
        findings.append(
            Finding(
                id=finding_id("contradiction_hotspot", pair["doc_a"], pair["doc_b"]),
                kind="contradiction_hotspot",
                severity=rules.contradiction_severity(
                    n, pair["kinds"], pair["outcomes"].values()
                ),
                title=f"{a} conflicts with {b}",
                explanation=(
                    f"{a} and {b} disagreed ({kinds}) in {n} of the "
                    f"{_plural(pair['decisions_retrieving_both'], 'decision')} that "
                    f"retrieved both ({_pct(pair['conflict_rate'])}); "
                    f"{shown} of those {n} still showed an answer.{sample}"
                ),
                metric=Metric(name="conflict_rate", value=pair["conflict_rate"],
                              numerator=n, denominator=pair["decisions_retrieving_both"]),
                subjects=[Subject(type="Document", id=pair["doc_a"]),
                          Subject(type="Document", id=pair["doc_b"])],
                request_ids=pair["request_ids"],
                query="conflict_edges",
                attribution="direct",
                details={"kinds": pair["kinds"], "conflict_edges": pair["conflict_count"]},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Superseded versions still in use
# ---------------------------------------------------------------------------
def build_stale_usage(
    usage: Sequence[Row],
    documents: Sequence[Row],
    supersedes_edges: Sequence[Row],
) -> Tuple[List[Row], List[Exclusion]]:
    """Per superseded document: decisions that retrieved it after a newer
    version existed.

    "After" needs two stored facts, and nothing is assumed when either is
    missing:

    * a cutoff -- the newer Document's `date`, else the earliest
      `created_at` of a decision that retrieved the newer version;
    * the decision's own `created_at`.

    Decisions without `created_at`, and pairs without a cutoff, are
    excluded and counted in the returned exclusions.
    """
    usage = _complete(usage, "request_id", "doc_id")
    doc_meta = {d["doc_id"]: d for d in documents if d.get("doc_id")}
    for row in usage:
        doc_meta.setdefault(
            row["doc_id"],
            {"doc_id": row["doc_id"], "source": row.get("source"),
             "version": row.get("version"), "date": row.get("date")},
        )
    superseded = supersession_map(list(doc_meta.values()), supersedes_edges)

    usage_by_doc: Dict[str, Dict[str, Row]] = defaultdict(dict)
    for row in usage:
        usage_by_doc[row["doc_id"]].setdefault(row["request_id"], row)

    items: List[Row] = []
    no_created_at: set = set()
    no_cutoff_pairs = 0
    for older_id in sorted(superseded):
        older_usage = usage_by_doc.get(older_id, {})
        if not older_usage:
            continue
        # Earliest known cutoff among the versions that supersede this one.
        candidates: List[Tuple[str, str, str, str]] = []
        for newer_id, basis in superseded[older_id].items():
            newer_date = _date_key(doc_meta.get(newer_id, {}).get("date"))
            if newer_date:
                candidates.append((newer_date, newer_id, "newer_document_date", basis))
                continue
            seen = sorted(
                r["created_at"] for r in usage_by_doc.get(newer_id, {}).values()
                if r.get("created_at")
            )
            if seen:
                candidates.append((str(seen[0]), newer_id, "first_retrieval_of_newer", basis))
        if not candidates:
            no_cutoff_pairs += 1
            continue
        cutoff, newer_id, cutoff_basis, supersedes_basis = min(candidates)

        stale: List[Row] = []
        for rid, row in sorted(older_usage.items()):
            created = row.get("created_at")
            if not created:
                no_created_at.add(rid)
                continue
            created = str(created)
            is_after = (
                created[:10] > cutoff if cutoff_basis == "newer_document_date"
                else created >= cutoff
            )
            if is_after:
                stale.append(
                    {"request_id": rid, "decision": row.get("decision"),
                     "created_at": created,
                     "relied": int(row.get("supported_by_doc") or 0) > 0}
                )
        # Denominator: dated decisions after the cutoff that retrieved
        # either version.
        eligible = {s["request_id"] for s in stale}
        for rid, row in usage_by_doc.get(newer_id, {}).items():
            created = row.get("created_at")
            if not created:
                continue
            created = str(created)
            if (created[:10] > cutoff) if cutoff_basis == "newer_document_date" else (created >= cutoff):
                eligible.add(rid)
        older, newer = doc_meta.get(older_id, {}), doc_meta.get(newer_id, {})
        items.append(
            {
                "older_doc_id": older_id,
                "newer_doc_id": newer_id,
                "source": older.get("source"),
                "older_version": older.get("version"),
                "newer_version": newer.get("version"),
                "superseded_by": sorted(superseded[older_id]),
                "supersedes_basis": supersedes_basis,
                "cutoff": cutoff,
                "cutoff_basis": cutoff_basis,
                "stale_decisions": len(stale),
                "eligible_decisions": len(eligible),
                "stale_usage_rate": rules.rate(len(stale), len(eligible)),
                "decisions": stale,
                "request_ids": _ids(s["request_id"] for s in stale),
                "relied_request_ids": _ids(s["request_id"] for s in stale if s["relied"]),
            }
        )
    items = [i for i in items if i["stale_decisions"] > 0]
    items.sort(key=lambda i: (-i["stale_decisions"], i["older_doc_id"]))

    exclusions: List[Exclusion] = []
    if no_created_at:
        exclusions.append(
            Exclusion(
                rule="stale_version_in_use", count=len(no_created_at),
                reason="decisions that retrieved a superseded version have no created_at, "
                       "so it cannot be shown they happened after the newer version existed",
            )
        )
    if no_cutoff_pairs:
        exclusions.append(
            Exclusion(
                rule="stale_version_in_use", count=no_cutoff_pairs,
                reason="superseded documents whose newer version has no date and no dated "
                       "retrieval, so no cutoff could be established",
            )
        )
    return items, exclusions


def stale_findings(items: Sequence[Row]) -> List[Finding]:
    findings: List[Finding] = []
    for item in items:
        n = item["stale_decisions"]
        if not rules.is_recurring(n):
            continue
        older, newer = _doc_label(item["older_doc_id"]), _doc_label(item["newer_doc_id"])
        relied_shown = [
            d for d in item["decisions"]
            if d["relied"] and d["decision"] in rules.SHOWN_DECISIONS
        ]
        when = (
            f"dated {item['cutoff']}" if item["cutoff_basis"] == "newer_document_date"
            else f"first retrieved at {item['cutoff']}"
        )
        findings.append(
            Finding(
                id=finding_id("stale_version_in_use", item["older_doc_id"]),
                kind="stale_version_in_use",
                severity=rules.stale_severity(n, len(relied_shown)),
                title=f"Superseded {older} is still being retrieved",
                explanation=(
                    f"{older} was retrieved in {n} of the "
                    f"{_plural(item['eligible_decisions'], 'decision')} "
                    f"({_pct(item['stale_usage_rate'])}) made on this source after the "
                    f"newer {newer} ({when}) existed. In {len(relied_shown)} of them a "
                    f"shown answer had a claim supported by the superseded version."
                ),
                metric=Metric(name="stale_usage_rate", value=item["stale_usage_rate"],
                              numerator=n, denominator=item["eligible_decisions"]),
                subjects=[Subject(type="Document", id=item["older_doc_id"]),
                          Subject(type="Document", id=item["newer_doc_id"])],
                request_ids=item["request_ids"],
                query="decision_document_usage+supersedes_edges",
                attribution="direct",
                details={"cutoff": item["cutoff"], "cutoff_basis": item["cutoff_basis"],
                         "supersedes_basis": item["supersedes_basis"],
                         "relied_request_ids": item["relied_request_ids"]},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Knowledge gaps by topic
# ---------------------------------------------------------------------------
def build_knowledge_gaps(
    overview: Sequence[Row],
    audit_queries: Optional[Dict[str, str]] = None,
    topic_fn: Optional[TopicFn] = None,
) -> Tuple[List[Row], List[Exclusion]]:
    """Topics ranked by ABSTAIN/ESCALATE share (topics with >= 2 decisions).

    The topic is `Decision.topic`. For a decision stored without one, the
    same deterministic `topic_key` is applied to its audit-log query when
    both are available; otherwise the decision is excluded.
    """
    audit_queries = audit_queries or {}
    topics: Dict[str, Row] = {}
    excluded = 0
    for row in _complete(overview, "request_id"):
        rid = row["request_id"]
        topic = row.get("topic") or ""
        source = "graph"
        if not topic and topic_fn is not None and audit_queries.get(rid):
            try:
                topic = topic_fn(audit_queries[rid]) or ""
            except Exception:
                topic = ""
            source = "audit_query"
        if not topic:
            excluded += 1
            continue
        item = topics.setdefault(
            topic,
            {"topic": topic, "_all": [], "_abstain": [], "_escalate": [],
             "sample_queries": [], "topic_sources": set()},
        )
        item["_all"].append(rid)
        item["topic_sources"].add(source)
        if row.get("decision") == "ABSTAIN":
            item["_abstain"].append(rid)
        elif row.get("decision") == "ESCALATE":
            item["_escalate"].append(rid)
        sample = row.get("query_preview") or (audit_queries.get(rid) or "")[:160]
        if sample and sample not in item["sample_queries"] and len(item["sample_queries"]) < 5:
            item["sample_queries"].append(sample)

    items: List[Row] = []
    for item in topics.values():
        total = len(item["_all"])
        if total < rules.MIN_DECISIONS_FOR_FINDING:
            continue
        gap_ids = item["_abstain"] + item["_escalate"]
        items.append(
            {
                "topic": item["topic"],
                "decisions": total,
                "abstains": len(item["_abstain"]),
                "escalations": len(item["_escalate"]),
                "gap_decisions": len(gap_ids),
                "gap_rate": rules.rate(len(gap_ids), total),
                "sample_queries": item["sample_queries"],
                "request_ids": _ids(gap_ids),
                "all_request_ids": _ids(item["_all"]),
                "topic_sources": sorted(item["topic_sources"]),
            }
        )
    items.sort(key=lambda i: (-i["gap_rate"], -i["gap_decisions"], i["topic"]))
    exclusions = []
    if excluded:
        exclusions.append(
            Exclusion(
                rule="knowledge_gap", count=excluded,
                reason="decisions stored without a topic (older traces, or queries with "
                       "no keywords) are not grouped into any topic",
            )
        )
    return items, exclusions


def knowledge_gap_findings(items: Sequence[Row]) -> List[Finding]:
    findings: List[Finding] = []
    for item in items:
        n = item["gap_decisions"]
        if not rules.is_recurring(n):
            continue
        severity = rules.knowledge_gap_severity(item["decisions"], item["gap_rate"])
        if severity is None:
            continue
        label = item["topic"].replace("|", " ")
        findings.append(
            Finding(
                id=finding_id("knowledge_gap", item["topic"]),
                kind="knowledge_gap",
                severity=severity,
                title=f"Questions about \"{label}\" rarely get an answer",
                explanation=(
                    f"{n} of {_plural(item['decisions'], 'decision')} "
                    f"({_pct(item['gap_rate'])}) on the topic \"{label}\" ended without "
                    f"a usable answer: {item['abstains']} ABSTAIN and "
                    f"{item['escalations']} ESCALATE."
                ),
                metric=Metric(name="gap_rate", value=item["gap_rate"],
                              numerator=n, denominator=item["decisions"]),
                subjects=[Subject(type="Topic", id=item["topic"])],
                request_ids=item["request_ids"],
                query="decision_overview",
                attribution="direct",
                details={"abstains": item["abstains"], "escalations": item["escalations"],
                         "sample_queries": item["sample_queries"]},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Escalation root causes and uncertainty sources
# ---------------------------------------------------------------------------
def escalation_root_cause_findings(
    root_cause_rows: Sequence[Row], overview: Sequence[Row]
) -> List[Finding]:
    """Documents that stored reasons point at (BECAUSE -> Reason -> ABOUT ->
    Evidence -> FROM -> Document, or via a claim the evidence contradicts)
    across >= 2 escalations."""
    total = sum(1 for r in overview if r.get("decision") == "ESCALATE")
    by_doc: Dict[str, Row] = {}
    for row in _complete(root_cause_rows, "request_id", "doc_id"):
        doc = by_doc.setdefault(row["doc_id"], {"ids": set(), "codes": defaultdict(set)})
        doc["ids"].add(row["request_id"])
        if row.get("code"):
            doc["codes"][row["code"]].add(row["request_id"])
    findings: List[Finding] = []
    for doc_id, doc in by_doc.items():
        n = len(doc["ids"])
        if not rules.is_recurring(n):
            continue
        denominator = max(total, n)
        share = rules.rate(n, denominator)
        label = _doc_label(doc_id)
        codes = sorted(doc["codes"].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        code_text = ", ".join(f"{code} in {len(ids)}" for code, ids in codes)
        findings.append(
            Finding(
                id=finding_id("escalation_root_cause", doc_id),
                kind="escalation_root_cause",
                severity=rules.root_cause_severity(n, share),
                title=f"{label} is behind {_plural(n, 'escalation')}",
                explanation=(
                    f"The stored reasons of {n} of {_plural(denominator, 'escalation')} "
                    f"({_pct(share)}) point at evidence from {label} ({code_text}). "
                    f"Fixing this one document would address all {n}."
                ),
                metric=Metric(name="escalation_share", value=share,
                              numerator=n, denominator=denominator),
                subjects=[Subject(type="Document", id=doc_id)],
                request_ids=_ids(doc["ids"]),
                query="escalation_root_causes",
                attribution="direct",
                details={"reason_codes": {code: len(ids) for code, ids in codes}},
            )
        )
    return findings


def uncertainty_source_findings(overview: Sequence[Row]) -> List[Finding]:
    """Reason codes that account for a large share of ABSTAIN/ESCALATE."""
    gap_rows = [
        r for r in _complete(overview, "request_id")
        if r.get("decision") in rules.GAP_DECISIONS
    ]
    total = len(gap_rows)
    by_code: Dict[str, set] = defaultdict(set)
    for row in gap_rows:
        for code in row.get("reason_codes") or []:
            by_code[code].add(row["request_id"])
    findings: List[Finding] = []
    for code, ids in by_code.items():
        n = len(ids)
        if not rules.is_recurring(n):
            continue
        share = rules.rate(n, total)
        severity = rules.uncertainty_severity(share)
        if severity is None:
            continue
        findings.append(
            Finding(
                id=finding_id("uncertainty_source", code),
                kind="uncertainty_source",
                severity=severity,
                title=f"{code} drives withheld answers",
                explanation=(
                    f"{code} was recorded on {n} of the {_plural(total, 'decision')} "
                    f"({_pct(share)}) that ended in ABSTAIN or ESCALATE."
                ),
                metric=Metric(name="reason_code_share", value=share,
                              numerator=n, denominator=total),
                subjects=[Subject(type="ReasonCode", id=code)],
                request_ids=_ids(ids),
                query="decision_overview",
                attribution="direct",
            )
        )
    return findings


def sort_findings(findings: Iterable[Finding]) -> List[Finding]:
    return sorted(
        findings,
        key=lambda f: (rules.severity_rank(f.severity), -f.metric.numerator, f.kind, f.id),
    )


def sufficiency(graph_decisions: int, total_decisions: int, graph_available: bool) -> Row:
    needed = max(rules.MIN_GRAPH_DECISIONS - graph_decisions, 0)
    if not graph_available:
        message = (
            "The decision graph is unavailable, so cross-decision findings cannot be "
            "computed (at least "
            f"{rules.MIN_GRAPH_DECISIONS} graph decisions are needed once it is back); "
            "decision and reason distributions come from the audit log."
        )
    elif needed:
        message = (
            f"Only {_plural(graph_decisions, 'decision')} in the decision graph; "
            f"{needed} more {'is' if needed == 1 else 'are'} needed (minimum "
            f"{rules.MIN_GRAPH_DECISIONS}) before patterns are meaningful."
        )
    else:
        message = (
            f"{_plural(graph_decisions, 'decision')} in the decision graph; a pattern "
            f"is reported only when at least {rules.MIN_DECISIONS_FOR_FINDING} distinct "
            f"decisions show it."
        )
    return {
        "total_decisions": total_decisions,
        "graph_decisions": graph_decisions,
        "min_required": rules.MIN_GRAPH_DECISIONS,
        "sufficient": graph_available and needed == 0,
        "needed": needed if graph_available else rules.MIN_GRAPH_DECISIONS,
        "message": message,
    }


def split_blast_radius(doc_id: str, usage: Sequence[Row]) -> Row:
    """Decisions that relied on a document (a SUPPORTED claim is
    SUPPORTED_BY its evidence) vs. those that only retrieved it."""
    relied: List[Row] = []
    retrieved_only: List[Row] = []
    seen: set = set()
    for row in usage:
        if row.get("doc_id") != doc_id or not row.get("request_id") or row["request_id"] in seen:
            continue
        seen.add(row["request_id"])
        entry = {
            "request_id": row["request_id"],
            "decision": row.get("decision"),
            "created_at": row.get("created_at"),
            "supported_claims": int(row.get("supported_by_doc") or 0),
            "contradicted_claims": int(row.get("contradicted_by_doc") or 0),
            "claims": list(row.get("supported_claim_texts") or []),
            "via": sorted(row.get("vias") or []),
        }
        (relied if entry["supported_claims"] > 0 else retrieved_only).append(entry)
    for group in (relied, retrieved_only):
        group.sort(key=lambda e: e["request_id"])
    shown = sum(1 for e in relied if e["decision"] in rules.SHOWN_DECISIONS)
    return {
        "doc_id": doc_id,
        "total_decisions": len(seen),
        "relied_on": {"count": len(relied), "decisions": relied},
        "retrieved_only": {"count": len(retrieved_only), "decisions": retrieved_only},
        "explanation": (
            f"{_plural(len(seen), 'decision')} retrieved {_doc_label(doc_id)}: "
            f"{len(relied)} relied on it (a supported claim cites its evidence; "
            f"{shown} of those showed an answer) and {len(retrieved_only)} only "
            f"retrieved it. If this document is wrong, the {len(relied)} relying "
            f"decisions are the ones to re-check."
        ),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
_PUBLIC = lambda row: {k: v for k, v in row.items() if not k.startswith("_")}  # noqa: E731


class IntelligenceService:
    def __init__(
        self,
        driver: Any = None,
        audit: Optional[AuditReader] = None,
        topic_fn: Optional[TopicFn] = None,
        database: Optional[str] = None,
        graph_known_down: bool = False,
    ):
        self.driver = driver
        #: Skip Neo4j entirely (it failed moments ago); set by the routes.
        self.graph_known_down = graph_known_down
        #: Set when a read failed because Neo4j could not be reached.
        self.unreachable = False
        self.audit = audit or AuditReader()
        self.topic_fn = topic_fn if topic_fn is not None else default_topic_fn()
        self.database = database

    # -- graph access ---------------------------------------------------
    def _q(self, name: str, prefix: str = "", **params: Any) -> List[Row]:
        if self.driver is None:
            raise GraphUnavailable(NOT_CONFIGURED)
        if self.graph_known_down:
            raise GraphUnavailable(UNREACHABLE, unreachable=True)
        try:
            return queries.run(
                self.driver, name, {"prefix": prefix or "", **params}, database=self.database
            )
        except Exception as exc:  # any driver failure degrades, never 500s
            logger.warning("Intelligence query %s failed: %s", name, exc)
            if _is_connectivity_error(exc):
                self.unreachable = True
                raise GraphUnavailable(UNREACHABLE, unreachable=True) from exc
            raise GraphUnavailable(
                f"The decision graph could not be read (query {name} failed with "
                f"{type(exc).__name__})."
            ) from exc

    def _audit_queries(self, overview: Sequence[Row]) -> Dict[str, str]:
        missing = [
            r["request_id"] for r in overview
            if not r.get("topic") or not r.get("query_preview")
        ]
        if not missing:
            return {}
        try:
            return self.audit.queries_by_request_id(missing)
        except AuditUnavailable:
            return {}

    # -- endpoints ------------------------------------------------------
    def documents(self, prefix: str = "") -> Row:
        overview = self._q("decision_overview", prefix)
        usage = self._q("decision_document_usage", prefix)
        conflicts = self._q("conflict_edges", prefix)
        superseded = supersession_map(self._q("documents"), self._q("supersedes_edges"))
        table = build_document_table(overview, usage, conflicts, superseded)
        return {
            "items": [_PUBLIC(r) for r in table],
            "definitions": {
                "decisions": "decisions that retrieved the document",
                "supported_claims": "SUPPORTED claims with a SUPPORTED_BY edge to its evidence",
                "contradicted_claims": "claims with a CONTRADICTED_BY edge to its evidence",
                "unsupported_or_contradicted_claims":
                    "claims not SUPPORTED in the decisions that retrieved it (co-occurrence)",
                "unsupported_rate":
                    "unsupported_or_contradicted_claims / claims_in_decisions",
            },
        }

    def contradictions(self, prefix: str = "") -> Row:
        pairs = build_contradiction_pairs(
            self._q("conflict_edges", prefix), self._q("decision_document_usage", prefix)
        )
        return {"items": pairs}

    def stale_usage(self, prefix: str = "") -> Row:
        items, exclusions = build_stale_usage(
            self._q("decision_document_usage", prefix),
            self._q("documents"),
            self._q("supersedes_edges"),
        )
        return {"items": items, "excluded": [e.model_dump() for e in exclusions]}

    def knowledge_gaps(self, prefix: str = "") -> Row:
        overview = self._q("decision_overview", prefix)
        items, exclusions = build_knowledge_gaps(
            overview, self._audit_queries(overview), self.topic_fn
        )
        return {
            "items": items,
            "min_decisions_per_topic": rules.MIN_DECISIONS_FOR_FINDING,
            "excluded": [e.model_dump() for e in exclusions],
        }

    def blast_radius(self, doc_id: str, prefix: str = "") -> Optional[Row]:
        found = self._q("document_by_id", doc_id=doc_id)
        if not found:
            return None
        usage = self._q("decision_document_usage", prefix, doc_id=doc_id)
        result = split_blast_radius(doc_id, usage)
        result["document"] = found[0]
        return result

    def trends(self, bucket: str = "day", prefix: str = "") -> Row:
        return {"bucket": bucket, "items": self.audit.trends(bucket, prefix or "")}

    def summary(self, prefix: str = "") -> Row:
        prefix = prefix or ""
        audit_state: Row = {"available": True}
        try:
            decision_distribution = self.audit.decision_distribution(prefix)
            reason_distribution = self.audit.reason_distribution(prefix)
        except AuditUnavailable as exc:
            decision_distribution, reason_distribution = {}, {}
            audit_state = {"available": False, "reason": str(exc)}
        total = sum(decision_distribution.values())

        graph_state: Row = {"available": True}
        findings: List[Finding] = []
        exclusions: List[Exclusion] = []
        graph_decisions = 0
        try:
            count_rows = self._q("graph_decision_count", prefix)
            graph_decisions = int((count_rows[0].get("n") if count_rows else 0) or 0)
            overview = self._q("decision_overview", prefix)
            usage = self._q("decision_document_usage", prefix)
            conflicts = self._q("conflict_edges", prefix)
            documents = self._q("documents")
            supersedes = self._q("supersedes_edges")
            root_causes = self._q("escalation_root_causes", prefix)

            superseded = supersession_map(documents, supersedes)
            table = build_document_table(overview, usage, conflicts, superseded)
            pairs = build_contradiction_pairs(conflicts, usage)
            stale, stale_excl = build_stale_usage(usage, documents, supersedes)
            gaps, gap_excl = build_knowledge_gaps(
                overview, self._audit_queries(overview), self.topic_fn
            )
            exclusions = stale_excl + gap_excl
            findings = sort_findings(
                unsupported_source_findings(table)
                + contradiction_findings(pairs)
                + stale_findings(stale)
                + knowledge_gap_findings(gaps)
                + escalation_root_cause_findings(root_causes, overview)
                + uncertainty_source_findings(overview)
            )
        except GraphUnavailable as exc:
            graph_state = {"available": False, "reason": str(exc)}
            findings, exclusions, graph_decisions = [], [], 0
        except Exception as exc:  # unexpected stored data: keep /summary at 200
            logger.exception("Intelligence analysis failed")
            graph_state = {"available": True,
                           "analysis_error": f"Findings could not be derived "
                                             f"({type(exc).__name__}); see server log."}
            findings, exclusions = [], []

        return {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "data": sufficiency(graph_decisions, total, graph_state["available"]),
            "decision_distribution": decision_distribution,
            "reason_distribution": reason_distribution,
            "findings": [f.model_dump() for f in findings],
            "graph": graph_state,
            "audit": audit_state,
            "excluded": [e.model_dump() for e in exclusions],
            "scope": {"request_prefix": prefix or None},
        }
