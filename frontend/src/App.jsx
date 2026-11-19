/**
 * AEGIS Trust Console – application shell and route switch.
 * Pages live in ./pages; routing is hash-based (see router.js).
 */
import { useEffect, useState } from "react";
import { API, useApi } from "./api.js";
import { href, useHashRoute } from "./router.js";
import { Icon, StatusDot } from "./ui/index.jsx";
import Overview from "./pages/Overview.jsx";
import Evaluate from "./pages/Evaluate.jsx";
import Decisions from "./pages/Decisions.jsx";
import Intelligence from "./pages/Intelligence.jsx";
import GraphExplorer from "./pages/GraphExplorer.jsx";
import Documents from "./pages/Documents.jsx";
import Escalations from "./pages/Escalations.jsx";
import System from "./pages/System.jsx";

const NAV = [
  {
    heading: "Evaluate",
    items: [
      { page: "overview", label: "Overview", icon: "overview" },
      { page: "evaluate", label: "Live evaluation", icon: "evaluate" },
    ],
  },
  {
    heading: "Investigate",
    items: [
      { page: "decisions", label: "Decisions", icon: "decisions" },
      { page: "intelligence", label: "Intelligence", icon: "intelligence" },
      { page: "graph", label: "Graph explorer", icon: "graph" },
      { page: "documents", label: "Documents", icon: "documents" },
    ],
  },
  {
    heading: "Operate",
    items: [
      { page: "escalations", label: "Escalations", icon: "escalations", badge: "pending" },
      { page: "system", label: "System", icon: "system" },
    ],
  },
];

const PAGES = {
  overview: Overview,
  evaluate: Evaluate,
  decisions: Decisions,
  intelligence: Intelligence,
  graph: GraphExplorer,
  documents: Documents,
  escalations: Escalations,
  system: System,
};

const TITLES = {
  overview: "Overview",
  evaluate: "Live evaluation",
  decisions: "Decisions",
  intelligence: "Intelligence",
  graph: "Graph explorer",
  documents: "Documents",
  escalations: "Escalations",
  system: "System",
};

function readTheme() {
  try {
    const t = localStorage.getItem("aegis-theme");
    if (t === "light" || t === "dark") return t;
  } catch {
    /* storage blocked */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function useTheme() {
  const [theme, setTheme] = useState(readTheme);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("aegis-theme", next);
    } catch {
      /* storage blocked */
    }
  };
  return [theme, toggle];
}

function Brand() {
  return (
    <a className="brand" href={href("overview")}>
      <span className="brand__mark" aria-hidden="true">
        <Icon name="shield" size={15} />
      </span>
      <span className="brand__name">
        AEGIS
        <span className="brand__sub">Trust console</span>
      </span>
    </a>
  );
}

function SystemStatus({ health, graph }) {
  const apiState = health.error ? "down" : health.data ? "ok" : "unknown";
  const g = graph.data;
  const graphState = graph.error ? "unknown" : !g ? "unknown" : g.connected ? "ok" : g.configured ? "down" : "warn";
  const graphLabel = !g ? "checking" : g.connected ? "connected" : g.configured ? "unreachable" : "not configured";
  return (
    <div className="sidebar__status">
      <div className="sidebar__status-row">
        <StatusDot state={apiState} label="API" />
        <span className="mono">{health.error ? "offline" : health.data ? `v${health.data.api_version}` : "…"}</span>
      </div>
      <div className="sidebar__status-row">
        <StatusDot state={graphState} label="Graph" />
        <span>{graphLabel}</span>
      </div>
      <div className="sidebar__status-row">
        <span>Policy</span>
        <span className="mono">{health.data?.policy_version ?? "—"}</span>
      </div>
    </div>
  );
}

export default function App() {
  const route = useHashRoute();
  const [theme, toggleTheme] = useTheme();
  const [navOpen, setNavOpen] = useState(false);
  const health = useApi("/v1/health", { interval: 30000 });
  const graph = useApi("/v1/graph/status", { interval: 30000 });
  const pending = useApi("/v1/escalations?status=pending&limit=500", { interval: 30000 });
  const pendingCount = Array.isArray(pending.data) ? pending.data.length : null;

  useEffect(() => {
    setNavOpen(false);
    document.title = `${TITLES[route.page] ?? "Console"} · AEGIS`;
    window.scrollTo(0, 0);
  }, [route.page]);

  useEffect(() => {
    if (!navOpen) return undefined;
    const onKey = (e) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  const Page = PAGES[route.page] ?? Overview;

  return (
    <div className="app">
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>
        Skip to content
      </a>
      <header className="topbar">
        <button type="button" className="icon-btn" aria-label="Open navigation" aria-expanded={navOpen} onClick={() => setNavOpen(true)}>
          <Icon name="menu" />
        </button>
        <Brand />
        <span className="topbar__status">
          <StatusDot state={health.error ? "down" : health.data ? "ok" : "unknown"} label={health.error ? "API offline" : "API"} />
        </span>
      </header>

      <div className={navOpen ? "nav-scrim is-open" : "nav-scrim"} onClick={() => setNavOpen(false)} aria-hidden="true" />
      <aside className={navOpen ? "sidebar is-open" : "sidebar"} aria-label="Primary">
        <Brand />
        <nav className="nav">
          {NAV.map((g) => (
            <div className="nav__group" key={g.heading}>
              <p className="nav__heading">{g.heading}</p>
              {g.items.map((it) => (
                <a
                  key={it.page}
                  href={href(it.page)}
                  className={route.page === it.page ? "nav__link is-active" : "nav__link"}
                  aria-current={route.page === it.page ? "page" : undefined}
                >
                  <Icon name={it.icon} className="icon" />
                  {it.label}
                  {it.badge === "pending" && pendingCount > 0 && (
                    <span className="nav__badge" title={`${pendingCount} pending escalations`}>
                      {pendingCount}
                    </span>
                  )}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar__foot">
          <SystemStatus health={health} graph={graph} />
          <div className="row row--between">
            <span className="mono" title="API base URL">
              {API.replace(/^https?:\/\//, "")}
            </span>
            <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
              <Icon name={theme === "dark" ? "sun" : "moon"} size={13} />
              {theme === "dark" ? "Light" : "Dark"}
            </button>
          </div>
        </div>
      </aside>

      <main className="main" id="main" tabIndex={-1}>
        <div className="content">
          <Page args={route.args} graphStatus={graph} health={health} onEscalationsChanged={pending.reload} />
        </div>
      </main>
    </div>
  );
}
