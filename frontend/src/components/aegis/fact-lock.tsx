import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest, display } from "@/lib/aegis-api";
import { useService } from "./service";
import { ConnectionNotice, EmptyState, Footer, PageHeader, SectionHeading } from "./console";

interface Fact {
  key: string;
  label: string;
  kind: string;
  value: string;
  level: number;
  level_name: string;
  unit?: string | null;
  aliases: string[];
  source?: string | null;
  version?: string | null;
}
interface FactCheck {
  fact_key: string;
  label: string;
  level: number;
  verdict: string;
  locked: string;
  stated?: string | null;
  action: string;
  message: string;
  outdated_version?: string | null;
}
interface CheckResult {
  decision_floor: string | null;
  requires_approval: boolean;
  corrected_answer: string | null;
  checks: FactCheck[];
}
interface Impact {
  key: string;
  label: string;
  current: string;
  version?: string | null;
  scanned: number;
  counts: Record<string, number>;
  delivered_wrong: number;
  affected: {
    request_id: string;
    timestamp: string;
    query: string;
    stated: string;
    status: string;
    old_version?: string | null;
    original_decision: string;
    action: string;
  }[];
}

const LEVELS: [number, string, string][] = [
  [1, "L1 Info", "Wrong value → shown with a correction note"],
  [2, "L2 Operational", "Wrong value → corrected automatically"],
  [3, "L3 Commitment", "Wrong value → blocked, sent to a person"],
  [4, "L4 Regulated", "Wrong or uncited → blocked until approved"],
];
const KINDS = ["duration", "money", "percent", "count", "date"];
const verdictClass = (v: string) =>
  v === "confirmed"
    ? "decision-answer"
    : v === "mismatch" || v === "outdated"
      ? "decision-escalate"
      : "decision-caveat";

export function FactLockPage() {
  const { base, connected, user } = useService();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === "admin";
  const facts = useQuery({
    queryKey: ["aegis", base, "facts"],
    queryFn: () => apiRequest<{ facts: Fact[] }>(base, "/v1/facts"),
    enabled: Boolean(base && connected),
    retry: false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["aegis", base, "facts"] });

  // --- try an answer
  const [question, setQuestion] = useState("How many days do I have to raise a damage claim?");
  const [answer, setAnswer] = useState("You can raise a damage claim within 14 days of delivery.");
  const check = useMutation({
    mutationFn: () => apiRequest<CheckResult>(base, "/v1/facts/check", { query: question, answer }),
  });

  // --- change a value
  const [editing, setEditing] = useState<string | null>(null);
  const [newValue, setNewValue] = useState("");
  const [newVersion, setNewVersion] = useState("");
  const [impact, setImpact] = useState<Impact | null>(null);
  const update = useMutation({
    mutationFn: (key: string) =>
      apiRequest<{ impact: Impact }>(
        base,
        `/v1/facts/${encodeURIComponent(key)}`,
        { value: newValue, version: newVersion || undefined },
        "PUT",
      ),
    onSuccess: (data) => {
      setImpact(data.impact);
      setEditing(null);
      void refresh();
    },
  });
  const showImpact = useMutation({
    mutationFn: (key: string) =>
      apiRequest<Impact>(base, `/v1/facts/${encodeURIComponent(key)}/impact`),
    onSuccess: setImpact,
  });

  // --- lock a new fact
  const blank = {
    key: "",
    label: "",
    kind: "duration",
    value: "",
    level: 3,
    aliases: "",
    source: "",
    version: "",
  };
  const [form, setForm] = useState(blank);
  const create = useMutation({
    mutationFn: () =>
      apiRequest(base, "/v1/facts", {
        ...form,
        level: Number(form.level),
        aliases: form.aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
        source: form.source || undefined,
        version: form.version || undefined,
      }),
    onSuccess: () => {
      setForm(blank);
      void refresh();
    },
  });

  const list = facts.data?.facts ?? [];
  return (
    <main className="content">
      <PageHeader
        title="Fact Lock"
        description="Approved facts every AI answer is checked against: exact values, versioned, independent of what retrieval returned."
      >
        <span className="status-badge">
          <Lock size={13} /> {list.length} locked
        </span>
      </PageHeader>
      <ConnectionNotice />

      <div className="fact-levels">
        {LEVELS.map(([n, name, rule]) => (
          <div key={n} className={`fact-level fact-level-${n}`}>
            <strong>{name}</strong>
            <span>{rule}</span>
          </div>
        ))}
      </div>

      <div className="workspace-grid">
        <section>
          <SectionHeading
            title="Check an answer"
            description="Runs only the Fact Lock: no models, same result every time."
          />
          <label className="editor-label" htmlFor="fl-question">
            Question
          </label>
          <textarea
            id="fl-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <label className="editor-label" htmlFor="fl-answer">
            AI answer
          </label>
          <textarea id="fl-answer" value={answer} onChange={(e) => setAnswer(e.target.value)} />
          <div className="evaluation-submit">
            <span className="minor-label">{check.error?.message ?? ""}</span>
            <Button
              size="sm"
              disabled={!connected || !answer.trim() || check.isPending}
              onClick={() => check.mutate()}
            >
              <Play /> Check
            </Button>
          </div>
        </section>
        <section>
          <SectionHeading title="Result" />
          {!check.data ? (
            <EmptyState
              icon={Lock}
              title="No check yet"
              description="Enter an answer that states a locked value."
            />
          ) : (
            <div className="fact-result">
              <p className="blast-title">
                Fact Lock decision:{" "}
                <strong
                  className={check.data.decision_floor ? "decision-escalate" : "decision-answer"}
                >
                  {check.data.decision_floor ?? "No objection"}
                </strong>
                {check.data.requires_approval && " · needs approval"}
              </p>
              {check.data.checks.length === 0 && (
                <p className="section-description">The answer does not touch any locked fact.</p>
              )}
              <ul className="blast-list">
                {check.data.checks.map((c) => (
                  <li key={c.fact_key}>
                    <span className={verdictClass(c.verdict)}>{c.verdict}</span>
                    <span>
                      <strong>{c.label}</strong> (L{c.level}) — {c.message}
                    </span>
                  </li>
                ))}
              </ul>
              {check.data.corrected_answer && (
                <p className="fact-corrected">
                  <strong>Corrected answer:</strong> {check.data.corrected_answer}
                </p>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="section">
        <SectionHeading
          title="Locked facts"
          description="Change a value to see which past answers stated the old one."
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {["Fact", "Value", "Level", "Source", ""].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.key}>
                  <td>
                    <strong>{f.label}</strong>
                    <div className="minor-label font-mono">{f.key}</div>
                  </td>
                  <td>
                    {editing === f.key ? (
                      <div className="flex gap-2">
                        <Input
                          aria-label="New value"
                          value={newValue}
                          onChange={(e) => setNewValue(e.target.value)}
                        />
                        <Input
                          aria-label="New version"
                          placeholder="version"
                          value={newVersion}
                          onChange={(e) => setNewVersion(e.target.value)}
                        />
                      </div>
                    ) : (
                      <strong>{f.value}</strong>
                    )}
                  </td>
                  <td>
                    <span className={`fact-chip fact-level-${f.level}`}>
                      L{f.level} {f.level_name}
                    </span>
                  </td>
                  <td>{[f.source, f.version].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="flex gap-2">
                    {editing === f.key ? (
                      <>
                        <Button
                          size="sm"
                          disabled={!newValue.trim() || update.isPending}
                          onClick={() => update.mutate(f.key)}
                        >
                          Save
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <>
                        {isAdmin && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              setEditing(f.key);
                              setNewValue(f.value);
                              setNewVersion("");
                            }}
                          >
                            Change value
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" onClick={() => showImpact.mutate(f.key)}>
                          Past answers
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {update.error && <p className="minor-label decision-escalate">{update.error.message}</p>}
        {!list.length && (
          <div className="table-empty">
            <EmptyState
              icon={Lock}
              title="No facts locked yet"
              description={
                facts.error ? facts.error.message : "Lock prices, limits and deadlines below."
              }
            />
          </div>
        )}
      </section>

      {impact && (
        <section className="section">
          <SectionHeading
            title={`Past answers: ${impact.label}`}
            description={`Locked value now ${impact.current}${impact.version ? ` (${impact.version})` : ""}. Scanned ${impact.scanned} stored answers.`}
          />
          <p className="blast-title">
            <span className="decision-escalate">●</span> <strong>{impact.delivered_wrong}</strong>{" "}
            wrong answer(s) were delivered · {impact.counts["outdated"] ?? 0} stated an old version
            · {impact.counts["wrong"] ?? 0} other wrong value ·{" "}
            {impact.counts["still_correct"] ?? 0} still correct
          </p>
          {impact.affected.length > 0 && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {["Asked", "Question", "Stated", "Status", "Was", "What to do"].map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {impact.affected.map((a) => (
                    <tr key={a.request_id}>
                      <td className="font-mono">{display(a.timestamp).slice(0, 16)}</td>
                      <td>{a.query}</td>
                      <td>
                        <strong>{a.stated}</strong>
                      </td>
                      <td className="decision-escalate">
                        {a.status}
                        {a.old_version ? ` (${a.old_version})` : ""}
                      </td>
                      <td>{a.original_decision}</td>
                      <td>{a.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {isAdmin && (
        <section className="section">
          <SectionHeading
            title="Lock a new fact"
            description="The value must contain exactly one amount, duration, percentage, count or date."
          />
          <div className="fact-form">
            <Input
              placeholder="key (e.g. refund_window)"
              value={form.key}
              onChange={(e) => setForm({ ...form, key: e.target.value })}
            />
            <Input
              placeholder="label (e.g. refund window)"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
            />
            <select
              aria-label="Kind"
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
            >
              {KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
            <Input
              placeholder="value (e.g. 15 days, Rs 7,500)"
              value={form.value}
              onChange={(e) => setForm({ ...form, value: e.target.value })}
            />
            <select
              aria-label="Level"
              value={form.level}
              onChange={(e) => setForm({ ...form, level: Number(e.target.value) })}
            >
              {LEVELS.map(([n, name]) => (
                <option key={n} value={n}>
                  {name}
                </option>
              ))}
            </select>
            <Input
              placeholder="other names, comma separated"
              value={form.aliases}
              onChange={(e) => setForm({ ...form, aliases: e.target.value })}
            />
            <Input
              placeholder="source document"
              value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value })}
            />
            <Input
              placeholder="version"
              value={form.version}
              onChange={(e) => setForm({ ...form, version: e.target.value })}
            />
          </div>
          <div className="evaluation-submit">
            <span className="minor-label">{create.error?.message ?? ""}</span>
            <Button
              size="sm"
              disabled={!form.key || !form.label || !form.value || create.isPending}
              onClick={() => create.mutate()}
            >
              <Lock /> Lock fact
            </Button>
          </div>
        </section>
      )}
      <Footer />
    </main>
  );
}
