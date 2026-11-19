/** Finding rows shared by Overview (compact) and Intelligence (full). */
import { DASH, humanCode, int, isNum, shortId } from "../format.js";
import { href } from "../router.js";
import { SeverityChip, Tag } from "../ui/index.jsx";

export function metricText(m) {
  if (!m) return DASH;
  const v = isNum(m.value) ? (m.value <= 1 && isNum(m.denominator) && m.denominator > 0 ? `${(m.value * 100).toFixed(0)}%` : String(m.value)) : DASH;
  const nd = isNum(m.numerator) && isNum(m.denominator) ? ` (${int(m.numerator)} of ${int(m.denominator)})` : "";
  return `${v}${nd}`;
}

export function SubjectLink({ subject }) {
  if (!subject) return null;
  if (subject.type === "Document") {
    return (
      <a className="link mono" href={href("documents", subject.id)}>
        {subject.id}
      </a>
    );
  }
  return (
    <span className="mono" title={subject.type}>
      {subject.id}
    </span>
  );
}

export function RequestLinks({ ids, max = 6 }) {
  const list = ids ?? [];
  if (!list.length) return <span className="muted">{DASH}</span>;
  return (
    <span className="req-links">
      {list.slice(0, max).map((id) => (
        <a key={id} className="link mono" href={href("decisions", id)} title={id}>
          {shortId(id)}
        </a>
      ))}
      {list.length > max && <span className="muted">+{list.length - max} more</span>}
    </span>
  );
}

export function FindingRow({ finding, compact = false }) {
  const f = finding;
  return (
    <li className="finding">
      <div className="finding__head">
        <SeverityChip severity={f.severity} />
        <span className="finding__title">{f.title}</span>
        <Tag>{humanCode(f.kind)}</Tag>
        {f.attribution === "considered" && (
          <Tag title="The subject was retrieved in the failing decisions but is not directly linked to the failure">considered only</Tag>
        )}
      </div>
      {!compact && <p className="finding__explanation">{f.explanation}</p>}
      <dl className="finding__meta">
        <div>
          <dt>{f.metric?.name ? humanCode(f.metric.name) : "Metric"}</dt>
          <dd className="mono">{metricText(f.metric)}</dd>
        </div>
        {!compact && f.subjects?.length > 0 && (
          <div>
            <dt>Subject</dt>
            <dd className="finding__subjects">
              {f.subjects.map((s) => (
                <SubjectLink key={`${s.type}-${s.id}`} subject={s} />
              ))}
            </dd>
          </div>
        )}
        <div>
          <dt>Decisions</dt>
          <dd>
            <RequestLinks ids={f.request_ids} max={compact ? 3 : 8} />
          </dd>
        </div>
        {!compact && f.query && (
          <div>
            <dt>Query</dt>
            <dd className="mono muted">{f.query}</dd>
          </div>
        )}
      </dl>
    </li>
  );
}
