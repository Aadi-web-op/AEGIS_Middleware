import { lazy, Suspense, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import {
  apiRequest,
  canTransition,
  apiUrl,
  display,
  graphLabel,
  score,
  decisions,
  statusValues,
  type RecordData,
} from "@/lib/aegis-api";
import { useRecords, useService } from "./service";
import { ImpactLookup, IngestDocument } from "./ingest";
import { Briefing } from "./briefing";
export { Evaluation } from "./evaluation";
const TraceGraph = lazy(() =>
  import("./graph-view").then((module) => ({ default: module.TraceGraph })),
);
import { Link } from "@tanstack/react-router";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  Clock3,
  Database,
  FileText,
  GitBranch,
  Info,
  Layers,
  Minus,
  Network,
  Play,
  Plus,
  RefreshCw,
  ScanLine,
  Server,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  ConnectionNotice,
  EmptyState,
  EvaluateLink,
  Footer,
  PageHeader,
  SearchField,
  SectionHeading,
} from "./console";

export function Overview() {
  const [period, setPeriod] = useState("Last 7 days");
  const findings = useRecords("/v1/insights/conflicting-document-pairs?limit=5");
  const { base, connected, graph } = useService();
  const recent = useQuery({
    queryKey: ["aegis", base, "recent"],
    queryFn: async () =>
      (
        await Promise.all(
          decisions.map((d) =>
            apiRequest<RecordData[]>(
              base,
              `/v1/insights/decisions-by-decision?decision=${d}&limit=5`,
            ),
          ),
        )
      )
        .flat()
        .sort((a, b) => display(b["timestamp"]).localeCompare(display(a["timestamp"])))
        .slice(0, 5),
    enabled: Boolean(base),
    retry: false,
  });
  const metrics = [
    { label: "Requests logged", context: "All evaluation requests", icon: Layers },
    {
      label: "Decisions in graph",
      context: "Persisted to Neo4j",
      icon: Network,
      value: graph?.connected ? graph.counts["Decision"] : undefined,
    },
    { label: "Escalation rate", context: "Decisions requiring human review", icon: ArrowUpRight },
    { label: "Abstention rate", context: "Decisions with insufficient evidence", icon: Minus },
  ];
  return (
    <main className="content">
      <PageHeader
        title="Overview"
        description="Monitor AI reliability. Investigate uncertainty. Build trust."
      >
        <select aria-label="Time period" value={period} onChange={(e) => setPeriod(e.target.value)}>
          {["Last 24 hours", "Last 7 days", "Last 30 days", "All time"].map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
        <EvaluateLink />
      </PageHeader>
      <ConnectionNotice />
      <Briefing />
      <div className="metrics">
        {metrics.map((metric) => (
          <div className="metric" key={metric.label}>
            <div className="metric-label">
              <span>{metric.label}</span>
              <metric.icon />
            </div>
            <div className="metric-value">
              {"value" in metric && metric.value !== undefined ? metric.value : "—"}
            </div>
            <div className="metric-context">{metric.context}</div>
          </div>
        ))}
      </div>
      <div className="analysis-layout">
        <section className="section">
          <SectionHeading
            title="Decision distribution"
            description="Outcomes across evaluated requests"
          >
            <span className="minor-label">Aggregate endpoint unavailable</span>
          </SectionHeading>
          <div className="distribution" aria-label="Decision distribution unavailable">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="legend-grid">
            {[
              { label: "ANSWER", color: "text-answer" },
              { label: "CAVEAT", color: "text-caveat" },
              { label: "ESCALATE", color: "text-escalate" },
              { label: "ABSTAIN", color: "text-abstain" },
            ].map((item) => (
              <div key={item.label}>
                <span className={`decision-label ${item.color}`}>
                  <i />
                  {item.label}
                </span>
                <div className="legend-value">
                  — <small>— %</small>
                </div>
              </div>
            ))}
          </div>
          <div className="panel-foot">
            <span>Total evaluated decisions</span>
            <span className="font-mono">—</span>
          </div>
          <div className="flex items-center gap-2 mt-4 text-[10px] text-muted-foreground">
            <Info size={12} />
            Generation failures are tracked separately.
          </div>
        </section>
        <section className="section">
          <SectionHeading
            title="Intelligence findings"
            description="Patterns across decisions and evidence"
          >
            <Button asChild variant="ghost" size="icon" title="Open intelligence">
              <Link to="/intelligence">
                <ArrowUpRight />
              </Link>
            </Button>
          </SectionHeading>
          {findings.data?.length ? (
            <div className="finding-list">
              {findings.data.map((finding, i) => (
                <Link to="/intelligence" className="finding-row" key={i}>
                  <span className="text-caveat">
                    <TriangleAlert size={14} />
                  </span>
                  <div>
                    <h3>Contradiction signal</h3>
                    <p>{display(finding["query"])}</p>
                    <span>{display(finding["request_id"])}</span>
                  </div>
                  <ArrowUpRight size={14} />
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={ScanLine}
              title="No intelligence available yet"
              description="Cross-decision findings will appear here once evaluation data is connected."
            />
          )}
        </section>
      </div>
      <section className="section recent-section">
        <SectionHeading
          title="Recent decisions"
          description="The latest evaluations and their evidence trails"
        >
          <Button asChild variant="ghost" size="sm">
            <Link to="/decisions">
              View all decisions <ArrowRight />
            </Link>
          </Button>
        </SectionHeading>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {[
                  "Request ID",
                  "Question",
                  "Decision",
                  "Answerability",
                  "Evidence",
                  "Evaluated at",
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.data?.map((row, i) => (
                <tr key={i}>
                  <td>
                    <Link to="/decisions" className="text-primary">
                      {display(row["request_id"])}
                    </Link>
                  </td>
                  <td>{display(row["query"])}</td>
                  <td>{display(row["decision"])}</td>
                  <td>{score(row["answerability_score"])}</td>
                  <td>—</td>
                  <td>{display(row["timestamp"])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!recent.data?.length && (
          <div className="table-empty">
            <EmptyState
              icon={GitBranch}
              title="Your decision history starts here"
              description={
                recent.error
                  ? recent.error.message
                  : "No evaluations are available. Connect your backend to inspect real decisions and their evidence."
              }
            />
          </div>
        )}
      </section>
      <div className="operational-strip">
        <span>
          <Server size={12} />
          API <span className="status-dot" />
          {connected ? "Connected" : "Not connected"}
        </span>
        <span>
          <Database size={12} />
          Neo4j <span className="status-dot" />
          {graphLabel(graph)}
        </span>
        <span>
          <TriangleAlert size={12} />
          Generation failures <span className="font-mono">—</span>
        </span>
        <Link to="/system" className="flex items-center gap-1">
          System details <ArrowRight size={12} />
        </Link>
      </div>
      <Footer />
    </main>
  );
}

type TableKind = "decisions" | "documents" | "escalations" | "intelligence";
const tableSettings = {
  decisions: {
    title: "Decisions",
    description: "Investigate historical evaluations and follow the evidence behind every outcome.",
    search: "Search request IDs or questions…",
    columns: [
      "Request ID",
      "Question",
      "Decision",
      "Answerability",
      "Evidence",
      "Policy",
      "Evaluated at",
    ],
    empty: "No decisions available",
    detail: "Your real evaluation history will appear here when the AEGIS backend is connected.",
    icon: GitBranch,
  },
  documents: {
    title: "Documents",
    description: "Understand source freshness, conflicts, and the impact of your evidence.",
    search: "Search documents or sources…",
    columns: ["Document", "Version", "Source", "Freshness", "Conflicts", "Related decisions"],
    empty: "No documents available",
    detail:
      "Connected evidence sources and document versions will appear here. No sources are connected yet.",
    icon: FileText,
  },
  escalations: {
    title: "Escalations",
    description: "Review uncertain decisions with their claims, reasons, and supporting evidence.",
    search: "Search escalations…",
    columns: ["Request ID", "Priority", "Reason", "Status", "Evidence", "Created at"],
    empty: "Escalation queue unavailable",
    detail:
      "Connect the AEGIS backend to view cases requiring human review and their current resolution status.",
    icon: TriangleAlert,
  },
  intelligence: {
    title: "Cross-decision intelligence",
    description: "Find recurring patterns. Trace their sources. Understand their impact.",
    search: "Search findings or evidence…",
    columns: ["Finding", "Category", "Severity", "Affected source", "Decisions", "Last observed"],
    empty: "Awaiting cross-decision intelligence",
    detail:
      "Findings are derived from real evaluations and graph relationships. Connect your backend to investigate patterns.",
    icon: ScanLine,
  },
};
export function DataWorkspace({ kind }: { kind: TableKind }) {
  const config = tableSettings[kind];
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All");
  const { base } = useService();
  const client = useQueryClient();
  const [selected, setSelected] = useState<RecordData | null>(null);
  const [page, setPage] = useState(0);
  const [ascending, setAscending] = useState(false);
  const decisionQuery = useQuery({
    queryKey: ["aegis", base, "decisions"],
    queryFn: async () =>
      (
        await Promise.all(
          decisions.map((d) =>
            apiRequest<RecordData[]>(
              base,
              `/v1/insights/decisions-by-decision?decision=${d}&limit=200`,
            ),
          ),
        )
      ).flat(),
    enabled: Boolean(base && kind === "decisions"),
    retry: false,
  });
  const insightPaths: Record<string, string> = {
    All: "conflicting-document-pairs",
    "Contradiction hotspots": "conflicting-document-pairs",
    "Stale document usage": "stale-document-retrievals",
    "Knowledge gaps": "abstain-topics",
    "Escalation root causes": "escalation-clusters",
  };
  const records = useRecords(
    kind === "escalations"
      ? "/v1/escalations?limit=500"
      : kind === "intelligence"
        ? `/v1/insights/${insightPaths[filter] ?? "conflicting-document-pairs"}?limit=100`
        : kind === "documents"
          ? "/v1/insights/outdated?limit=100"
          : null,
  );
  const query = kind === "decisions" ? decisionQuery : records;
  const rows = (query.data ?? [])
    .filter(
      (row) =>
        Object.values(row).some((v) => display(v).toLowerCase().includes(search.toLowerCase())) &&
        (filter === "All" ||
          (kind === "decisions"
            ? row["decision"] === filter
            : kind === "escalations"
              ? row["status"] === statusValues[filter as keyof typeof statusValues]
              : kind === "documents"
                ? filter === "Stale"
                : true)),
    )
    .sort(
      (a, b) =>
        display(a["timestamp"] ?? a["created_at"]).localeCompare(
          display(b["timestamp"] ?? b["created_at"]),
        ) * (ascending ? 1 : -1),
    );
  const update = useMutation({
    mutationFn: (status: string) =>
      apiRequest<RecordData>(
        base,
        `/v1/escalations/${display(selected?.["escalation_id"])}`,
        { status },
        "PATCH",
      ),
    onSuccess: (data) => {
      setSelected(data);
      client.invalidateQueries({ queryKey: ["aegis", base] });
    },
  });
  const cells = (r: RecordData) =>
    kind === "decisions"
      ? [
          r["request_id"],
          r["query"],
          r["decision"],
          score(r["answerability_score"]),
          null,
          null,
          r["timestamp"],
        ]
      : kind === "escalations"
        ? [
            r["request_id"],
            null,
            r["reason"],
            r["status"] === "dismissed" ? "Rejected" : r["status"],
            null,
            r["created_at"],
          ]
        : kind === "documents"
          ? [
              r["source"],
              r["outdated_version"],
              r["source"],
              "Outdated (API finding)",
              null,
              r["affected_decisions_count"],
            ]
          : [
              r["query"] ?? r["reason_code"],
              filter === "All" ? "Contradiction signal" : filter,
              null,
              null,
              r["request_id"] ?? r["request_ids"],
              r["timestamp"],
            ];
  const options =
    kind === "decisions"
      ? ["ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"]
      : kind === "escalations"
        ? ["Pending", "In Review", "Resolved", "Rejected"]
        : kind === "documents"
          ? ["Stale"]
          : [
              "Stale document usage",
              "Contradiction hotspots",
              "Knowledge gaps",
              "Escalation root causes",
            ];
  return (
    <main className="content">
      <PageHeader title={config.title} description={config.description}>
        {kind === "decisions" ? (
          <EvaluateLink />
        ) : (
          <span className="status-badge">
            <Database size={12} />
            {query.data ? "Live API data" : "Awaiting live data"}
          </span>
        )}
      </PageHeader>
      <ConnectionNotice />
      {kind === "intelligence" && (
        <div className="node-types">
          <span>
            <Clock3 />
            Document freshness
          </span>
          <span>
            <X />
            Contradiction sources
          </span>
          <span>
            <TriangleAlert />
            Escalation causes
          </span>
          <span>
            <Network />
            Knowledge gaps
          </span>
        </div>
      )}
      <div className="filters">
        <SearchField
          value={search}
          onChange={(value) => {
            setSearch(value);
            setPage(0);
          }}
          placeholder={config.search}
        />
        <select
          aria-label={`${config.title} filter`}
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(0);
          }}
        >
          <option value="All">
            {kind === "decisions"
              ? "All decisions"
              : kind === "escalations"
                ? "All statuses"
                : kind === "documents"
                  ? "All freshness states"
                  : "All categories"}
          </option>
          {options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
        <Button
          variant="outline"
          size="sm"
          disabled={!query.data}
          onClick={() => setAscending(!ascending)}
        >
          <ArrowDown />
          {ascending ? "Oldest first" : "Newest first"}
        </Button>
        <span className="minor-label ml-auto">
          {query.data ? `${rows.length} results` : "Results unavailable"}
        </span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {config.columns.map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(page * 20, page * 20 + 20).map((row, i) => (
              <tr key={i} className="selectable-row" onClick={() => setSelected(row)}>
                {cells(row).map((cell, index) => (
                  <td key={index}>
                    {index === 0 ? (
                      <Button variant="link" size="sm" onClick={() => setSelected(row)}>
                        {display(cell)}
                      </Button>
                    ) : (
                      display(cell)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <div className="table-empty">
          <EmptyState
            icon={config.icon}
            title={query.data ? "No matching records" : config.empty}
            description={
              query.error
                ? query.error.message
                : query.isFetching
                  ? "Loading live AEGIS records…"
                  : config.detail
            }
            link
          />
        </div>
      )}
      <div className="panel-foot">
        <span>
          {query.data
            ? `Page ${page + 1} · API returns up to ${kind === "decisions" ? "200 records per decision category" : "500 records"}`
            : "No data source connected"}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={(page + 1) * 20 >= rows.length}
            onClick={() => setPage(page + 1)}
          >
            Next
          </Button>
        </div>
      </div>
      {kind === "documents" && (
        <>
          <IngestDocument />
          <ImpactLookup />
        </>
      )}
      {selected && (
        <section className="section mt-7">
          <SectionHeading title="Record details">
            <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
              <X />
              Close
            </Button>
          </SectionHeading>
          {Object.entries(selected).map(([key, value]) => (
            <p className="record-property" key={key}>
              <span>{key}</span>
              {display(value)}
            </p>
          ))}
          {kind === "escalations" && (
            <div className="flex gap-2 flex-wrap mt-4">
              {Object.entries(statusValues).map(([label, value]) => (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={update.isPending || !canTransition(selected["status"], value)}
                  key={value}
                  onClick={() => update.mutate(value)}
                >
                  {label}
                </Button>
              ))}
            </div>
          )}
          {update.error && (
            <p role="alert" className="text-escalate text-xs mt-3">
              {update.error.message}
            </p>
          )}
        </section>
      )}
      <Footer />
    </main>
  );
}
export function Graph() {
  const [search, setSearch] = useState("");
  const [type, setType] = useState("All node types");
  const { result, graph } = useService();
  const graphUp = Boolean(graph?.connected);
  const live = useLiveGraph();
  const trace = live.enabled ? live.trace : result?.trace;
  const nodes =
    trace?.nodes?.filter(
      (n) =>
        (type === "All node types" || n["type"] === type) &&
        display(n).toLowerCase().includes(search.toLowerCase()),
    ) ?? [];
  const edges = trace?.edges ?? [];
  return (
    <main className="content">
      <PageHeader
        title="Graph explorer"
        description="Trace decisions to claims, evidence, and the documents behind them."
      >
        <Button
          size="sm"
          variant={live.enabled ? "secondary" : "outline"}
          onClick={() => live.setEnabled(!live.enabled)}
          title="Stream new decisions into the graph as they are evaluated"
        >
          {live.enabled ? `● Live · ${live.count} decision(s)` : "Go live"}
        </Button>
        <span className="status-badge">
          <Database size={12} />
          {live.enabled ? live.status : result?.trace ? "Evaluation trace" : "No trace available"}
        </span>
      </PageHeader>
      <ConnectionNotice />
      <div className="filters">
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search node identifiers or properties…"
        />
        <select aria-label="Node type" value={type} onChange={(e) => setType(e.target.value)}>
          {["All node types", "Decision", "Claim", "Evidence", "Document", "Reason"].map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </div>
      <div className="node-types">
        <span>
          <GitBranch className="text-primary" />
          Decision
        </span>
        <span>
          <Check className="text-answer" />
          Claim
        </span>
        <span>
          <Layers className="text-caveat" />
          Evidence
        </span>
        <span>
          <FileText />
          Document
        </span>
        <span>
          <Info />
          Reason
        </span>
      </div>
      <Suspense
        fallback={
          <EmptyState title="Loading graph workspace" description="Preparing the returned trace." />
        }
      >
        {nodes.length ? (
          <TraceGraph nodes={nodes} edges={edges} />
        ) : (
          <div className="graph-workspace">
            <div className="graph-canvas">
              <EmptyState
                icon={Network}
                title={graphUp ? "No trace loaded" : "Your evidence graph is not connected"}
                description={
                  graphUp
                    ? "Neo4j is connected. Run a live evaluation, or press Go live to stream new decisions into this view."
                    : "Actual Neo4j nodes and relationships will appear here once graph connectivity is available."
                }
                link={!graphUp}
              />
              <div className="graph-controls">
                <Button variant="outline" size="icon" disabled title="Zoom in">
                  <Plus />
                </Button>
                <Button variant="outline" size="icon" disabled title="Zoom out">
                  <Minus />
                </Button>
                <Button variant="outline" size="icon" disabled title="Reset view">
                  <RefreshCw />
                </Button>
              </div>
            </div>
            <aside className="graph-inspector">
              <h3>Node inspector</h3>
              <p>No node selected.</p>
              <div className="section mt-6">
                <h3>Relationships</h3>
                <p>
                  {graphUp
                    ? "Select a node to see its relationships."
                    : "Relationship data is unavailable until Neo4j is connected."}
                </p>
              </div>
            </aside>
          </div>
        )}
      </Suspense>
      <Footer />
    </main>
  );
}
type Trace = { nodes: RecordData[]; edges: RecordData[] };
/** Finale feature 6: new decisions stream in over SSE (/v1/graph/events). */
function useLiveGraph() {
  const { base } = useService();
  const [enabled, setEnabled] = useState(false);
  const [trace, setTrace] = useState<Trace>({ nodes: [], edges: [] });
  const [count, setCount] = useState(0);
  const [status, setStatus] = useState("Connecting…");
  useEffect(() => {
    if (!enabled || !base) return;
    const source = new EventSource(`${base}/v1/graph/events`);
    source.onopen = () => setStatus("Live: waiting for decisions");
    source.onerror = () => setStatus("Live stream reconnecting…");
    source.addEventListener("decision", (event) => {
      try {
        const incoming = JSON.parse((event as MessageEvent).data) as Partial<Trace>;
        setTrace((current) => {
          const ids = new Set(current.nodes.map((n) => display(n["id"])));
          const edgeKey = (e: RecordData) =>
            `${display(e["type"])}|${display(e["from"])}|${display(e["to"])}`;
          const edgeKeys = new Set(current.edges.map(edgeKey));
          return {
            nodes: [
              ...current.nodes,
              ...(incoming.nodes ?? []).filter((n) => !ids.has(display(n["id"]))),
            ].slice(-400),
            edges: [
              ...current.edges,
              ...(incoming.edges ?? []).filter((e) => !edgeKeys.has(edgeKey(e))),
            ].slice(-800),
          };
        });
        setCount((c) => c + 1);
        setStatus("Live: streaming");
      } catch {
        /* a malformed event costs that event, not the stream */
      }
    });
    source.addEventListener("reset", () => {
      setTrace({ nodes: [], edges: [] });
      setCount(0);
    });
    return () => source.close();
  }, [enabled, base]);
  return { enabled, setEnabled, trace, count, status };
}
export function System() {
  const { base, setBase, connected, health, error, checking, graph } = useService();
  const writer = graph?.configured ? graph.writer : undefined;
  const [url, setUrl] = useState(base);
  const [validation, setValidation] = useState("");
  const connect = () => {
    try {
      setBase(apiUrl(url));
      setValidation("");
    } catch (error) {
      setValidation(error instanceof Error ? error.message : "Invalid API URL.");
    }
  };

  const rows = [
    { name: "FastAPI backend", description: "Evaluation API and request processing", icon: Server },
    {
      name: "Neo4j connection",
      description: "Knowledge graph and evidence relationships",
      icon: Database,
    },
    {
      name: "Model readiness",
      description: "Answer generation and verification models",
      icon: Sparkles,
    },
    {
      name: "Policy version",
      description: "Active evaluation thresholds and risk policy",
      icon: ShieldCheck,
    },
    {
      name: "Graph persistence",
      description: "Decision writes and evidence traceability",
      icon: Network,
    },
    {
      name: "Failed graph writes",
      description: "Operational graph persistence failures",
      icon: TriangleAlert,
    },
  ];
  return (
    <main className="content">
      <PageHeader
        title="System"
        description="Operational health, service connectivity, and evaluation configuration."
      >
        <span className="status-badge">
          <span className="status-dot" />
          Not configured
        </span>
      </PageHeader>
      <ConnectionNotice />
      <SectionHeading
        title="Service health"
        description="Status is reported by connected services, never inferred."
      />
      <div className="system-list">
        {rows.map((row, index) => (
          <div className="system-row" key={row["name"]}>
            <div className="system-name">
              <row.icon />
              <div>
                <h3>{row["name"]}</h3>
                <p>{row["description"]}</p>
              </div>
            </div>
            <span className="status-badge">
              <span className="status-dot" />
              {index === 0
                ? connected
                  ? display(health?.["status"])
                  : checking
                    ? "Checking…"
                    : base
                      ? "Unreachable"
                      : "Not connected"
                : index === 1
                  ? graphLabel(graph)
                  : index === 3
                    ? display(health?.["policy_version"])
                    : index === 4 && writer
                      ? `${writer.written} written, ${writer.pending} pending`
                      : index === 5 && writer
                        ? `${writer.failed} failed, ${writer.dropped} dropped`
                        : "Not reported by API"}
            </span>
          </div>
        ))}
      </div>
      <section className="section mt-7">
        <SectionHeading title="Connection configuration" />
        <p className="section-description mt-3 leading-7">
          Connect a reachable AEGIS API. Its allowed origins must include this console’s address.
          Neo4j connectivity and graph write counts are read from /v1/graph/status.
        </p>
        <div className="flex gap-3 mt-4">
          <Input
            aria-label="AEGIS API URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-aegis-service.example.com"
          />
          <Button onClick={connect} disabled={!url || checking}>
            {checking ? "Connecting…" : "Connect API"}
          </Button>
        </div>
        {(validation || error) && (
          <p className="text-escalate text-xs mt-3" role="alert">
            {validation || error}
          </p>
        )}
        {connected && (
          <p className="text-answer text-xs mt-3" role="status">
            AEGIS API connected. Policy {display(health?.["policy_version"])}.
          </p>
        )}
      </section>
      <Footer />
    </main>
  );
}
