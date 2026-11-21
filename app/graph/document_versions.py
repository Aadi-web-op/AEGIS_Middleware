"""Register ingested document revisions and find affected decisions."""

from dataclasses import dataclass
from typing import Any

from app.graph.identity import document_id


@dataclass(frozen=True)
class DocumentRevision:
    source: str
    version: str | None
    content_hash: str
    date: str | None = None

    @property
    def id(self) -> str:
        return document_id(self.source, self.version, self.content_hash)


_LOCK_AND_READ = """
MERGE (source:DocumentSource {name: $source})
SET source.write_lock = coalesce(source.write_lock, 0) + 1
MERGE (incoming:Document {id: $id})
SET incoming.source = $source, incoming.version = $version,
    incoming.content_hash = $content_hash
SET incoming.date = coalesce($date, incoming.date)
WITH source, incoming
OPTIONAL MATCH (previous:Document)
WHERE previous.id = CASE WHEN incoming.ingested = true
                         THEN incoming.previous_document_id ELSE source.head_id END
RETURN incoming.ingested = true AS registered, previous.id AS previous_id,
       previous.version AS previous_version, previous.content_hash AS previous_hash
"""

_SET_HEAD = """
MATCH (source:DocumentSource {name: $source}), (incoming:Document {id: $id})
SET incoming.ingested = true, incoming.previous_document_id = $previous_id,
    source.head_id = incoming.id
WITH incoming
MATCH (previous:Document {id: $previous_id})
MERGE (incoming)-[r:SUPERSEDES]->(previous)
SET r.inferred = false
"""

_AFFECTED_DECISIONS = """
MATCH (doc:Document)
WHERE doc.id = $previous_id OR (
    doc.id = $legacy_id AND NOT EXISTS {
        MATCH (other:Document {source: $source, ingested: true})
        WHERE other.id <> $previous_id
          AND (other.version = $previous_version
               OR (other.version IS NULL AND $previous_version IS NULL))
    }
)
CALL (doc) {
    MATCH (d:Decision)-[use:USES_DOCUMENT]->(doc)
    RETURN d, coalesce(use.evidence_ids, []) AS evidence_ids
    UNION
    MATCH (d:Decision)-[:HAS_CLAIM]->(:Claim)-[:SUPPORTED_BY|CONTRADICTED_BY]
          ->(e:Evidence)-[:FROM]->(doc)
    WHERE e.content_hash IS NULL AND NOT EXISTS { MATCH (d)-[:USES_DOCUMENT]->(doc) }
    RETURN d, [e.id] AS evidence_ids
}
RETURN d.request_id AS request_id, d.decision AS decision,
       d.answerability_score AS score, collect(DISTINCT doc.id) AS document_ids,
       collect(evidence_ids) AS evidence_groups
ORDER BY request_id
"""


def _register(tx: Any, revision: DocumentRevision) -> dict:
    params = {
        "id": revision.id, "source": revision.source, "version": revision.version,
        "content_hash": revision.content_hash, "date": revision.date,
    }
    previous = tx.run(_LOCK_AND_READ, **params).single(strict=True)
    previous_id = previous["previous_id"]
    previous_version = previous["previous_version"]
    if not previous["registered"]:
        tx.run(_SET_HEAD, source=revision.source, id=revision.id, previous_id=previous_id).consume()

    changed = previous_id is not None and previous["previous_hash"] != revision.content_hash
    decisions = []
    if changed:
        records = tx.run(
            _AFFECTED_DECISIONS,
            previous_id=previous_id,
            previous_version=previous_version,
            legacy_id=document_id(revision.source, previous_version),
            source=revision.source,
        )
        for record in records:
            decision = {key: record[key] for key in ("request_id", "decision", "score", "document_ids")}
            decision["evidence_ids"] = sorted({
                evidence_id for group in record["evidence_groups"] for evidence_id in group
            })
            decisions.append(decision)

    return {
        "status": "ok",
        "changed": changed,
        "previous_document_id": previous_id,
        "previous_version": previous_version,
        "affected_request_ids": [decision["request_id"] for decision in decisions],
        "affected_decisions": decisions,
    }


def register_document(driver: Any, revision: DocumentRevision) -> dict:
    """Atomically record the revision and return its blast radius."""
    with driver.session() as session:
        return session.execute_write(_register, revision)
