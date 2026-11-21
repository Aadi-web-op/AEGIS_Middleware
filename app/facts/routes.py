"""Fact Lock API.

GET    /v1/facts                  locked facts and level names
POST   /v1/facts                  lock a new fact                      (admin)
PUT    /v1/facts/{key}            new version of a fact + impact       (admin)
DELETE /v1/facts/{key}            retire a fact                        (admin)
GET    /v1/facts/{key}/history    every version of a fact
GET    /v1/facts/{key}/impact     re-check past answers against it
POST   /v1/facts/check            check one answer, no models needed   (reviewer, service)
POST   /v1/facts/suggest          candidate facts from a document text (admin)
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.facts.lock import FactLock, _sentences, _tokens
from app.facts.store import LEVELS, Fact, FactStore
from app.facts.values import KINDS, extract_values
from app.schemas import EvidenceItem

router = APIRouter(prefix="/v1/facts", tags=["Fact Lock"])

IMPACT_SCAN_LIMIT = 20000


class FactIn(BaseModel):
    key: str = Field(min_length=2, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    kind: str
    value: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=1, le=4)
    unit: str | None = Field(default=None, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    source: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=60)


class FactUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=80)
    level: int | None = Field(default=None, ge=1, le=4)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    unit: str | None = Field(default=None, max_length=40)
    aliases: list[str] | None = Field(default=None, max_length=20)
    source: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=60)


class CheckIn(BaseModel):
    query: str = ""
    answer: str = Field(min_length=1)
    evidence: list[EvidenceItem] | None = None


class SuggestIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    source: str | None = None
    version: str | None = None


def _store(request: Request) -> FactStore:
    store = getattr(request.app.state, "fact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Fact Lock is not configured.")
    return store


def _actor(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    return getattr(principal, "email", None) or getattr(principal, "role", None)


def _graph(request: Request):
    return getattr(request.app.state, "fact_graph", None)


@router.get("")
def list_facts(request: Request):
    store = _store(request)
    return {"facts": [f.public() for f in store.active()],
            "levels": {str(k): v for k, v in LEVELS.items()}, "kinds": list(KINDS)}


@router.post("", status_code=201)
def create_fact(payload: FactIn, request: Request):
    store = _store(request)
    fact = Fact(**payload.model_dump(), created_by=_actor(request))
    try:
        created = store.create(fact)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if _graph(request):
        _graph(request).upsert(created)
    return created.public()


@router.put("/{key}")
def update_fact(key: str, payload: FactUpdate, request: Request):
    store = _store(request)
    try:
        old, new = store.update(key, created_by=_actor(request), **payload.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if _graph(request):
        _graph(request).upsert(new, supersedes=old)
    impact = past_answer_impact(request, new.key)
    return {"previous": old.public(), "current": new.public(), "impact": impact}


@router.delete("/{key}")
def retire_fact(key: str, request: Request):
    if not _store(request).retire(key):
        raise HTTPException(status_code=404, detail=f"no active fact {key!r}")
    return {"retired": key}


@router.get("/{key}/history")
def fact_history(key: str, request: Request):
    history = _store(request).history(key)
    if not history:
        raise HTTPException(status_code=404, detail=f"no fact {key!r}")
    return {"key": key, "versions": [f.public() for f in history]}


@router.get("/{key}/impact")
def fact_impact(key: str, request: Request):
    if _store(request).get(key) is None:
        raise HTTPException(status_code=404, detail=f"no active fact {key!r}")
    return past_answer_impact(request, key)


@router.post("/check")
def check_answer(payload: CheckIn, request: Request):
    lock = FactLock(_store(request))
    result = lock.check(payload.query, payload.answer, payload.evidence)
    return {
        "decision_floor": result.floor.value if result.floor else None,
        "requires_approval": result.requires_approval,
        "corrected_answer": result.corrected_answer,
        "checks": [c.model_dump() for c in result.checks],
        "notes": result.notes,
    }


@router.post("/suggest")
def suggest_facts(payload: SuggestIn):
    """Sentences that state exactly one value: candidates a person can approve."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for sentence in _sentences(payload.text):
        text = sentence.text.strip()
        for kind in ("money", "percent", "duration", "date"):
            values = extract_values(text, kind)
            if len(values) != 1:
                continue
            words = [w for w in _tokens(text[: values[0].start]) if not w.isdigit()][-4:]
            label = " ".join(words) or text[:40]
            key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:64] or "fact"
            if key in seen:
                continue
            seen.add(key)
            out.append({"key": key, "label": label, "kind": kind, "value": values[0].text,
                        "level": 3 if kind == "money" else 2, "sentence": text,
                        "source": payload.source, "version": payload.version})
            break
        if len(out) >= 50:
            break
    return {"candidates": out}


# ---------------------------------------------------------------- impact
def past_answer_impact(request: Request, key: str) -> dict:
    """Re-check every stored answer against the current value of one fact.

    Works on history recorded before the fact was locked too: the audit log
    keeps each question and answer, and matching is deterministic.
    """
    store = _store(request)
    fact = store.get(key)
    audit = getattr(request.app.state, "audit_logger", None)
    if fact is None or audit is None:
        return {"key": key, "scanned": 0, "affected": [], "counts": {}}

    lock = FactLock(store)
    weights = lock._weights(store.active())
    locked = fact.parsed()
    older = [f for f in store.history(key) if f.status == "superseded"]

    affected, counts, scanned, offset = [], {"still_correct": 0, "outdated": 0, "wrong": 0}, 0, 0
    while scanned < IMPACT_SCAN_LIMIT:
        rows = audit.list_records(limit=500, offset=offset)
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            scanned += 1
            answer = row.get("answer") or ""
            if not answer:
                continue
            found = lock._stated(fact, answer, row.get("query") or "", weights)
            if not found or not found[0]:
                continue
            stated = next((v for v in found[0] if v.comparable(locked)), None)
            if stated is None:
                continue
            if stated.same_as(locked):
                counts["still_correct"] += 1
                continue
            old = next((f for f in older if _same(f, stated)), None)
            status = "outdated" if old else "wrong"
            counts[status] += 1
            affected.append({
                "request_id": row.get("request_id"),
                "timestamp": row.get("timestamp"),
                "query": row.get("query"),
                "answer": answer[:400],
                "stated": stated.text,
                "status": status,
                "old_version": old.version if old else None,
                "original_decision": row.get("decision"),
                "action": "Contact the person and send the corrected value"
                          if row.get("decision") in ("ANSWER", "CAVEAT")
                          else "Was not delivered; no correction needed",
            })
    return {
        "key": key,
        "label": fact.label,
        "current": fact.value,
        "version": fact.version,
        "level": fact.level,
        "scanned": scanned,
        "counts": counts,
        "delivered_wrong": sum(1 for a in affected if a["original_decision"] in ("ANSWER", "CAVEAT")),
        "affected": affected,
    }


def _same(fact: Fact, value) -> bool:
    try:
        return fact.parsed().same_as(value)
    except ValueError:
        return False
