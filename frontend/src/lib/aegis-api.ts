export const decisions = ["ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"] as const;
export type Decision = (typeof decisions)[number];
export type RecordData = Record<string, unknown>;
/** Shape of GET /v1/graph/status (app/main.py). */
export interface GraphStatus {
  configured: boolean;
  connected: boolean;
  counts: Record<string, number>;
  relationships: Record<string, number>;
  writer: {
    written: number;
    failed: number;
    dropped: number;
    pending: number;
    last_error: string | null;
  };
}
/** Label for the Neo4j badge: reported by the API, never inferred. */
export function graphLabel(graph: GraphStatus | undefined): string {
  if (!graph) return "Not reported";
  if (!graph.configured) return "Not configured";
  return graph.connected ? "Connected" : "Unreachable";
}
export interface EvaluationResult {
  request_id: string;
  decision: Decision;
  answerability_score: number;
  signals: Record<string, number | null>;
  reasons: { code: string; message: string }[];
  claims: { claim: string; status: string; support: number; evidence_indices: number[] }[];
  policy_version: string;
  latency_ms?: number;
  caveat_text?: string;
  clarifying_question?: string;
  trace?: { nodes?: RecordData[]; edges?: RecordData[] };
  headline?: string | null;
  explanation?: Explanation | null;
  counterfactual?: Counterfactual | null;
  highlights?: EvidenceHighlight[];
}
export interface ExplanationFactor {
  signal: string;
  value: number | null;
  threshold: number | null;
  comparison: string | null;
  effect: Decision | null;
  message: string;
}
export interface Explanation {
  summary: string;
  decisive_rule: string | null;
  factors: ExplanationFactor[];
}
export interface SignalChange {
  signal: string;
  current: number;
  target: number;
  delta: number;
  resulting_decision: Decision;
  resulting_score: number;
  hint: string;
}
export interface Counterfactual {
  score_only_decision: Decision;
  policy_reasons: { code: string; message: string }[];
  contributions: Record<string, number>;
  unavailable_signals: string[];
  minimum_change: SignalChange | null;
}
export interface HighlightSpan {
  start: number;
  end: number;
  kind: "support" | "conflict";
  claim_index: number;
  overlap: number;
}
export interface NumberMark {
  start: number;
  end: number;
  value: string;
  claim_value: string;
  claim_index: number;
}
export interface EvidenceHighlight {
  evidence_index: number;
  source: string | null;
  version: string | null;
  text: string;
  spans: HighlightSpan[];
  numbers: NumberMark[];
}
export interface CalibrationBand {
  band_id: string;
  band_label: string;
  correct_count: number;
  sample_size: number;
  message: string;
  disclaimer?: string;
}
export interface AffectedDecision {
  request_id: string;
  decision?: string | null;
  score?: number | null;
}
/** Split a passage into plain / support / conflict / number segments. */
export function highlightSegments(h: EvidenceHighlight) {
  const cuts = new Set<number>([0, h.text.length]);
  for (const m of [...h.spans, ...h.numbers]) {
    cuts.add(Math.max(0, Math.min(h.text.length, m.start)));
    cuts.add(Math.max(0, Math.min(h.text.length, m.end)));
  }
  const points = [...cuts].sort((a, b) => a - b);
  const segments: {
    text: string;
    kind: "plain" | "support" | "conflict";
    number?: NumberMark | undefined;
  }[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i] ?? 0;
    const b = points[i + 1] ?? a;
    if (a === b) continue;
    const covering = h.spans.filter((s) => s.start <= a && s.end >= b);
    // A sentence that both supports one claim and conflicts with another reads as a conflict.
    const kind = covering.some((s) => s.kind === "conflict")
      ? "conflict"
      : covering.length
        ? "support"
        : "plain";
    const number = h.numbers.find((n) => n.start <= a && n.end >= b);
    segments.push({ text: h.text.slice(a, b), kind, number });
  }
  return segments;
}
export function apiUrl(value: string) {
  const url = new URL(value);
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password)
    throw new Error("Enter an HTTP or HTTPS API URL without credentials.");
  return url.href.replace(/\/$/, "");
}
/** Thrown on HTTP 401 so the console can show the sign-in screen. */
export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}
export interface AuthUser {
  auth_enabled: boolean;
  email: string | null;
  role: string;
}
export async function apiRequest<T>(
  base: string,
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  if (!base) throw new Error("No AEGIS API connected.");
  const response = await fetch(`${base}${path}`, {
    method: body ? method : "GET",
    // Send the HttpOnly session cookie set by /v1/auth/login.
    credentials: "include",
    ...(body
      ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {}),
    signal: AbortSignal.timeout(30000),
  });
  const data = await response.json();
  if (response.status === 401) throw new AuthError(data.detail ?? "Sign in required.");
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : `AEGIS returned ${response.status}.`,
    );
  return data as T;
}
export function score(value: unknown) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
}
export function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
export const statusValues = {
  Pending: "pending",
  "In Review": "in_review",
  Resolved: "resolved",
  Rejected: "dismissed",
} as const;
export function canTransition(current: unknown, target: string) {
  return (current === "pending" || current === "in_review") && current !== target;
}
export function evaluationPayload(
  query: string,
  answer: string,
  text: string,
  profile: string,
  timeSensitive: boolean,
) {
  return {
    query,
    answer,
    evidence: text
      .split(/\n\s*\n/)
      .filter((p) => p.trim())
      .map((text) => ({ text: text.trim() })),
    profile,
    time_sensitive: timeSensitive,
  };
}
