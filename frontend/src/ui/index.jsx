/** Small UI kit shared by every page. */
import { useEffect, useId, useRef, useState } from "react";
import { API } from "../api.js";
import { CLAIM_CLS, DECISION_META, SEVERITY_CLS, decisionCls } from "../format.js";

// ── Icon ──────────────────────────────────────────────────────────────────

const ICONS = {
  shield: "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z",
  overview: "M4 4h7v7H4z M13 4h7v4h-7z M13 10h7v10h-7z M4 13h7v7H4z",
  evaluate: "M5 12l4 4L19 6",
  decisions: "M4 6h16 M4 12h16 M4 18h10",
  intelligence: "M4 20V11 M10 20V5 M16 20v-6 M3 20h18",
  graph:
    "M6 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M18 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M12 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M8 6h8 M7 8l4 8 M17 8l-4 8",
  documents: "M7 3h7l5 5v13H7z M14 3v5h5 M10 13h6 M10 17h6",
  escalations: "M12 9v4 M12 17h.01 M10.3 3.9L2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  system: "M4 7h16 M4 12h16 M4 17h16 M8 5v4 M15 10v4 M10 15v4",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7 M20 4v7h-7",
  close: "M6 6l12 12 M18 6L6 18",
  plus: "M12 5v14 M5 12h14",
  trash: "M5 7h14 M10 11v6 M14 11v6 M7 7l1 13h8l1-13 M9 7V4h6v3",
  copy: "M9 9h11v11H9z M5 15V4h11",
  check: "M5 12l4 4L19 6",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  external: "M14 4h6v6 M20 4l-9 9 M18 14v6H4V6h6",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  sun: "M12 4V2 M12 22v-2 M4 12H2 M22 12h-2 M5.6 5.6L4.2 4.2 M19.8 19.8l-1.4-1.4 M5.6 18.4l-1.4 1.4 M19.8 4.2l-1.4 1.4 M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8",
  moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  fit: "M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5",
  zoomin: "M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14 M20 20l-4-4 M11 8v6 M8 11h6",
  zoomout: "M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14 M20 20l-4-4 M8 11h6",
  expand: "M12 5v14 M5 12h14",
  chevron: "M9 6l6 6-6 6",
};

export function Icon({ name, size = 16, className }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICONS[name] ?? ""} />
    </svg>
  );
}

// ── Layout ────────────────────────────────────────────────────────────────

export function PageHeader({ title, description, children }) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children && <div className="page-header__actions">{children}</div>}
    </header>
  );
}

export function Panel({ title, description, actions, children, flush = false, className = "", id }) {
  return (
    <section className={`panel ${className}`} id={id}>
      {(title || actions) && (
        <div className="panel__head">
          <div>
            {title && <h2 className="panel__title">{title}</h2>}
            {description && <p className="panel__desc">{description}</p>}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </div>
      )}
      <div className={flush ? "panel__body panel__body--flush" : "panel__body"}>{children}</div>
    </section>
  );
}

// ── Chips ─────────────────────────────────────────────────────────────────

export function DecisionBadge({ decision, size = "md" }) {
  if (!decision) return <span className="chip chip--abstain">Unknown</span>;
  return (
    <span className={`chip chip--${decisionCls(decision)} chip--${size}`}>
      <span className="chip__dot" aria-hidden="true" />
      {DECISION_META[decision]?.label ?? decision}
    </span>
  );
}

export function ClaimChip({ status }) {
  const cls = CLAIM_CLS[status] ?? "abstain";
  const label = status ? status.charAt(0) + status.slice(1).toLowerCase() : "Unknown";
  return <span className={`chip chip--${cls}`}>{label}</span>;
}

export function SeverityChip({ severity }) {
  const cls = SEVERITY_CLS[severity] ?? "abstain";
  return <span className={`chip chip--${cls} chip--outline`}>{severity ?? "—"}</span>;
}

export function Tag({ children, tone = "neutral", title }) {
  return (
    <span className={`tag tag--${tone}`} title={title}>
      {children}
    </span>
  );
}

export function StatusDot({ state, label }) {
  return (
    <span className="status-dot-wrap">
      <span className={`status-dot status-dot--${state}`} aria-hidden="true" />
      {label}
    </span>
  );
}

export function Mono({ children, title }) {
  return (
    <span className="mono" title={title}>
      {children}
    </span>
  );
}

// ── States ────────────────────────────────────────────────────────────────

export function Loading({ rows = 3, label = "Loading" }) {
  return (
    <div className="loading" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state state--empty">
      <p className="state__title">{title}</p>
      {children && <p className="state__body">{children}</p>}
      {action && <div className="state__action">{action}</div>}
    </div>
  );
}

const ERROR_TITLE = {
  offline: "Graph database offline",
  unavailable: "Endpoint unavailable",
  network: "API unreachable",
  notfound: "Not found",
  http: "Request failed",
};

export function ErrorState({ error, onRetry, compact = false, title }) {
  if (!error) return null;
  const kind = error.kind ?? "http";
  let body = error.message;
  if (kind === "unavailable") body = `GET ${error.path?.split("?")[0]} is not served by this backend version.`;
  if (kind === "network") body = `Could not reach ${API}. Start the backend and retry.`;
  return (
    <div className={`state state--error state--${kind}${compact ? " state--compact" : ""}`} role="alert">
      <p className="state__title">{title ?? ERROR_TITLE[kind] ?? "Error"}</p>
      <p className="state__body">{body}</p>
      {onRetry && (
        <div className="state__action">
          <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}
    </div>
  );
}

/** Render loading / error / children for a useApi() result. */
export function Async({ q, rows = 3, children, errorTitle }) {
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} title={errorTitle} />;
  if (!q.data && q.loading) return <Loading rows={rows} />;
  if (!q.data) return null;
  return children(q.data);
}

export function Notice({ tone = "neutral", title, children }) {
  return (
    <div className={`notice notice--${tone}`}>
      {title && <p className="notice__title">{title}</p>}
      {children && <div className="notice__body">{children}</div>}
    </div>
  );
}

// ── Controls ──────────────────────────────────────────────────────────────

export function RefreshButton({ onClick, loading }) {
  return (
    <button type="button" className="btn btn--secondary btn--sm" onClick={onClick} disabled={loading}>
      <Icon name="refresh" size={14} className={loading ? "spin" : undefined} />
      Refresh
    </button>
  );
}

export function CopyButton({ value, label = "Copy" }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="icon-btn"
      title={label}
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(String(value));
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {
          /* clipboard blocked */
        }
      }}
    >
      <Icon name={done ? "check" : "copy"} size={14} />
    </button>
  );
}

export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          className={value === o.value ? "segmented__opt is-active" : "segmented__opt"}
          onClick={() => onChange(o.value)}
        >
          {o.label}
          {o.count !== undefined && <span className="segmented__count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Tabs({ tabs, value, onChange, label }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          aria-selected={value === t.value}
          className={value === t.value ? "tabs__tab is-active" : "tabs__tab"}
          onClick={() => onChange(t.value)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function KeyValue({ items }) {
  return (
    <dl className="kv">
      {items
        .filter(Boolean)
        .map(([k, v]) => (
          <div className="kv__row" key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
    </dl>
  );
}

export function Metric({ label, value, sub }) {
  return (
    <div className="metric">
      <span className="metric__label">{label}</span>
      <span className="metric__value">{value}</span>
      {sub && <span className="metric__sub">{sub}</span>}
    </div>
  );
}

// ── Drawer ────────────────────────────────────────────────────────────────

export function Drawer({ open, onClose, title, subtitle, children, wide = false }) {
  const ref = useRef(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return undefined;
    const prev = document.activeElement;
    ref.current?.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.classList.add("no-scroll");
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("no-scroll");
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="drawer-root">
      <div className="drawer-scrim" onClick={onClose} aria-hidden="true" />
      <aside
        className={wide ? "drawer drawer--wide" : "drawer"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={ref}
      >
        <div className="drawer__head">
          <div>
            <h2 id={titleId} className="drawer__title">
              {title}
            </h2>
            {subtitle && <div className="drawer__sub">{subtitle}</div>}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close panel">
            <Icon name="close" />
          </button>
        </div>
        <div className="drawer__body">{children}</div>
      </aside>
    </div>
  );
}
