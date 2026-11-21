import { lazy, Suspense } from "react";
import { display, score, type AffectedDecision, type RecordData } from "@/lib/aegis-api";
const TraceGraph = lazy(() =>
  import("./graph-view").then((module) => ({ default: module.TraceGraph })),
);

/**
 * Finale feature 3: blast-radius highlight. The changed document and every
 * past decision that relied on the old version, drawn as a lit-up path.
 */
export function BlastRadius({
  title,
  newDocument,
  oldDocument,
  decisions,
}: {
  title: string;
  newDocument?: string;
  oldDocument: string;
  decisions: AffectedDecision[];
}) {
  const nodes: RecordData[] = [
    { id: oldDocument, type: "Document", label: `Old: ${oldDocument}`, impacted: true },
    ...decisions.map((d) => ({
      id: `decision:${d.request_id}`,
      type: "Decision",
      label: `${d.decision ?? "Decision"} · ${d.request_id.slice(0, 8)}`,
      request_id: d.request_id,
      decision: d.decision,
      answerability_score: d.score,
      impacted: true,
    })),
  ];
  const edges: RecordData[] = decisions.map((d) => ({
    type: "USES_DOCUMENT",
    from: `decision:${d.request_id}`,
    to: oldDocument,
    impacted: true,
  }));
  if (newDocument) {
    nodes.unshift({ id: newDocument, type: "Document", label: `New: ${newDocument}` });
    edges.push({ type: "SUPERSEDES", from: newDocument, to: oldDocument, impacted: true });
  }
  return (
    <div className="blast-radius mt-4" aria-label="Blast radius">
      <p className="blast-title">
        <span className="decision-escalate">●</span> {title}: <strong>{decisions.length}</strong>{" "}
        past decision(s) at risk
      </p>
      {decisions.length > 0 && (
        <>
          <Suspense fallback={<p className="minor-label">Loading graph…</p>}>
            <TraceGraph nodes={nodes} edges={edges} />
          </Suspense>
          <ul className="blast-list">
            {decisions.map((d) => (
              <li key={d.request_id}>
                <span className="font-mono">{d.request_id}</span>
                <span className={`decision-${display(d.decision).toLowerCase()}`}>
                  {display(d.decision)}
                </span>
                <span>{score(d.score)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
