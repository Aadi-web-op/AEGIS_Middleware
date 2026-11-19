/** Decision distribution: one stacked bar plus a legend table of real counts. */
import { DECISIONS, DECISION_META, int, ratio } from "../format.js";

export default function DistributionBar({ counts }) {
  const total = DECISIONS.reduce((s, d) => s + (counts?.[d] ?? 0), 0);
  if (!total) return <p className="muted">No decisions recorded yet.</p>;
  return (
    <div className="dist">
      <div className="dist__bar" role="img" aria-label={DECISIONS.map((d) => `${d} ${counts?.[d] ?? 0}`).join(", ")}>
        {DECISIONS.map((d) => {
          const n = counts?.[d] ?? 0;
          if (!n) return null;
          return <span key={d} className={`dist__seg dist__seg--${DECISION_META[d].cls}`} style={{ flexGrow: n }} title={`${d}: ${n}`} />;
        })}
      </div>
      <table className="dist__table">
        <tbody>
          {DECISIONS.map((d) => (
            <tr key={d}>
              <td>
                <span className={`dist__key dist__seg--${DECISION_META[d].cls}`} aria-hidden="true" />
                {DECISION_META[d].label}
              </td>
              <td className="num">{int(counts?.[d] ?? 0)}</td>
              <td className="num muted">{ratio(counts?.[d] ?? 0, total, 1)}</td>
            </tr>
          ))}
          <tr className="dist__total">
            <td>Total</td>
            <td className="num">{int(total)}</td>
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  );
}
