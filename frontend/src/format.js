/** Formatting helpers. Missing values render as an em dash, never as 0. */

export const DASH = "—";

export function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

export function score(v, digits = 2) {
  return isNum(v) ? v.toFixed(digits) : DASH;
}

export function pct(v, digits = 0) {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : DASH;
}

export function ratio(num, den, digits = 0) {
  if (!isNum(num) || !isNum(den) || den === 0) return DASH;
  return `${((num / den) * 100).toFixed(digits)}%`;
}

export function int(v) {
  return isNum(v) ? v.toLocaleString("en-US") : DASH;
}

export function ms(v) {
  if (!isNum(v)) return DASH;
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
}

export function shortId(id, n = 8) {
  if (!id) return DASH;
  const s = String(id);
  return s.length > n + 2 ? s.slice(0, n) : s;
}

export function truncate(s, n = 80) {
  if (s === null || s === undefined) return "";
  const t = String(s);
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export function humanCode(code) {
  if (!code) return DASH;
  return String(code)
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^\w/, (c) => c.toUpperCase());
}

export function parseTime(v) {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgo(v) {
  const d = parseTime(v);
  if (!d) return DASH;
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 0) return d.toLocaleString();
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function dateTime(v) {
  const d = parseTime(v);
  if (!d) return v ? String(v) : DASH;
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export const DECISIONS = ["ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"];

export const DECISION_META = {
  ANSWER: { cls: "answer", label: "Answer", action: "Return the answer" },
  CAVEAT: { cls: "caveat", label: "Caveat", action: "Return with a caveat" },
  ESCALATE: { cls: "escalate", label: "Escalate", action: "Route to a human" },
  ABSTAIN: { cls: "abstain", label: "Abstain", action: "Do not answer" },
};

export const CLAIM_CLS = {
  SUPPORTED: "answer",
  UNSUPPORTED: "caveat",
  CONTRADICTED: "escalate",
};

export const SEVERITY_CLS = { high: "escalate", medium: "caveat", low: "abstain" };

export function decisionCls(d) {
  return DECISION_META[d]?.cls ?? "abstain";
}
