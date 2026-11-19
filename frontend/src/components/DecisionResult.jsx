/**
 * DecisionResult – the one view of an evaluation, used by Live evaluation
 * and by the Decision history drawer.
 *
 * Reading order: decision → question → answer with claims highlighted →
 * claims and the evidence each used → why → graph → technical details.
 */
import { useMemo, useState } from "react";
import { CLAIM_CLS, DASH, DECISION_META, decisionCls, humanCode, isNum, ms, score } from "../format.js";
import { normaliseGraph } from "../graphUtils.js";
import { href } from "../router.js";
import { ClaimChip, CopyButton, DecisionBadge, Notice, Tag } from "../ui/index.jsx";
import GraphCanvas, { GraphLegend } from "./GraphCanvas.jsx";
import GraphInspector from "./GraphInspector.jsx";

const SIGNALS = ["relevance", "entailment", "contradiction", "freshness", "completeness", "ambiguity"];

// ── Claim → answer span matching ──────────────────────────────────────────

function findSpan(answer, claim) {
  if (!answer || !claim) return null;
  const direct = answer.indexOf(claim);
  if (direct >= 0) return [direct, direct + claim.length];
  // Whitespace/case-insensitive match, ignoring a trailing full stop.
  const esc = claim
    .trim()
    .replace(/[.。]\s*$/, "")
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\s+/g, "\\s+");
  if (!esc) return null;
  try {
    const m = new RegExp(esc, "i").exec(answer);
    if (m) {
      let end = m.index + m[0].length;
      if (answer[end] === ".") end += 1;
      return [m.index, end];
    }
  } catch {
    /* fall through */
  }
  return null;
}

export function segmentAnswer(answer, claims) {
  if (!answer) return { segments: [], matched: 0 };
  const spans = [];
  (claims ?? []).forEach((c, i) => {
    let s = null;
    if (Array.isArray(c.span) && c.span.length === 2 && c.span[0] >= 0 && c.span[1] <= answer.length && c.span[0] < c.span[1]) {
      s = c.span;
    } else {
      s = findSpan(answer, c.claim);
    }
    if (s) spans.push({ start: s[0], end: s[1], index: i });
  });
  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  const segments = [];
  let pos = 0;
  let matched = 0;
  for (const s of spans) {
    if (s.start < pos) continue; // overlapping span: keep the first
    if (s.start > pos) segments.push({ text: answer.slice(pos, s.start) });
    segments.push({ text: answer.slice(s.start, s.end), index: s.index });
    pos = s.end;
    matched += 1;
  }
  if (pos < answer.length) segments.push({ text: answer.slice(pos) });
  return { segments, matched };
}

function claimEvidence(c) {
  const all = Array.isArray(c.evidence_indices) ? c.evidence_indices : [];
  const sup = Array.isArray(c.supporting_evidence_indices)
    ? c.supporting_evidence_indices
    : c.status === "SUPPORTED"
      ? all
      : [];
  const con = Array.isArray(c.contradicting_evidence_indices)
    ? c.contradicting_evidence_indices
    : c.status === "CONTRADICTED"
      ? all
      : [];
  const other = all.filter((i) => !sup.includes(i) && !con.includes(i));
  return { sup, con, other };
}

// ── Score scale ───────────────────────────────────────────────────────────

function ScoreScale({ value, thresholds, decision }) {
  const ticks = thresholds
    ? [
        ["escalate", thresholds.escalate],
        ["caveat", thresholds.caveat],
        ["answer", thresholds.answer],
      ].filter(([, v]) => isNum(v))
    : [];
  return (
    <div className="scale">
      <div className="scale__track">
        {ticks.map(([name, v]) => (
          <span key={name} className="scale__tick" style={{ left: `${v * 100}%` }} />
        ))}
        {isNum(value) && (
          <span className={`scale__marker scale__marker--${decisionCls(decision)}`} style={{ left: `${value * 100}%` }} />
        )}
      </div>
      {ticks.length > 0 && (
        <div className="scale__labels">
          {ticks.map(([name, v]) => (
            <span key={name} style={{ left: `${v * 100}%` }}>
              {name} ≥ {v.toFixed(2)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Sections ──────────────────────────────────────────────────────────────

function Section({ title, aside, children }) {
  return (
    <section className="result-section">
      <div className="result-section__head">
        <h3>{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function EvidenceRef({ i, tone, active, onHover }) {
  return (
    <span
      className={`eref eref--${tone}${active ? " is-active" : ""}`}
      onMouseEnter={() => onHover?.(i)}
      onMouseLeave={() => onHover?.(null)}
    >
      E{i + 1}
    </span>
  );
}

function comparisonText(f) {
  if (!isNum(f.threshold)) return DASH;
  const sym = f.comparison === "below" ? "<" : f.comparison === "above" ? ">" : f.comparison === "at_or_above" ? "≥" : f.comparison ?? "";
  return `${sym} ${f.threshold.toFixed(2)}`;
}

function Why({ response }) {
  const ex = response.explanation;
  const reasons = response.reasons ?? [];
  const factors = ex?.factors ?? [];
  return (
    <Section title="Why this decision">
      {ex?.summary ? (
        <p className="why__summary">{ex.summary}</p>
      ) : (
        reasons.length === 0 && <p className="muted">No reasons were returned for this decision.</p>
      )}
      {ex?.decisive_rule && (
        <p className="why__rule">
          Decisive rule <span className="mono">{ex.decisive_rule}</span>
        </p>
      )}
      {factors.length > 0 && (
        <div className="table-wrap">
          <table className="table table--compact">
            <thead>
              <tr>
                <th>Signal</th>
                <th className="num">Value</th>
                <th className="num">Threshold</th>
                <th>Effect</th>
                <th>Explanation</th>
              </tr>
            </thead>
            <tbody>
              {factors.map((f, i) => (
                <tr key={`${f.signal}-${i}`}>
                  <td className="mono">{f.signal}</td>
                  <td className="num">{score(f.value)}</td>
                  <td className="num">{comparisonText(f)}</td>
                  <td>{f.effect ? <span className={`effect effect--${decisionCls(f.effect)}`}>{f.effect}</span> : DASH}</td>
                  <td className="wrap">{f.message ?? DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reasons.length > 0 && (
        <ul className="reason-list">
          {reasons.map((r, i) => (
            <li key={`${r.code}-${i}`}>
              <Tag>{r.code}</Tag>
              <span>{r.message}</span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Technical({ response, profile }) {
  const unavailable = new Set(response.unavailable_signals ?? []);
  return (
    <details className="technical">
      <summary>Technical details</summary>
      <div className="technical__grid">
        <div>
          <h4>Signals</h4>
          <table className="table table--compact table--plain">
            <tbody>
              {SIGNALS.map((s) => {
                const v = response.signals?.[s];
                return (
                  <tr key={s}>
                    <td className="mono">{s}</td>
                    <td className="num">{isNum(v) ? v.toFixed(3) : <span className="muted">{unavailable.has(s) || v === null ? "unavailable" : DASH}</span>}</td>
                    <td className="bar-cell">
                      {isNum(v) && (
                        <span className="minibar">
                          <span style={{ width: `${v * 100}%` }} />
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div>
          <h4>Request</h4>
          <dl className="kv kv--tight">
            <div className="kv__row">
              <dt>request_id</dt>
              <dd className="mono">
                {response.request_id ?? DASH} {response.request_id && <CopyButton value={response.request_id} label="Copy request id" />}
              </dd>
            </div>
            <div className="kv__row">
              <dt>profile</dt>
              <dd className="mono">{profile ?? DASH}</dd>
            </div>
            <div className="kv__row">
              <dt>policy_version</dt>
              <dd className="mono">{response.policy_version ?? DASH}</dd>
            </div>
            <div className="kv__row">
              <dt>latency</dt>
              <dd className="mono">{ms(response.latency_ms)}</dd>
            </div>
            <div className="kv__row">
              <dt>recommended_action</dt>
              <dd className="mono">{response.recommended_action ?? DASH}</dd>
            </div>
            <div className="kv__row">
              <dt>degraded</dt>
              <dd className="mono">{response.degraded === undefined ? DASH : String(response.degraded)}</dd>
            </div>
          </dl>
        </div>
      </div>
      <details className="technical__raw">
        <summary>Raw response JSON</summary>
        <pre className="code">{JSON.stringify(response, null, 2)}</pre>
      </details>
    </details>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────

export default function DecisionResult({ response, request, config, showGraph = true }) {
  const [activeClaim, setActiveClaim] = useState(null);
  const [activeEvidence, setActiveEvidence] = useState(null);
  const [selected, setSelected] = useState(null);

  const graph = useMemo(() => normaliseGraph(response?.trace), [response]);
  const decisionNode = graph.nodes.find((n) => n.type === "Decision");

  const evidence = useMemo(() => {
    if (request?.evidence?.length) {
      return request.evidence.map((e, i) => ({ index: i, text: e.text, source: e.source, version: e.version, date: e.date, full: true }));
    }
    return graph.nodes
      .filter((n) => n.type === "Evidence")
      .map((n, i) => ({
        index: Number.isFinite(Number(n.props.evidence_index)) ? Number(n.props.evidence_index) : i,
        text: n.props.preview ?? n.props.text ?? "",
        source: n.props.source,
        version: n.props.version,
        date: n.props.date,
        full: false,
      }))
      .sort((a, b) => a.index - b.index);
  }, [request, graph]);

  if (!response) return null;

  const claims = response.claims ?? [];
  const answer = request?.answer ?? response.answer ?? null;
  const query = request?.query ?? null;
  const profile = request?.profile ?? decisionNode?.props.profile ?? null;
  const thresholds = config?.profiles?.[profile]?.thresholds ?? null;
  const headline = response.headline ?? response.trace?.headline ?? decisionNode?.props.headline ?? null;
  const meta = DECISION_META[response.decision];
  const { segments, matched } = segmentAnswer(answer, claims);

  const usedBy = (ei) =>
    claims
      .map((c, ci) => {
        const { sup, con, other } = claimEvidence(c);
        if (sup.includes(ei)) return { ci, tone: "answer" };
        if (con.includes(ei)) return { ci, tone: "escalate" };
        if (other.includes(ei)) return { ci, tone: "abstain" };
        return null;
      })
      .filter(Boolean);

  const activeClaimEvidence =
    activeClaim !== null && claims[activeClaim]
      ? new Set([...claimEvidence(claims[activeClaim]).sup, ...claimEvidence(claims[activeClaim]).con, ...claimEvidence(claims[activeClaim]).other])
      : null;

  return (
    <div className="result">
      <div className={`verdict verdict--${decisionCls(response.decision)}`}>
        <div className="verdict__main">
          <div className="verdict__row">
            <DecisionBadge decision={response.decision} size="lg" />
            <span className="verdict__action">{meta?.action ?? humanCode(response.recommended_action)}</span>
            {response.degraded && <Tag tone="caveat" title="One or more signals could not be computed">degraded</Tag>}
          </div>
          {headline && <p className="verdict__headline">{headline}</p>}
        </div>
        <div className="verdict__score">
          <div className="verdict__score-row">
            <span className="label">Answerability score</span>
            <span className="verdict__score-value">{score(response.answerability_score)}</span>
          </div>
          <ScoreScale value={response.answerability_score} thresholds={thresholds} decision={response.decision} />
          {thresholds && profile && (
            <p className="verdict__score-note">
              Thresholds for the <span className="mono">{profile}</span> profile. A veto rule can override the score.
            </p>
          )}
        </div>
      </div>

      {query && (
        <Section title="Question">
          <p className="result__question">{query}</p>
        </Section>
      )}

      {answer && (
        <Section
          title="Answer under evaluation"
          aside={
            claims.length > 0 && (
              <span className="claim-key">
                <span className="claim-key__item claim-key__item--answer">supported</span>
                <span className="claim-key__item claim-key__item--caveat">unsupported</span>
                <span className="claim-key__item claim-key__item--escalate">contradicted</span>
              </span>
            )
          }
        >
          <p className="answer-text">
            {segments.map((seg, i) =>
              seg.index === undefined ? (
                <span key={i}>{seg.text}</span>
              ) : (
                <mark
                  key={i}
                  className={`claim-mark claim-mark--${CLAIM_CLS[claims[seg.index].status] ?? "abstain"}${activeClaim === seg.index ? " is-active" : ""}`}
                  onMouseEnter={() => setActiveClaim(seg.index)}
                  onMouseLeave={() => setActiveClaim(null)}
                  title={`Claim ${seg.index + 1}: ${String(claims[seg.index].status).toLowerCase()}`}
                >
                  {seg.text}
                  <sup>{seg.index + 1}</sup>
                </mark>
              )
            )}
          </p>
          {claims.length > 0 && matched < claims.length && (
            <p className="muted small">
              {matched === 0
                ? "Claims were rephrased during extraction, so they are listed below rather than highlighted in place."
                : `${claims.length - matched} of ${claims.length} claims were rephrased during extraction and are listed below only.`}
            </p>
          )}
          {response.caveat_text && (
            <Notice tone="caveat" title="Caveat returned to the user">
              {response.caveat_text}
            </Notice>
          )}
          {response.clarifying_question && (
            <Notice tone="neutral" title="Clarifying question">
              {response.clarifying_question}
            </Notice>
          )}
        </Section>
      )}

      <div className="result__cols">
        <Section title={`Claims (${claims.length})`}>
          {claims.length === 0 ? (
            <p className="muted">No claims were extracted from the answer.</p>
          ) : (
            <ol className="claim-list">
              {claims.map((c, i) => {
                const { sup, con, other } = claimEvidence(c);
                const lit = activeClaim === i || (activeEvidence !== null && [...sup, ...con, ...other].includes(activeEvidence));
                return (
                  <li
                    key={i}
                    className={`claim claim--${CLAIM_CLS[c.status] ?? "abstain"}${lit ? " is-active" : ""}`}
                    onMouseEnter={() => setActiveClaim(i)}
                    onMouseLeave={() => setActiveClaim(null)}
                  >
                    <div className="claim__head">
                      <span className="claim__n">{i + 1}</span>
                      <ClaimChip status={c.status} />
                      <span className="claim__support">
                        support <span className="mono">{score(c.support)}</span>
                      </span>
                    </div>
                    <p className="claim__text">{c.claim}</p>
                    {c.reason && <p className="claim__reason">{c.reason}</p>}
                    <p className="claim__refs">
                      {sup.length > 0 && (
                        <span>
                          Supported by {sup.map((e) => <EvidenceRef key={e} i={e} tone="answer" onHover={setActiveEvidence} />)}
                        </span>
                      )}
                      {con.length > 0 && (
                        <span>
                          Contradicted by {con.map((e) => <EvidenceRef key={e} i={e} tone="escalate" onHover={setActiveEvidence} />)}
                        </span>
                      )}
                      {other.length > 0 && (
                        <span>
                          Closest evidence {other.map((e) => <EvidenceRef key={e} i={e} tone="abstain" onHover={setActiveEvidence} />)}
                        </span>
                      )}
                      {sup.length + con.length + other.length === 0 && <span className="muted">No evidence passage matched this claim.</span>}
                    </p>
                  </li>
                );
              })}
            </ol>
          )}
        </Section>

        <Section title={`Evidence (${evidence.length})`}>
          {evidence.length === 0 ? (
            <p className="muted">No evidence passages were supplied.</p>
          ) : (
            <ul className="evidence-list">
              {evidence.map((e) => {
                const users = usedBy(e.index);
                const lit = activeEvidence === e.index || activeClaimEvidence?.has(e.index);
                return (
                  <li
                    key={e.index}
                    className={`evidence${lit ? " is-active" : ""}`}
                    onMouseEnter={() => setActiveEvidence(e.index)}
                    onMouseLeave={() => setActiveEvidence(null)}
                  >
                    <div className="evidence__head">
                      <span className="evidence__n">E{e.index + 1}</span>
                      <span className="evidence__src mono">
                        {e.source ?? "no source"}
                        {e.version ? ` @ ${e.version}` : ""}
                      </span>
                      {e.date && <span className="evidence__date mono">{String(e.date)}</span>}
                    </div>
                    <p className="evidence__text">
                      {e.text}
                      {!e.full && e.text?.length >= 118 ? " …" : ""}
                    </p>
                    <p className="evidence__uses">
                      {users.length === 0 ? (
                        <span className="muted">Not cited by any claim</span>
                      ) : (
                        users.map((u) => (
                          <span key={u.ci} className={`eref eref--${u.tone}`}>
                            {u.tone === "answer" ? "supports" : u.tone === "escalate" ? "contradicts" : "near"} claim {u.ci + 1}
                          </span>
                        ))
                      )}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </Section>
      </div>

      <Why response={response} />

      {showGraph && (
        <Section
          title="Decision graph"
          aside={
            response.request_id &&
            graph.nodes.length > 0 && (
              <a className="link" href={href("graph", "decision", response.request_id)}>
                Open in graph explorer
              </a>
            )
          }
        >
          {graph.nodes.length === 0 ? (
            <p className="muted">No decision trace was stored for this evaluation.</p>
          ) : (
            <>
              <div className={selected ? "result-graph has-selection" : "result-graph"}>
                <GraphCanvas graph={graph} selected={selected} onSelect={setSelected} height={Math.min(460, Math.max(260, graph.nodes.length * 34))} />
                {selected && (
                  <div className="result-graph__inspector">
                    <GraphInspector graph={graph} selected={selected} onSelect={setSelected} />
                  </div>
                )}
              </div>
              <GraphLegend />
            </>
          )}
        </Section>
      )}

      <Technical response={response} profile={profile} />
    </div>
  );
}
