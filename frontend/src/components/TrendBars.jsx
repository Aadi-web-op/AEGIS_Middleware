/** Stacked bars of decision counts per time bucket (from /v1/intelligence/trends). */
import { DECISIONS, DECISION_META, int } from "../format.js";

const H = 140;
const AXIS = 22;
const LEFT = 30;

function niceMax(v) {
  if (v <= 5) return 5;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function bucketLabel(b, bucket) {
  if (!b) return "";
  if (bucket === "hour") return `${b.slice(5, 10)} ${b.slice(11, 13)}h`;
  return b.slice(5, 10);
}

export default function TrendBars({ items, bucket }) {
  const max = niceMax(Math.max(...items.map((i) => i.total ?? 0), 1));
  const n = items.length;
  const W = Math.max(560, LEFT + n * 28);
  const slot = (W - LEFT) / n;
  const bw = Math.min(28, slot * 0.7);
  const labelEvery = Math.ceil(n / 10);
  const y = (v) => H - (v / max) * H;

  return (
    <div className="trend">
      <svg viewBox={`0 0 ${W} ${H + AXIS}`} role="img" aria-label={`Decisions per ${bucket}, ${n} buckets`}>
        {[0, max / 2, max].map((t) => (
          <g key={t}>
            <line className="trend__grid" x1={LEFT} x2={W} y1={y(t)} y2={y(t)} />
            <text className="trend__axis" x={LEFT - 6} y={y(t) + 3} textAnchor="end">
              {int(t)}
            </text>
          </g>
        ))}
        {items.map((it, i) => {
          const x = LEFT + i * slot + (slot - bw) / 2;
          let acc = 0;
          return (
            <g key={it.bucket}>
              <title>{`${it.bucket}: ${DECISIONS.map((d) => `${DECISION_META[d].label} ${it[d] ?? 0}`).join(", ")} (total ${it.total})`}</title>
              {DECISIONS.map((d) => {
                const v = it[d] ?? 0;
                if (!v) return null;
                const y1 = y(acc + v);
                const h = y(acc) - y1;
                acc += v;
                return <rect key={d} className={`trend__seg--${DECISION_META[d].cls}`} x={x} y={y1} width={bw} height={Math.max(h - 1, 1)} />;
              })}
              {i % labelEvery === 0 && (
                <text className="trend__axis" x={x + bw / 2} y={H + 15} textAnchor="middle">
                  {bucketLabel(it.bucket, bucket)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="legend-inline">
        {DECISIONS.map((d) => (
          <span key={d}>
            <span className={`dist__key dist__seg--${DECISION_META[d].cls}`} aria-hidden="true" />
            {DECISION_META[d].label}
          </span>
        ))}
      </div>
    </div>
  );
}
