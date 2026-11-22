import { Link } from "@tanstack/react-router";
import {
  ArrowRight,
  Blocks,
  Check,
  Code2,
  Minus,
  Plug,
  Puzzle,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Footer, PageHeader, SectionHeading } from "./console";

/**
 * Plans follow docs/product-readiness/FIRST_CUSTOMER_AND_PRICING_PLAN.md and the roadmap
 * follows MCP_AND_AGENT_ADDONS_ROADMAP.md. Set VITE_CONTACT_URL (a mailto: or a form URL)
 * to turn on the "Request a pilot" / "Talk to us" buttons.
 */
const CONTACT_URL = (import.meta.env["VITE_CONTACT_URL"] ?? "").trim();

interface Tier {
  name: string;
  status: string;
  price: string;
  unit?: string;
  alt?: string;
  summary: string;
  features: string[];
  cta: { label: string; to?: "/evaluation" | "/documents"; contact?: boolean };
  featured?: boolean;
}

const TIERS: Tier[] = [
  {
    name: "Community",
    status: "Available",
    price: "Free",
    unit: "self-hosted",
    summary: "The open-source core (MIT). Run it on your own infrastructure.",
    features: [
      "Evaluator API and policy profiles",
      "ANSWER / CAVEAT / ESCALATE / ABSTAIN decisions",
      "Trust Console",
      "Neo4j graph and intelligence (bring your own Neo4j)",
      "Fact Lock guardrail",
      "Community support",
    ],
    cta: { label: "Try the console", to: "/evaluation" },
  },
  {
    name: "Design Partner",
    status: "Accepting pilots",
    price: "₹15,000–25,000",
    unit: "/ month · 2–3 month minimum",
    alt: "or ₹40,000–60,000 fixed for a 6–8 week pilot",
    summary: "A hosted deployment for one real use case, with our engineers alongside you.",
    features: [
      "Dedicated hosted instance",
      "1 use case, ~200 documents, 20k evaluations / month",
      "Up to 5 console users",
      "~8 engineer-hours of integration help",
      "Weekly reliability and impact report",
      "End-of-pilot readout with measured results",
      "Data deleted at the end on request",
    ],
    cta: { label: "Request a pilot", contact: true },
    featured: true,
  },
  {
    name: "Business",
    status: "Coming soon",
    price: "₹15,000–25,000",
    unit: "/ month",
    summary: "Self-serve subscription for teams running AEGIS in production.",
    features: [
      "Everything in Community, hosted",
      "Self-serve API keys and usage metering",
      "Hosted graph and intelligence",
      "Self-serve report export",
      "Email support, business hours",
    ],
    cta: { label: "Join the waitlist", contact: true },
  },
  {
    name: "Enterprise",
    status: "Contact us",
    price: "Custom",
    summary: "For regulated teams that need private deployment and contracts.",
    features: [
      "Private cloud or on-prem deployment",
      "SSO (OIDC / SAML)",
      "Custom retention and bulk audit export",
      "Named engineer",
      "Contractual SLA",
    ],
    cta: { label: "Talk to us", contact: true },
  },
];

type Cell = boolean | string;
const COMPARISON: { feature: string; cells: [Cell, Cell, Cell, Cell] }[] = [
  { feature: "Evaluator API and policy profiles", cells: [true, true, true, true] },
  { feature: "Trust Console", cells: [true, true, true, true] },
  { feature: "Neo4j graph and intelligence", cells: ["Bring your own", "Hosted", "Hosted", true] },
  {
    feature: "Hosting and operations",
    cells: [false, "Dedicated instance", true, "Private / on-prem"],
  },
  {
    feature: "Onboarding and integration help",
    cells: ["Community", "Hands-on", "Email", "Named engineer"],
  },
  {
    feature: "Weekly reliability and impact report",
    cells: [false, true, "Self-serve export", true],
  },
  { feature: "SSO, custom retention, audit export", cells: [false, false, "Partial", true] },
  { feature: "Support / SLA", cells: [false, "Business hours", "Business hours", "Contract"] },
];

interface RoadmapItem {
  icon: LucideIcon;
  name: string;
  summary: string;
  points: string[];
  code?: string;
}

const ROADMAP: RoadmapItem[] = [
  {
    icon: Plug,
    name: "MCP server",
    summary:
      "Use AEGIS from Claude Desktop and any MCP-capable agent: check an answer, trace its evidence, ask which decisions a document affected.",
    points: [
      "aegis_evaluate · get_decision · trace_evidence",
      "get_intelligence · get_document_impact",
      "Scoped by API key role; every call audited",
    ],
  },
  {
    icon: Code2,
    name: "Python SDK",
    summary: "A typed client so adding AEGIS to an existing RAG app is a few lines of code.",
    points: ["Sync and async clients", "Retries, timeouts, fail-closed defaults"],
    code: `from aegis_client import Aegis

aegis = Aegis(api_key="...")
result = aegis.evaluate(query=q, answer=a, evidence=docs)
if result.decision == "ANSWER":
    send(a)`,
  },
  {
    icon: Puzzle,
    name: "Browser extension",
    summary:
      "Check AI chat answers in the browser against your workspace's approved documents before you rely on them.",
    points: ["Highlights unsupported claims", "Links each claim to its source document"],
  },
  {
    icon: Blocks,
    name: "LangChain & LlamaIndex adapters",
    summary:
      "Drop-in callback and post-processor that pass the retrieved sources to AEGIS automatically.",
    points: ["Uses the chain's own source documents", "Returns the decision and caveat text"],
  },
];

function TierAction({ tier }: { tier: Tier }) {
  const variant = tier.featured ? "default" : "outline";
  if (tier.cta.to)
    return (
      <Button asChild size="sm" variant={variant} className="w-full">
        <Link to={tier.cta.to}>
          {tier.cta.label} <ArrowRight />
        </Link>
      </Button>
    );
  if (CONTACT_URL)
    return (
      <Button asChild size="sm" variant={variant} className="w-full">
        <a
          href={CONTACT_URL}
          target={CONTACT_URL.startsWith("mailto:") ? undefined : "_blank"}
          rel="noreferrer"
        >
          {tier.cta.label} <ArrowRight />
        </a>
      </Button>
    );
  return (
    <Button
      size="sm"
      variant={variant}
      className="w-full"
      disabled
      title="Contact the AEGIS team directly"
    >
      {tier.cta.label}
    </Button>
  );
}

function CellValue({ value }: { value: Cell }) {
  if (value === true) return <Check size={14} className="text-answer" aria-label="Included" />;
  if (value === false)
    return <Minus size={14} className="text-muted-foreground" aria-label="Not included" />;
  return <span>{value}</span>;
}

export function Pricing() {
  return (
    <main className="content">
      <PageHeader
        title="Plans & Pricing"
        description="The core is open source. You pay for hosting, operations, integration help and insight reports."
      >
        <Button asChild size="sm" variant="outline">
          <Link to="/documents">Try it with sample documents</Link>
        </Button>
      </PageHeader>

      <div className="pricing-grid">
        {TIERS.map((tier) => (
          <section
            key={tier.name}
            className={`pricing-card ${tier.featured ? "is-featured" : ""}`}
            aria-labelledby={`tier-${tier.name}`}
          >
            <div className="pricing-top">
              <h2 id={`tier-${tier.name}`}>{tier.name}</h2>
              <span className={`pricing-status ${tier.featured ? "is-live" : ""}`}>
                {tier.status}
              </span>
            </div>
            <div className="pricing-price">{tier.price}</div>
            <div className="minor-label">{tier.unit ?? " "}</div>
            {tier.alt && <div className="minor-label mt-1">{tier.alt}</div>}
            <p className="pricing-summary">{tier.summary}</p>
            <ul className="pricing-features">
              {tier.features.map((f) => (
                <li key={f}>
                  <Check size={13} className="text-answer" aria-hidden />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <TierAction tier={tier} />
          </section>
        ))}
      </div>
      <p className="minor-label mt-3">
        Prices in INR, excluding GST. Pilots are invoiced directly (GST invoice, bank transfer or
        UPI). Early-access pricing; it may change as plans launch.
      </p>

      <section className="section mt-8">
        <SectionHeading title="Compare plans" />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Feature</th>
                {TIERS.map((t) => (
                  <th key={t.name}>{t.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map((row) => (
                <tr key={row.feature}>
                  <td>{row.feature}</td>
                  {row.cells.map((c, i) => (
                    <td key={i}>
                      <CellValue value={c} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section mt-8">
        <SectionHeading
          title="Coming soon"
          description="Integrations on the roadmap. They will work with every plan."
        />
        <div className="roadmap-grid">
          {ROADMAP.map((item) => (
            <article key={item.name} className="roadmap-card">
              <div className="pricing-top">
                <span className="roadmap-icon">
                  <item.icon size={16} />
                </span>
                <span className="pricing-status">Coming soon</span>
              </div>
              <h3>{item.name}</h3>
              <p className="pricing-summary">{item.summary}</p>
              <ul className="pricing-features">
                {item.points.map((p) => (
                  <li key={p}>
                    <ArrowRight size={12} aria-hidden />
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
              {item.code && (
                <>
                  <pre className="roadmap-code">
                    <code>{item.code}</code>
                  </pre>
                  <div className="minor-label">Preview. The package is not published yet.</div>
                </>
              )}
            </article>
          ))}
        </div>
      </section>
      <Footer />
    </main>
  );
}
