import { useQuery } from "@tanstack/react-query";
import { Download, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  apiRequest,
  highlightSegments,
  score,
  type CalibrationBand,
  type EvaluationResult,
} from "@/lib/aegis-api";
import { useService } from "./service";
import { SectionHeading } from "./console";

const SIGNAL_LABELS: Record<string, string> = {
  relevance: "Relevance",
  support: "Support (entailment)",
  agreement: "Agreement (no contradiction)",
  freshness: "Freshness",
  completeness: "Completeness",
  clarity: "Clarity (no ambiguity)",
};

/** Finale feature 4: why AEGIS decided, and the smallest change that flips it. */
export function WhyPanel({ result }: { result: EvaluationResult }) {
  const explanation = result.explanation;
  const counterfactual = result.counterfactual;
  const contributions = Object.entries(counterfactual?.contributions ?? {});
  const maxContribution = Math.max(0.0001, ...contributions.map(([, v]) => v));
  if (!explanation && !counterfactual) return null;
  return (
    <section className="why-panel" aria-label="Why this decision">
      <SectionHeading title="Why this decision">
        {explanation?.decisive_rule && (
          <span className="minor-label font-mono">{explanation.decisive_rule}</span>
        )}
      </SectionHeading>
      {explanation?.summary && <p className="result-copy">{explanation.summary}</p>}
      {!!explanation?.factors.length && (
        <ul className="why-factors">
          {explanation.factors.map((f, i) => (
            <li key={i}>
              <span
                className={`decision-${(f.effect ?? "answer").toLowerCase()} font-mono text-[10px]`}
              >
                {f.effect ?? "—"}
              </span>
              <span>{f.message}</span>
            </li>
          ))}
        </ul>
      )}
      {counterfactual?.minimum_change && (
        <div className="why-hint" role="note">
          <Lightbulb size={14} />
          <div>
            <strong>What would change it</strong>
            <p>
              {counterfactual.minimum_change.hint} The score would become{" "}
              {score(counterfactual.minimum_change.resulting_score)}.
            </p>
          </div>
        </div>
      )}
      {counterfactual && !counterfactual.minimum_change && (
        <p className="minor-label mt-3">
          No single-signal change lets this answer through: more than one check must improve.
        </p>
      )}
      {!!contributions.length && (
        <div className="contribution-list" aria-label="Signal contributions to the score">
          <span className="minor-label">Contribution to the answerability score</span>
          {contributions.map(([name, value]) => (
            <div key={name} className="contribution-row">
              <span>{SIGNAL_LABELS[name] ?? name}</span>
              <div className="contribution-track">
                <div style={{ width: `${(value / maxContribution) * 100}%` }} />
              </div>
              <span className="font-mono">+{value.toFixed(3)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** Finale feature 5: the score with an honest empirical band from the dev set. */
export function AnswerabilityBand({ value }: { value: number }) {
  const { base, connected } = useService();
  const query = useQuery({
    queryKey: ["aegis", base, "calibration", value],
    queryFn: () =>
      apiRequest<CalibrationBand>(base, `/v1/insights/calibration?score=${value.toFixed(4)}`),
    enabled: connected,
    retry: false,
    staleTime: Infinity,
  });
  if (!query.data || query.data.band_id === "unavailable") return null;
  return (
    <p className="band-line" title={query.data.disclaimer}>
      {query.data.band_label}: answers in this band were correct {query.data.correct_count} of{" "}
      {query.data.sample_size} times on the dev set.
    </p>
  );
}

/** Finale feature 2: the exact sentences that support or contradict the answer. */
export function EvidenceHighlights({ result }: { result: EvaluationResult }) {
  const highlights = result.highlights ?? [];
  if (!highlights.length) return null;
  return (
    <section className="section mt-7" aria-label="Evidence highlighting">
      <SectionHeading title="Evidence highlighting">
        <span className="highlight-legend">
          <mark className="hl-support">supports</mark>
          <mark className="hl-conflict">conflicts</mark>
          <mark className="hl-number">number mismatch</mark>
        </span>
      </SectionHeading>
      {highlights.map((h) => (
        <figure key={h.evidence_index} className="highlight-passage">
          <figcaption>
            E{h.evidence_index + 1}
            {h.source ? ` · ${h.source}` : ""}
            {h.version ? ` · v${h.version}` : ""}
          </figcaption>
          <p>
            {highlightSegments(h).map((seg, i) =>
              seg.kind === "plain" && !seg.number ? (
                <span key={i}>{seg.text}</span>
              ) : (
                <mark
                  key={i}
                  className={`hl-${seg.kind === "plain" ? "none" : seg.kind}${seg.number ? " hl-number" : ""}`}
                  title={
                    seg.number
                      ? `Evidence says ${seg.number.value}; the answer says ${seg.number.claim_value}`
                      : seg.kind === "conflict"
                        ? "Contradicts a claim in the answer"
                        : "Supports a claim in the answer"
                  }
                >
                  {seg.text}
                </mark>
              ),
            )}
          </p>
          {h.numbers.map((n, i) => (
            <p key={i} className="minor-label">
              Number mismatch: evidence says <strong>{n.value}</strong>, the answer says{" "}
              <strong>{n.claim_value}</strong>.
            </p>
          ))}
        </figure>
      ))}
    </section>
  );
}

/** Finale feature 7: one-click auditor report for this decision. */
export function AuditorExport({ requestId }: { requestId: string }) {
  const { base } = useService();
  if (!base) return null;
  const href = (format: string) =>
    `${base}/v1/insights/export/${encodeURIComponent(requestId)}?format=${format}&download=true`;
  return (
    <div className="flex gap-2 mt-4 flex-wrap">
      <Button asChild variant="outline" size="sm">
        <a href={href("md")} download>
          <Download /> Auditor report (Markdown)
        </a>
      </Button>
      <Button asChild variant="ghost" size="sm">
        <a href={href("json")} download>
          <Download /> JSON
        </a>
      </Button>
    </div>
  );
}
