import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Clock3, FileWarning, GitCompare, ScrollText, ShieldAlert } from "lucide-react";
import graphImage from "@/assets/evidence-graph.jpg";
import reviewImage from "@/assets/review-desk.jpg";

function Reveal({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => e?.isIntersecting && (el.classList.add("is-visible"), io.disconnect()),
      { threshold: 0.15 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={`reveal ${className}`}>
      {children}
    </div>
  );
}

const problems = [
  { icon: ShieldAlert, title: "Unsupported claims", text: "Each sentence of an answer is split into claims and checked for entailment against the supplied evidence before it reaches a user." },
  { icon: GitCompare, title: "Conflicting sources", text: "Contradictions between passages are recorded as graph relationships, so teams can see which documents disagree and which decisions they touched." },
  { icon: Clock3, title: "Stale knowledge", text: "Time-sensitive questions apply a freshness signal, lowering answerability when evidence is outdated." },
  { icon: ScrollText, title: "No audit trail", text: "Every request, decision, reason code and policy version is persisted, giving reviewers a reproducible record." },
];

const steps = [
  ["01", "Retrieve", "Collect the answer and the passages it relies on."],
  ["02", "Decompose", "Split the answer into individually verifiable claims."],
  ["03", "Score", "Measure relevance, entailment, contradiction, freshness, completeness and ambiguity."],
  ["04", "Decide", "Apply the risk-profile policy: ANSWER, CAVEAT, ESCALATE or ABSTAIN."],
  ["05", "Trace", "Write the decision, claims and evidence links to the Neo4j graph."],
];

export function Briefing() {
  return (
    <div className="briefing">
      <Reveal className="brief-hero">
        <div className="brief-hero-copy">
          <span className="eyebrow">AI governance middleware</span>
          <h2>Every AI answer, checked against its evidence before anyone relies on it.</h2>
          <p>
            AEGIS sits between your language model and your users. It verifies claims, weighs
            uncertainty, and returns a policy-backed decision with a traceable record — so
            governance is enforced at runtime, not reconstructed after an incident.
          </p>
          <div className="brief-links">
            <Link to="/evaluation">Run an evaluation <ArrowRight size={12} /></Link>
            <Link to="/graph">Explore the evidence graph <ArrowRight size={12} /></Link>
          </div>
        </div>
        <figure className="brief-figure">
          <img src={graphImage} alt="Schematic of documents flowing through claim checks into a decision node" width={1600} height={800} />
          <figcaption>Evidence → claims → decision → outcome</figcaption>
        </figure>
      </Reveal>

      <Reveal>
        <div className="section-heading"><h2>Governance failures AEGIS addresses</h2></div>
        <div className="problem-grid">
          {problems.map((p) => (
            <article className="problem-card" key={p.title}>
              <p.icon size={16} />
              <h3>{p.title}</h3>
              <p>{p.text}</p>
            </article>
          ))}
        </div>
      </Reveal>

      <Reveal className="brief-split">
        <div>
          <div className="section-heading"><h2>Decision pipeline</h2></div>
          <ol className="pipeline">
            {steps.map(([n, t, d]) => (
              <li key={n}>
                <span className="font-mono">{n}</span>
                <div><strong>{t}</strong><p>{d}</p></div>
              </li>
            ))}
          </ol>
        </div>
        <figure className="brief-photo">
          <img src={reviewImage} alt="Reviewer examining source documents for an escalated decision" width={1200} height={912} loading="lazy" />
          <figcaption>
            <FileWarning size={12} /> Escalated decisions route to a human reviewer with claims and evidence attached.
          </figcaption>
        </figure>
      </Reveal>
    </div>
  );
}
