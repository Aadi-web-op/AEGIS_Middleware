/**
 * Landing – public home page for AEGIS (route: #home).
 *
 * Every number on this page comes from the committed benchmark and test
 * suite (see PITCH-DECK / docs/demo_script.md). No customer logos or
 * testimonials are shown, because none exist yet.
 */
import { useEffect, useState } from "react";
import "./Landing.css";
import GraphField from "./GraphField.jsx";
import { useCountUp, useInView, useRevealAll } from "./useMotion.js";

const API = import.meta.env.VITE_AEGIS_API ?? "http://127.0.0.1:8000";
const ROTATING = ["trust", "audit", "explain", "defend"];

function scrollToId(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function Logo() {
  return (
    <span className="lp-logo">
      <span className="lp-logo-mark">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      </span>
      AEGIS
    </span>
  );
}

// ── Nav ─────────────────────────────────────────────────────────────────────

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const links = [
    ["how", "How it works"],
    ["signals", "Signals"],
    ["graph", "Decision graph"],
    ["insights", "Insights"],
    ["developers", "Developers"],
  ];
  return (
    <header className={`lp-nav${scrolled ? " lp-nav--scrolled" : ""}`}>
      <div className="lp-container lp-nav-inner">
        <a href="#home" aria-label="AEGIS home" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
          <Logo />
        </a>
        <nav className="lp-nav-links" aria-label="Page sections">
          {links.map(([id, label]) => (
            <button key={id} type="button" onClick={() => scrollToId(id)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="lp-nav-cta">
          <a className="lp-btn lp-btn--ghost lp-btn--sm" href={`${API}/docs`} target="_blank" rel="noreferrer">
            API docs
          </a>
          <a className="lp-btn lp-btn--primary lp-btn--sm" href="#workspace">
            Open console
          </a>
        </div>
      </div>
    </header>
  );
}

// ── Hero ────────────────────────────────────────────────────────────────────

function RotatingWord() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setI((v) => (v + 1) % ROTATING.length), 2200);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="lp-rotator" aria-live="polite">
      <span key={ROTATING[i]} className="lp-rotator-word">
        {ROTATING[i]}
      </span>
    </span>
  );
}

const DEMO_SIGNALS = [
  ["Relevance", 0.762, "ok"],
  ["Entailment", 0.332, "bad"],
  ["Contradiction", 1.0, "bad"],
  ["Freshness", 0.0, "bad"],
  ["Completeness", 1.0, "ok"],
  ["Ambiguity", 0.0, "ok"],
];

function LiveDecisionCard() {
  // 0 question · 1 generated answer · 2 signals · 3 decision
  const [step, setStep] = useState(0);
  useEffect(() => {
    const delays = [1100, 1500, 2200, 4200];
    const id = setTimeout(() => setStep((s) => (s + 1) % 4), delays[step]);
    return () => clearTimeout(id);
  }, [step]);

  return (
    <div className="lp-demo" aria-label="Animated example of an AEGIS evaluation">
      <div className="lp-demo-bar">
        <span className="lp-dots"><i /><i /><i /></span>
        <span className="lp-demo-title">POST /v1/rag/ask · profile: standard</span>
      </div>

      <div className="lp-demo-body">
        <div className="lp-demo-row lp-demo-row--in">
          <span className="lp-demo-label">Question</span>
          <p>How many casual leaves can an employee take?</p>
        </div>

        <div className={`lp-demo-row${step >= 1 ? " lp-demo-row--in" : ""}`}>
          <span className="lp-demo-label">Generator</span>
          <p>
            “Employees receive <mark>18 casual leaves</mark> per year.”
          </p>
          <small>Sourced from HR/2024/11 · v2 (Mar 2024)</small>
        </div>

        <div className={`lp-demo-row${step >= 2 ? " lp-demo-row--in" : ""}`}>
          <span className="lp-demo-label">AEGIS signals</span>
          <div className="lp-demo-signals">
            {DEMO_SIGNALS.map(([name, v, tone], idx) => (
              <div className="lp-demo-signal" key={name}>
                <span>{name}</span>
                <div className="lp-demo-track">
                  <div
                    className={`lp-demo-fill lp-demo-fill--${tone}`}
                    style={{
                      width: step >= 2 ? `${Math.max(v * 100, 3)}%` : "0%",
                      transitionDelay: `${idx * 90}ms`,
                    }}
                  />
                </div>
                <b>{v.toFixed(2)}</b>
              </div>
            ))}
          </div>
        </div>

        <div className={`lp-demo-verdict${step >= 3 ? " lp-demo-verdict--in" : ""}`}>
          <div>
            <span className="lp-demo-label">Decision</span>
            <strong>ESCALATE</strong>
            <p>Sources disagree: HR/2026/04 supersedes this with 12 days.</p>
          </div>
          <div className="lp-demo-chips">
            <span>CONTRADICTION</span>
            <span>UNSUPPORTED_CLAIM</span>
            <span>STALE_EVIDENCE</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Hero() {
  return (
    <section className="lp-hero">
      <GraphField />
      <div className="lp-hero-glow" aria-hidden="true" />
      <div className="lp-container lp-hero-inner">
        <div className="lp-hero-copy">
          <span className="lp-badge lp-fade" style={{ "--d": "0ms" }}>
            <span className="lp-badge-dot" /> Open source · MIT · Model-agnostic
          </span>
          <h1 className="lp-fade" style={{ "--d": "80ms" }}>
            AI answers
            <br />
            you can <RotatingWord />
          </h1>
          <p className="lp-lead lp-fade" style={{ "--d": "160ms" }}>
            AEGIS is the judgement layer between your model and your users. It
            checks every generated answer against its own evidence, decides
            whether it is safe to show, and keeps a graph of exactly why.
          </p>
          <div className="lp-hero-ctas lp-fade" style={{ "--d": "240ms" }}>
            <a className="lp-btn lp-btn--primary" href="#workspace">
              Launch the console
              <span aria-hidden="true">→</span>
            </a>
            <button type="button" className="lp-btn lp-btn--ghost" onClick={() => scrollToId("how")}>
              See how it works
            </button>
          </div>
          <ul className="lp-hero-meta lp-fade" style={{ "--d": "320ms" }}>
            <li><b>6</b> independent signals</li>
            <li><b>4</b> auditable decisions</li>
            <li><b>58 ms</b> median latency</li>
          </ul>
        </div>
        <div className="lp-hero-visual lp-fade" style={{ "--d": "200ms" }}>
          <LiveDecisionCard />
        </div>
      </div>
      <button type="button" className="lp-scroll-cue" onClick={() => scrollToId("problem")} aria-label="Scroll to content">
        <span />
      </button>
    </section>
  );
}

// ── Marquee ─────────────────────────────────────────────────────────────────

function Marquee() {
  const items = [
    "HR policy assistants", "Compliance desks", "Legal research", "IT helpdesks",
    "Finance operations", "Internal knowledge bases", "Customer support", "Medical guidance",
  ];
  const row = [...items, ...items];
  return (
    <div className="lp-marquee" aria-label="Built for teams running AI over internal documents">
      <div className="lp-marquee-track">
        {row.map((t, i) => (
          <span key={i} aria-hidden={i >= items.length}>
            <i /> {t}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Section header ──────────────────────────────────────────────────────────

function SectionHead({ eyebrow, title, children, center }) {
  return (
    <div className={`lp-section-head reveal${center ? " lp-center" : ""}`}>
      <span className="lp-eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {children && <p>{children}</p>}
    </div>
  );
}

// ── Problem ─────────────────────────────────────────────────────────────────

function Problem() {
  return (
    <section id="problem" className="lp-section">
      <div className="lp-container">
        <SectionHead eyebrow="The problem" title="Retrieval-augmented AI fails silently." center>
          Retrieval worked. Judgement is what was missing. Two live HR documents
          disagree, and a plain RAG stack answers confidently from the old one.
        </SectionHead>

        <div className="lp-compare">
          <div className="lp-compare-card lp-compare-card--bad reveal">
            <div className="lp-compare-top">
              <span className="lp-tag lp-tag--bad">Plain RAG</span>
              <span className="lp-muted">Confident. Sourced. Two years out of date.</span>
            </div>
            <p className="lp-quote">“You get <mark>18 casual leaves</mark> per year.”</p>
            <ul className="lp-checklist lp-checklist--bad">
              <li>Cites a real, superseded document</li>
              <li>Never sees the newer circular</li>
              <li>No warning, no flag, no audit trail</li>
            </ul>
          </div>

          <div className="lp-compare-vs reveal" aria-hidden="true">vs</div>

          <div className="lp-compare-card lp-compare-card--good reveal">
            <div className="lp-compare-top">
              <span className="lp-tag lp-tag--good">With AEGIS</span>
              <span className="lp-muted">Caught before it reached a user.</span>
            </div>
            <p className="lp-quote">
              <b className="lp-escalate">ESCALATE</b> — “A person should check this
              before anyone relies on it.”
            </p>
            <ul className="lp-checklist lp-checklist--good">
              <li>Names the two documents that disagree</li>
              <li>Flags the 2024 source as stale</li>
              <li>Stores the full evidence trail as a graph</li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── How it works ────────────────────────────────────────────────────────────

const STEPS = [
  ["Retrieve", "Your existing RAG returns evidence chunks with source, date and version."],
  ["Generate", "Any model, any provider. AEGIS never replaces your generator."],
  ["Measure", "Six independent uncertainty signals over the answer and its evidence."],
  ["Decide", "Weighted score, veto rules and a risk profile produce the decision."],
  ["Explain", "Plain-language reasons plus a graph of the evidence trail."],
];

function HowItWorks() {
  const [ref, visible] = useInView(0.25);
  return (
    <section id="how" className="lp-section lp-section--alt">
      <div className="lp-container">
        <SectionHead eyebrow="How it works" title="A judgement layer between the model and the user.">
          AEGIS sits after generation and before delivery. It scores the answer
          against the evidence that produced it, then returns one of four
          decisions — each with human-readable reasons.
        </SectionHead>

        <ol ref={ref} className={`lp-steps${visible ? " lp-steps--in" : ""}`}>
          {STEPS.map(([title, body], i) => (
            <li key={title} style={{ "--i": i }}>
              <span className="lp-step-num">{String(i + 1).padStart(2, "0")}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ── Signals ─────────────────────────────────────────────────────────────────

const SIGNALS = [
  ["Relevance", "Embedding similarity between the question and each evidence chunk. Catches retrieval that returned something plausible but unrelated.", "M4 12h16 M12 4v16"],
  ["Entailment", "Claim-level NLI. The answer is split into claims and each is checked for support individually, not in aggregate.", "M5 12l4 4L19 6"],
  ["Contradiction", "Detects conflict between answer and evidence and between two sources, including numeric and date conflicts.", "M6 6l12 12 M18 6L6 18"],
  ["Freshness", "Decay over evidence dates. Undated evidence returns SIGNAL_UNAVAILABLE and marks the request degraded.", "M12 7v5l3 3 M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18"],
  ["Completeness", "Whether the evidence covers every part of a multi-part question, or only some of it.", "M4 6h16 M4 12h16 M4 18h10"],
  ["Ambiguity", "Whether the question is answerable as asked. Produces a clarifying question rather than a guess.", "M9 9a3 3 0 1 1 4 2.8c-.6.3-1 .9-1 1.6V14 M12 18h.01"],
];

function Spotlight({ children, className = "", style }) {
  function onMove(e) {
    const r = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
    e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
  }
  return (
    <div className={`lp-spot ${className}`} style={style} onPointerMove={onMove}>
      {children}
    </div>
  );
}

function Signals() {
  return (
    <section id="signals" className="lp-section">
      <div className="lp-container">
        <SectionHead eyebrow="How it measures" title="Six signals, each independently computed.">
          A signal that cannot be computed is never silently treated as a pass.
          A missing check can only make AEGIS more cautious — never less.
        </SectionHead>
        <div className="lp-grid lp-grid--3">
          {SIGNALS.map(([title, body, path], i) => (
            <Spotlight key={title} className="lp-card reveal" style={{ "--d": `${i * 70}ms` }}>
              <span className="lp-card-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d={path} />
                </svg>
              </span>
              <h3>{title}</h3>
              <p>{body}</p>
            </Spotlight>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Decisions ───────────────────────────────────────────────────────────────

const DECISIONS = [
  ["ANSWER", "answer", "Every claim is supported by current evidence.", "return_answer"],
  ["CAVEAT", "caveat", "Mostly supported — ship it with a warning.", "return_with_caveat"],
  ["ESCALATE", "escalate", "A person must check before anyone relies on it.", "escalate_to_human"],
  ["ABSTAIN", "abstain", "Not answerable from these documents.", "abstain"],
];

function Decisions() {
  return (
    <section className="lp-section lp-section--alt">
      <div className="lp-container">
        <SectionHead eyebrow="How it decides" title="Not a bare score. A decision you can act on." center>
          Weighted signals, hard veto rules that the score can never override,
          and risk profiles from lenient to strict — all in a YAML file you own.
        </SectionHead>
        <div className="lp-grid lp-grid--4">
          {DECISIONS.map(([name, tone, body, action], i) => (
            <div key={name} className={`lp-decision lp-decision--${tone} reveal`} style={{ "--d": `${i * 90}ms` }}>
              <span className="lp-decision-dot" />
              <h3>{name}</h3>
              <p>{body}</p>
              <code>{action}</code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Decision graph (animated SVG) ───────────────────────────────────────────

function GraphShowcase() {
  const [ref, visible] = useInView(0.3);
  const N = {
    dec: { x: 10, y: 190, label: "Decision · ESCALATE", c: "#4a9eff" },
    c1: { x: 215, y: 100, label: "Claim · 18 casual leaves", c: "#ef4444" },
    rsn: { x: 215, y: 290, label: "Reason · Contradiction", c: "#f472b6" },
    e1: { x: 435, y: 50, label: "Evidence · “18 leaves”", c: "#7dd3fc" },
    e2: { x: 435, y: 190, label: "Evidence · “12 leaves”", c: "#7dd3fc" },
    d1: { x: 660, y: 50, label: "HR/2024/11 · v2", c: "#c084fc" },
    d2: { x: 660, y: 190, label: "HR/2026/04 · v3", c: "#c084fc" },
  };
  const E = [
    ["dec", "c1", "HAS_CLAIM", "#4a9eff"],
    ["dec", "rsn", "BECAUSE", "#f472b6"],
    ["c1", "e1", "SUPPORTED_BY", "#22c55e"],
    ["c1", "e2", "CONTRADICTED_BY", "#ef4444"],
    ["e1", "d1", "FROM", "#c084fc"],
    ["e2", "d2", "FROM", "#c084fc"],
    ["e1", "e2", "CONFLICTS_WITH", "#f97316"],
    ["d2", "d1", "SUPERSEDES", "#a3e635"],
  ];
  const W = 180;
  const H = 42;
  return (
    <section id="graph" className="lp-section">
      <div className="lp-container lp-split">
        <div>
          <SectionHead eyebrow="The decision graph" title="Every decision keeps its evidence trail.">
            Each evaluation emits one trace — claims, evidence, documents,
            conflicts and reasons. The API returns it, the console draws it and
            Neo4j stores it, so a decision explains itself identically everywhere.
          </SectionHead>
          <ul className="lp-checklist lp-checklist--good reveal">
            <li>Idempotent writes — re-seeding leaves the graph byte-identical</li>
            <li>Never in the decision path — verified with Neo4j stopped</li>
            <li>Document text is never stored, only 120-character previews</li>
            <li>Renders in the console even with the graph database off</li>
          </ul>
        </div>

        <div ref={ref} className={`lp-graph-card${visible ? " lp-graph--in" : ""}`}>
          <svg viewBox="0 30 850 320" role="img" aria-label="Decision graph for the casual leave example">
            <defs>
              <marker id="lp-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0 0L10 5L0 10z" fill="#64748b" />
              </marker>
            </defs>
            {E.map(([a, b, label, color], i) => {
              const A = N[a];
              const B = N[b];
              const x1 = A.x + W / 2;
              const y1 = A.y + H / 2;
              const x2 = B.x + W / 2;
              const y2 = B.y + H / 2;
              const dashed = label === "SUPERSEDES";
              return (
                <g key={i} className="lp-edge" style={{ "--i": i }}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth="1.6"
                    strokeDasharray={dashed ? "5 5" : undefined} pathLength="1" className={dashed ? "lp-edge-dashed" : "lp-edge-line"} />
                  <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} fill={color} className="lp-edge-label">
                    {label}
                  </text>
                </g>
              );
            })}
            {Object.entries(N).map(([id, n], i) => (
              <g key={id} className="lp-node" style={{ "--i": i }} transform={`translate(${n.x} ${n.y})`}>
                <rect width={W} height={H} rx="9" fill="#0f1623" stroke={n.c} strokeWidth="1.4" />
                <circle cx="14" cy={H / 2} r="4" fill={n.c} />
                <text x="26" y={H / 2 + 4} className="lp-node-label">{n.label}</text>
              </g>
            ))}
          </svg>
        </div>
      </div>
    </section>
  );
}

// ── Insights ────────────────────────────────────────────────────────────────

const INSIGHTS = [
  ["Conflict hotspots", "Which document pairs contradict each other most often across all decisions."],
  ["Stale retrievals", "Which documents keep being retrieved while a newer version already exists."],
  ["Abstention topics", "Which subjects most often end in ABSTAIN — your documentation gaps, ranked."],
  ["Blast radius", "Every past decision that leaned on a given document. Essential when one is found wrong."],
  ["Escalation clusters", "Escalations grouped by shared root cause, so one fix clears many."],
];

function Insights() {
  return (
    <section id="insights" className="lp-section lp-section--alt">
      <div className="lp-container">
        <SectionHead eyebrow="Beyond one answer" title="Find out which document to go fix." center>
          Because every decision is stored with its evidence, AEGIS answers
          questions no single-request guardrail can — live, from real decisions.
        </SectionHead>
        <div className="lp-grid lp-grid--insights">
          {INSIGHTS.map(([title, body], i) => (
            <Spotlight key={title} className="lp-card lp-card--insight reveal" style={{ "--d": `${i * 70}ms` }}>
              <span className="lp-card-index">{String(i + 1).padStart(2, "0")}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </Spotlight>
          ))}
          <a href="#insights" className="lp-card lp-card--cta reveal" style={{ "--d": "350ms" }}>
            <h3>Open the insights dashboard</h3>
            <p>See all five, running on stored decisions.</p>
            <span className="lp-arrow" aria-hidden="true">→</span>
          </a>
        </div>
      </div>
    </section>
  );
}

// ── Stats ───────────────────────────────────────────────────────────────────

function Stat({ value, decimals = 0, suffix = "", label, note }) {
  const [ref, shown] = useCountUp(value, { decimals });
  return (
    <div ref={ref} className="lp-stat reveal">
      <strong>
        {shown}
        <span>{suffix}</span>
      </strong>
      <p>{label}</p>
      <small>{note}</small>
    </div>
  );
}

function Stats() {
  return (
    <section className="lp-section lp-stats-section">
      <div className="lp-container">
        <SectionHead eyebrow="Measured, reproducible" title="Numbers you can rerun with one command." center />
        <div className="lp-stats">
          <Stat value={456} label="Automated tests" note="Green CI on main" />
          <Stat value={58} suffix=" ms" label="Median decision latency" note="CPU, excluding model load" />
          <Stat value={83.3} decimals={1} suffix="%" label="Abstention precision" note="12-case development split" />
          <Stat value={6} label="Real signals" note="No placeholders" />
        </div>
        <p className="lp-honest reveal">
          The locked test split stays sealed until the system is frozen, and
          known limitations are published in the repository — not discovered at
          judging.
        </p>
      </div>
    </section>
  );
}

// ── Developers ──────────────────────────────────────────────────────────────

const CODE = `from app.core.evaluator import Evaluator
from app.evidence.registry import default_signals

aegis = Evaluator(default_signals())
verdict = aegis.evaluate(request)

verdict.decision        # ESCALATE
verdict.reasons         # [CONTRADICTION, STALE_EVIDENCE]`;

function Developers() {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(CODE);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable — ignore */
    }
  }
  return (
    <section id="developers" className="lp-section">
      <div className="lp-container lp-split">
        <div>
          <SectionHead eyebrow="For developers" title="Drop it into an existing RAG stack in five lines.">
            Model-agnostic middleware, not a platform. Any OpenAI-compatible
            provider with a fallback chain. SQLite for audit, Docker Compose for
            the graph, no managed service required.
          </SectionHead>
          <ul className="lp-checklist lp-checklist--good reveal">
            <li>Prompt injection is treated as data, never as instructions</li>
            <li>Fails safe — a model failure degrades to ABSTAIN</li>
            <li>Policy is configuration: a YAML edit and a restart</li>
          </ul>
        </div>
        <div className="lp-code reveal">
          <div className="lp-demo-bar">
            <span className="lp-dots"><i /><i /><i /></span>
            <span className="lp-demo-title">integrate.py</span>
            <button type="button" className="lp-copy" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <pre>
            <code>
              {CODE.split("\n").map((line, i) => (
                <span key={i} className={line.trim().startsWith("verdict.") ? "lp-code-dim" : undefined}>
                  {line || " "}
                  {"\n"}
                </span>
              ))}
            </code>
          </pre>
        </div>
      </div>
    </section>
  );
}

// ── CTA + footer ────────────────────────────────────────────────────────────

function FinalCta() {
  return (
    <section className="lp-section">
      <div className="lp-container">
        <div className="lp-cta reveal">
          <GraphField density={0.45} />
          <div className="lp-cta-inner">
            <h2>Close the gap between a confident answer and a correct one.</h2>
            <p>Run the console locally against the demo HR documents in under a minute.</p>
            <div className="lp-hero-ctas lp-center-row">
              <a className="lp-btn lp-btn--primary" href="#workspace">
                Launch the console <span aria-hidden="true">→</span>
              </a>
              <a className="lp-btn lp-btn--ghost" href="#graph">
                Explore a decision graph
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer-inner">
        <div>
          <Logo />
          <p>Open-source uncertainty middleware for AI systems.</p>
        </div>
        <div className="lp-footer-cols">
          <div>
            <h4>Product</h4>
            <a href="#workspace">Workspace</a>
            <a href="#graph">Decision graph</a>
            <a href="#insights">Insights</a>
            <a href="#escalations">Escalations</a>
          </div>
          <div>
            <h4>Learn</h4>
            <button type="button" onClick={() => scrollToId("how")}>How it works</button>
            <button type="button" onClick={() => scrollToId("signals")}>Signals</button>
            <button type="button" onClick={() => scrollToId("developers")}>Developers</button>
          </div>
        </div>
      </div>
      <div className="lp-container lp-footer-base">
        <span>© 2026 AEGIS · MIT licensed</span>
        <span>Evidence before confidence</span>
      </div>
    </footer>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────

export default function Landing() {
  const ref = useRevealAll();
  useEffect(() => {
    document.title = "AEGIS — AI answers you can trust";
  }, []);
  return (
    <div className="lp" ref={ref}>
      <Nav />
      <main>
        <Hero />
        <Marquee />
        <Problem />
        <HowItWorks />
        <Signals />
        <Decisions />
        <GraphShowcase />
        <Insights />
        <Stats />
        <Developers />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}
