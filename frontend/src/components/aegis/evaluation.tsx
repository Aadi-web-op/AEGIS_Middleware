import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Play, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest, evaluationPayload, score, type EvaluationResult } from "@/lib/aegis-api";
import { useService } from "./service";
import { ConnectionNotice, EmptyState, Footer, PageHeader, SectionHeading } from "./console";
export function Evaluation() {
  const { base, connected, result, setResult } = useService();
  const [mode, setMode] = useState<"manual" | "rag">("manual");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [evidence, setEvidence] = useState("");
  const [profile, setProfile] = useState("standard");
  const [topK, setTopK] = useState(3);
  const [timeSensitive, setTimeSensitive] = useState(false);
  const mutation = useMutation({
    mutationFn: () =>
      apiRequest<EvaluationResult>(
        base,
        mode === "manual" ? "/v1/evaluate" : "/v1/rag/ask",
        mode === "manual"
          ? evaluationPayload(question, answer, evidence, profile, timeSensitive)
          : { question, top_k: topK, profile, time_sensitive: timeSensitive },
      ),
    onSuccess: setResult,
  });
  return (
    <main className="content">
      <PageHeader
        title="Live evaluation"
        description="Verify an AI answer against its supporting evidence."
      >
        <span className="status-badge">
          {connected ? "API connected" : "Backend not connected"}
        </span>
      </PageHeader>
      <ConnectionNotice />
      <div className="workspace-grid">
        <section>
          <SectionHeading title="Evaluation input" />
          <div className="flex gap-2 mt-4">
            <Button
              size="sm"
              variant={mode === "manual" ? "secondary" : "ghost"}
              onClick={() => setMode("manual")}
            >
              Verify an answer
            </Button>
            <Button
              size="sm"
              variant={mode === "rag" ? "secondary" : "ghost"}
              onClick={() => setMode("rag")}
            >
              Generate & evaluate
            </Button>
          </div>
          <label className="editor-label" htmlFor="question">
            Question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Enter the question you want to evaluate…"
          />
          {mode === "manual" ? (
            <>
              <label className="editor-label" htmlFor="answer">
                AI-generated answer
              </label>
              <textarea
                id="answer"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Paste the answer to verify…"
              />
              <label className="editor-label" htmlFor="evidence">
                Supporting evidence<span>Separate passages with a blank line</span>
              </label>
              <textarea
                id="evidence"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
                placeholder="Paste the source passages supporting this answer…"
              />
            </>
          ) : (
            <>
              <div className="editor-label">
                <label htmlFor="top-k">Retrieved passages</label>
                <Input
                  id="top-k"
                  className="w-20"
                  type="number"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(e) => setTopK(Math.min(20, Math.max(1, Number(e.target.value))))}
                />
              </div>
              <Link to="/documents" className="text-xs text-primary flex gap-2 items-center">
                Knowledge base documents <ArrowRight size={12} />
              </Link>
            </>
          )}
          <div className="flex gap-4 items-center flex-wrap mt-5">
            <label className="text-xs flex gap-2 items-center">
              Risk profile
              <select
                aria-label="Risk profile"
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
              >
                <option>lenient</option>
                <option>standard</option>
                <option>strict</option>
              </select>
            </label>
            <label className="text-xs text-muted-foreground flex gap-2 items-center">
              <input
                type="checkbox"
                checked={timeSensitive}
                onChange={(e) => setTimeSensitive(e.target.checked)}
              />
              Time-sensitive
            </label>
          </div>
          <div className="evaluation-submit">
            <span className="minor-label">
              {connected ? "Evaluated by AEGIS" : "Connect the API to run an evaluation."}
            </span>
            <Button
              size="sm"
              disabled={
                !connected ||
                !question.trim() ||
                (mode === "manual" && !answer.trim()) ||
                mutation.isPending
              }
              onClick={() => mutation.mutate()}
            >
              <Play />
              {mutation.isPending ? "Evaluating…" : "Evaluate"}
            </Button>
          </div>
          {mutation.error && (
            <p role="alert" className="text-escalate text-xs mt-4">
              Evaluation failed: {mutation.error.message}. No decision was recorded by this
              interface.
            </p>
          )}
        </section>
        <section className="result-workspace">
          <SectionHeading title="Evaluation result">
            <span className="minor-label">{result?.request_id ?? "Awaiting evaluation"}</span>
          </SectionHeading>
          {result ? (
            <>
              <div className="result-summary">
                <span className={`decision-label decision-${result.decision.toLowerCase()}`}>
                  {result.decision}
                </span>
                <div>
                  <span className="minor-label">Answerability</span>
                  <strong>{score(result.answerability_score)}</strong>
                </div>
              </div>
              {result.caveat_text && <p className="result-copy">{result.caveat_text}</p>}
              {result.clarifying_question && (
                <p className="result-copy">{result.clarifying_question}</p>
              )}
              <div className="result-reasons">
                {result.reasons.map((reason, i) => (
                  <p key={i}>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {reason.code}
                    </span>
                    <br />
                    {reason.message}
                  </p>
                ))}
              </div>
            </>
          ) : (
            <EmptyState
              icon={ShieldCheck}
              title="Evidence before confidence"
              description="The final decision, claim verification, and evidence trail will appear after a live evaluation."
            />
          )}
          <SectionHeading title="Uncertainty signals" />
          <div className="signal-list">
            {[
              "Relevance",
              "Entailment",
              "Contradiction",
              "Freshness",
              "Completeness",
              "Ambiguity",
            ].map((signal) => (
              <div key={signal}>
                <div className="signal-label">
                  <span>{signal}</span>
                  <span>{score(result?.signals[signal.toLowerCase()])}</span>
                </div>
                <div className="signal-track" />
              </div>
            ))}
          </div>
          {result && (
            <>
              <section className="section mt-7">
                <SectionHeading title="Claim verification" />
                {result.claims.map((claim, i) => (
                  <details className="claim-detail" key={i}>
                    <summary>
                      <span
                        className={`decision-${claim.status === "SUPPORTED" ? "answer" : claim.status === "CONTRADICTED" ? "escalate" : "caveat"}`}
                      >
                        {claim.status}
                      </span>{" "}
                      · {claim.claim}
                    </summary>
                    <p>
                      Support: {score(claim.support)} · Evidence references:{" "}
                      {claim.evidence_indices.join(", ") || "None"}
                    </p>
                  </details>
                ))}
                {!result.claims.length && (
                  <p className="minor-label mt-3">No individual claims returned.</p>
                )}
              </section>
              <div className="panel-foot mt-6">
                <span>Policy {result.policy_version}</span>
                <span>
                  Latency {result.latency_ms == null ? "—" : `${result.latency_ms.toFixed(0)} ms`}
                </span>
              </div>
              <Button asChild variant="link" size="sm" className="mt-4">
                <Link to="/graph">
                  Inspect graph trace <ArrowRight />
                </Link>
              </Button>
            </>
          )}
        </section>
      </div>
      <Footer />
    </main>
  );
}
