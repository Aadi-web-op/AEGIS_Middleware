import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowRight,
  Bell,
  Box,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Database,
  FileText,
  GitBranch,
  LayoutDashboard,
  Menu,
  Network,
  PanelLeftClose,
  Play,
  Search,
  Settings2,
  Shield,
  ShieldCheck,
  Sparkles,
  SunMoon,
  Terminal,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useService } from "./service";
import { display, graphLabel } from "@/lib/aegis-api";

export const navigation = [
  {
    group: "EVALUATE",
    items: [
      { name: "Overview", path: "/" as const, icon: LayoutDashboard },
      { name: "Live Evaluation", path: "/evaluation" as const, icon: Activity },
    ],
  },
  {
    group: "INVESTIGATE",
    items: [
      { name: "Decisions", path: "/decisions" as const, icon: GitBranch },
      { name: "Intelligence", path: "/intelligence" as const, icon: Sparkles },
      { name: "Graph Explorer", path: "/graph" as const, icon: Network },
      { name: "Documents", path: "/documents" as const, icon: FileText },
    ],
  },
  {
    group: "OPERATE",
    items: [
      { name: "Escalations", path: "/escalations" as const, icon: ShieldCheck },
      { name: "System", path: "/system" as const, icon: Settings2 },
    ],
  },
];

export function ConsoleShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    const aliases = {
      "#workspace": "/evaluation",
      "#graph": "/graph",
      "#insights": "/intelligence",
      "#escalations": "/escalations",
      "#home": "/",
    } as const;
    const target = aliases[window.location.hash as keyof typeof aliases];
    if (target) navigate({ to: target, replace: true });
  }, [navigate]);
  const { connected, health, base, graph } = useService();
  const pathname = useLocation({ select: (location) => location.pathname });
  const current = navigation
    .map((group) => group.items.find((item) => item.path === pathname))
    .find((item) => item !== undefined);
  return (
    <div className="console-shell">
      <aside className={`console-sidebar ${open ? "is-open" : ""}`}>
        <Link to="/" className="brand" onClick={() => setOpen(false)}>
          <Shield className="brand-symbol" strokeWidth={1.7} />
          <div>
            <div className="brand-name">AEGIS</div>
            <div className="brand-caption">Trust Console</div>
          </div>
        </Link>
        <div className="workspace">
          <span className="workspace-icon">
            <Box size={14} />
          </span>
          <span>Default workspace</span>
          <ChevronDown size={12} className="ml-auto text-muted-foreground" />
        </div>
        <nav aria-label="Main navigation">
          {navigation.map((group) => (
            <div className="nav-group" key={group.group}>
              <div className="nav-label">{group.group}</div>
              {group.items.map((item) => (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={() => setOpen(false)}
                  className={`nav-item ${pathname === item.path ? "active" : ""}`}
                >
                  <item.icon />
                  <span>{item.name}</span>
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-line">
            <span>
              <span className="status-dot" />
              API connection
            </span>
            <span>{connected ? "Connected" : base ? "Unreachable" : "Offline"}</span>
          </div>
          <div className="connection-line">
            <span>
              <span className="status-dot" />
              Neo4j
            </span>
            <span>{graphLabel(graph)}</span>
          </div>
          <div className="connection-line">
            <span>Policy version</span>
            <span className="font-mono">{display(health?.["policy_version"])}</span>
          </div>
          <div className="connection-line mb-0">
            <span>
              <Terminal size={12} />
              Environment
            </span>
            <span>Unconfigured</span>
          </div>
        </div>
        <div className="sidebar-footer">
          <div className="avatar">AG</div>
          <div>
            AEGIS workspace
            <div className="text-muted-foreground text-[10px]">AI Trust & Intelligence</div>
          </div>
          <SunMoon size={14} className="ml-auto text-muted-foreground" aria-label="Dark theme" />
        </div>
      </aside>
      <div className="console-main">
        <header className="topbar">
          <div className="topbar-context">
            <Button
              variant="ghost"
              size="icon"
              className="mobile-menu"
              aria-label={open ? "Close navigation" : "Open navigation"}
              onClick={() => setOpen(!open)}
            >
              {open ? <PanelLeftClose /> : <Menu />}
            </Button>
            <span>Trust Console</span>
            <ChevronRight size={12} />
            <span className="text-foreground">{current?.name}</span>
          </div>
          <div className="topbar-tools">
            <span className="topbar-descriptor">AI Trust & Intelligence Platform</span>
            <span className="environment">LOCAL</span>
            <Button asChild variant="ghost" size="icon" title="System connection status">
              <Link to="/system">
                <CircleHelp />
              </Link>
            </Button>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      <div className="page-actions">{children}</div>
    </div>
  );
}
export function ConnectionNotice() {
  const { connected, checking, error, base } = useService();
  if (connected) return null;
  return (
    <div className="connection-notice">
      <Database size={15} />
      <span>
        <strong>
          {checking ? "Checking connection." : error ? "API unavailable." : "Awaiting connection."}
        </strong>{" "}
        {error
          ? "The configured AEGIS API could not be reached. Check its URL and allowed origins."
          : base
            ? "Waiting for AEGIS service health."
            : "Connect your AEGIS backend to view live evaluations and intelligence."}
      </span>
      <Link to="/system">
        System status <ArrowRight size={12} />
      </Link>
    </div>
  );
}
export function EmptyState({
  icon: Icon = Database,
  title,
  description,
  link,
}: {
  icon?: typeof Database;
  title: string;
  description: string;
  link?: boolean;
}) {
  return (
    <div className="empty-state">
      <Icon className="empty-icon" />
      <h3>{title}</h3>
      <p>{description}</p>
      {link && (
        <Link to="/system">
          View connection status <ArrowRight size={12} />
        </Link>
      )}
    </div>
  );
}
export function SectionHeading({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <>
      <div className="section-heading">
        <h2>{title}</h2>
        {children}
      </div>
      {description && <p className="section-description">{description}</p>}
    </>
  );
}
export function Footer() {
  return (
    <footer className="console-footer">
      <span>
        <ShieldCheck size={12} />
        Evidence-backed decisions. Traceable intelligence.
      </span>
      <span>
        AEGIS Trust Console <span className="text-border">/</span> Powered by Neo4j
      </span>
    </footer>
  );
}
export function EvaluateLink() {
  return (
    <Button asChild size="sm">
      <Link to="/evaluation">
        <Play size={13} />
        New evaluation
      </Link>
    </Button>
  );
}
export function SearchField({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className="search-input">
      <Search />
      <input
        className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
export { Bell, Workflow };
