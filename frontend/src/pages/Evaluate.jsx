/** Live evaluation – POST /v1/evaluate, or the RAG pipeline (/v1/rag/*). */
import { useState } from "react";
import { apiPost, useApi } from "../api.js";
import DecisionResult from "../components/DecisionResult.jsx";
import { ErrorState, Icon, Notice, PageHeader, Panel, Tabs } from "../ui/index.jsx";
import { EMPTY_EVIDENCE, EXAMPLES } from "./examples.js";

function ProfileSelect({ id, value, onChange, config }) {
  const names = config.data?.profiles ? Object.keys(config.data.profiles) : ["lenient", "standard", "strict"];
  return (
    <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)}>
      {names.map((n) => (
        <option key={n} value={n}>
          {n}
          {config.data?.profiles?.[n]?.description ? ` — ${config.data.profiles[n].description}` : ""}
        </option>
      ))}
    </select>
  );
}

function cleanPayload(form) {
  return {
    query: form.query.trim(),
    answer: form.answer.trim(),
    profile: form.profile,
    time_sensitive: form.time_sensitive,
    evidence: form.evidence
      .filter((e) => e.text.trim())
      .map((e) => {
        const out = { text: e.text.trim() };
        if (e.source.trim()) out.source = e.source.trim();
        if (e.version.trim()) out.version = e.version.trim();
        if (e.date) out.date = e.date;
        return out;
      }),
  };
}

function ResultPlaceholder() {
  return (
    <div className="result-placeholder">
      <p>
        <strong>No evaluation yet.</strong> Fill in a question, the AI answer and the evidence it was given, or load an example, then press
        Evaluate.
      </p>
      <ol>
        <li>The answer is split into claims and each claim is checked against the evidence.</li>
        <li>Relevance, contradiction, freshness, completeness and ambiguity are scored.</li>
        <li>The policy profile turns those signals into one of four decisions, with the reasons.</li>
      </ol>
    </div>
  );
}

function EvaluateForm({ config }) {
  const [form, setForm] = useState({ query: "", answer: "", profile: "standard", time_sensitive: true, evidence: [{ ...EMPTY_EVIDENCE }] });
  const [example, setExample] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setEv = (i, k, v) => setForm((f) => ({ ...f, evidence: f.evidence.map((e, j) => (j === i ? { ...e, [k]: v } : e)) }));
  const addEv = () => setForm((f) => ({ ...f, evidence: [...f.evidence, { ...EMPTY_EVIDENCE }] }));
  const removeEv = (i) => setForm((f) => ({ ...f, evidence: f.evidence.filter((_, j) => j !== i) }));

  const loadExample = (ex) => {
    const data = ex.build();
    setForm({
      ...data,
      evidence: data.evidence.map((e) => ({ ...EMPTY_EVIDENCE, ...e })),
    });
    setExample(ex.id);
    setError(null);
  };

  const submit = async (e) => {
    e.preventDefault();
    const payload = cleanPayload(form);
    setBusy(true);
    setError(null);
    try {
      const response = await apiPost("/v1/evaluate", payload);
      setResult({ response, request: payload });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="eval-layout">
      <Panel title="Input" description="What the AI was asked, what it answered, and the passages it had.">
        <div className="examples" role="group" aria-label="Load an example">
          <span className="examples__label">Load an example (prefills the form only)</span>
          {EXAMPLES.map((ex) => (
            <button key={ex.id} type="button" className={example === ex.id ? "example-btn is-active" : "example-btn"} onClick={() => loadExample(ex)}>
              {ex.label}
            </button>
          ))}
        </div>
        <form onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="ev-query">
              Question
            </label>
            <textarea id="ev-query" className="textarea" rows={2} required value={form.query} onChange={(e) => set("query", e.target.value)} />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="ev-answer">
              AI answer to evaluate
            </label>
            <textarea id="ev-answer" className="textarea" rows={3} required value={form.answer} onChange={(e) => set("answer", e.target.value)} />
          </div>

          <div className="field">
            <span className="field__label">Evidence passages</span>
            <div className="ev-editor">
              {form.evidence.map((ev, i) => (
                <div className="ev-item" key={i}>
                  <div className="ev-item__head">
                    <span>E{i + 1}</span>
                    {form.evidence.length > 1 && (
                      <button type="button" className="icon-btn" onClick={() => removeEv(i)} aria-label={`Remove evidence E${i + 1}`} title="Remove">
                        <Icon name="trash" size={14} />
                      </button>
                    )}
                  </div>
                  <label className="sr-only" htmlFor={`ev-text-${i}`}>
                    Evidence E{i + 1} text
                  </label>
                  <textarea
                    id={`ev-text-${i}`}
                    className="textarea"
                    rows={2}
                    placeholder="Passage text"
                    value={ev.text}
                    onChange={(e) => setEv(i, "text", e.target.value)}
                  />
                  <div className="form-grid form-grid--3">
                    <div className="field">
                      <label className="field__label" htmlFor={`ev-src-${i}`}>
                        Source
                      </label>
                      <input id={`ev-src-${i}`} className="input input--sm" value={ev.source} onChange={(e) => setEv(i, "source", e.target.value)} />
                    </div>
                    <div className="field" style={{ marginTop: 0 }}>
                      <label className="field__label" htmlFor={`ev-ver-${i}`}>
                        Version
                      </label>
                      <input id={`ev-ver-${i}`} className="input input--sm" value={ev.version} onChange={(e) => setEv(i, "version", e.target.value)} />
                    </div>
                    <div className="field" style={{ marginTop: 0 }}>
                      <label className="field__label" htmlFor={`ev-date-${i}`}>
                        Date
                      </label>
                      <input id={`ev-date-${i}`} type="date" className="input input--sm" value={ev.date} onChange={(e) => setEv(i, "date", e.target.value)} />
                    </div>
                  </div>
                </div>
              ))}
              <div>
                <button type="button" className="btn btn--secondary btn--sm" onClick={addEv}>
                  <Icon name="plus" size={14} /> Add passage
                </button>
              </div>
            </div>
            <p className="field__hint">Leave every passage empty to test the no-evidence path.</p>
          </div>

          <div className="form-grid">
            <div className="field">
              <label className="field__label" htmlFor="ev-profile">
                Policy profile
              </label>
              <ProfileSelect id="ev-profile" value={form.profile} onChange={(v) => set("profile", v)} config={config} />
            </div>
            <div className="field" style={{ marginTop: 0, alignContent: "end" }}>
              <label className="check">
                <input type="checkbox" checked={form.time_sensitive} onChange={(e) => set("time_sensitive", e.target.checked)} />
                Time-sensitive question
              </label>
            </div>
          </div>

          <div className="form-actions">
            <button type="submit" className="btn" disabled={busy || !form.query.trim() || !form.answer.trim()}>
              {busy ? "Evaluating…" : "Evaluate"}
            </button>
            {result && (
              <span className="muted small">
                Last run <span className="mono">{result.response.request_id}</span>
              </span>
            )}
          </div>
          {error && <ErrorState error={error} compact />}
        </form>
      </Panel>

      <div aria-live="polite">
        {busy && !result && <Notice title="Evaluating">Running signals and policy…</Notice>}
        {result ? <DecisionResult response={result.response} request={result.request} config={config.data} /> : !busy && <ResultPlaceholder />}
      </div>
    </div>
  );
}

function RagPanel({ config }) {
  const [ingest, setIngest] = useState({ pdf_path: "data/demo/leave_policy_v2_2024.pdf", date: "", version: "" });
  const [ingestState, setIngestState] = useState({ busy: false, error: null, message: null });
  const [ask, setAsk] = useState({ question: "", top_k: 5, profile: "standard", time_sensitive: true });
  const [askState, setAskState] = useState({ busy: false, error: null, result: null });

  const doIngest = async (e) => {
    e.preventDefault();
    setIngestState({ busy: true, error: null, message: null });
    const body = { pdf_path: ingest.pdf_path.trim() };
    if (ingest.date) body.date = ingest.date;
    if (ingest.version.trim()) body.version = ingest.version.trim();
    try {
      const r = await apiPost("/v1/rag/ingest", body);
      setIngestState({ busy: false, error: null, message: `${r.chunks_added} chunks added from ${r.pdf_path}.` });
    } catch (err) {
      setIngestState({ busy: false, error: err, message: null });
    }
  };

  const doAsk = async (e) => {
    e.preventDefault();
    setAskState((s) => ({ ...s, busy: true, error: null }));
    try {
      const response = await apiPost("/v1/rag/ask", { ...ask, top_k: Number(ask.top_k) || 5 });
      setAskState({ busy: false, error: null, result: { response, request: { query: ask.question, profile: ask.profile } } });
    } catch (err) {
      setAskState((s) => ({ ...s, busy: false, error: err }));
    }
  };

  return (
    <div className="eval-layout">
      <div className="stack">
        <Panel title="1. Ingest a document" description="PDF path on the backend machine. The knowledge base is held in memory by the backend.">
          <form onSubmit={doIngest}>
            <div className="field">
              <label className="field__label" htmlFor="rag-path">
                PDF path
              </label>
              <input id="rag-path" className="input mono" required value={ingest.pdf_path} onChange={(e) => setIngest({ ...ingest, pdf_path: e.target.value })} />
            </div>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <div className="field">
                <label className="field__label" htmlFor="rag-date">
                  Effective date
                </label>
                <input id="rag-date" type="date" className="input" value={ingest.date} onChange={(e) => setIngest({ ...ingest, date: e.target.value })} />
              </div>
              <div className="field" style={{ marginTop: 0 }}>
                <label className="field__label" htmlFor="rag-version">
                  Version
                </label>
                <input id="rag-version" className="input" value={ingest.version} onChange={(e) => setIngest({ ...ingest, version: e.target.value })} />
              </div>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn btn--secondary" disabled={ingestState.busy}>
                {ingestState.busy ? "Ingesting…" : "Ingest document"}
              </button>
              {ingestState.message && <span className="small" style={{ color: "var(--answer)" }}>{ingestState.message}</span>}
            </div>
            {ingestState.error && <ErrorState error={ingestState.error} compact />}
          </form>
        </Panel>

        <Panel title="2. Ask a question" description="The backend retrieves passages, generates an answer with the configured LLM provider, then AEGIS evaluates it.">
          <form onSubmit={doAsk}>
            <div className="field">
              <label className="field__label" htmlFor="rag-q">
                Question
              </label>
              <textarea id="rag-q" className="textarea" rows={2} required value={ask.question} onChange={(e) => setAsk({ ...ask, question: e.target.value })} />
            </div>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <div className="field">
                <label className="field__label" htmlFor="rag-profile">
                  Policy profile
                </label>
                <ProfileSelect id="rag-profile" value={ask.profile} onChange={(v) => setAsk({ ...ask, profile: v })} config={config} />
              </div>
              <div className="field" style={{ marginTop: 0 }}>
                <label className="field__label" htmlFor="rag-k">
                  Passages to retrieve
                </label>
                <input id="rag-k" type="number" min={1} max={20} className="input" value={ask.top_k} onChange={(e) => setAsk({ ...ask, top_k: e.target.value })} />
              </div>
            </div>
            <label className="check" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={ask.time_sensitive} onChange={(e) => setAsk({ ...ask, time_sensitive: e.target.checked })} />
              Time-sensitive question
            </label>
            <div className="form-actions">
              <button type="submit" className="btn" disabled={askState.busy || !ask.question.trim()}>
                {askState.busy ? "Running…" : "Ask and evaluate"}
              </button>
            </div>
            {askState.error && <ErrorState error={askState.error} compact />}
          </form>
        </Panel>
      </div>
      <div aria-live="polite">
        {askState.result ? (
          <DecisionResult response={askState.result.response} request={askState.result.request} config={config.data} />
        ) : (
          <div className="result-placeholder">
            <p>
              <strong>No RAG answer yet.</strong> Ingest at least one document, then ask a question. The generated answer is not returned by{" "}
              <span className="mono">/v1/rag/ask</span>; its claims and evidence are shown from the evaluation.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Evaluate() {
  const [tab, setTab] = useState("direct");
  const config = useApi("/v1/config");
  return (
    <>
      <PageHeader
        title="Live evaluation"
        description="Send an AI answer and its evidence through AEGIS and see the decision, the claim-by-claim check and the reasons."
      />
      <Tabs
        label="Evaluation mode"
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "direct", label: "Evaluate an answer" },
          { value: "rag", label: "RAG pipeline" },
        ]}
      />
      {config.error && (
        <div style={{ marginBottom: 16 }}>
          <ErrorState error={config.error} compact title="Policy config unavailable" onRetry={config.reload} />
        </div>
      )}
      {tab === "direct" ? <EvaluateForm config={config} /> : <RagPanel config={config} />}
    </>
  );
}
