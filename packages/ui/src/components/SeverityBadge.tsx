import { SEVERITIES, SEVERITY_LABELS, type Severity } from "../lib/severity";
import { formatNumber } from "../lib/format";

export function SeverityBadge({ level, label }: { level: Severity; label?: string }) {
  return <span className={`sev sev-${level}`}>{label ?? SEVERITY_LABELS[level]}</span>;
}

/** Полоса распределения по уровням (сегменты с зазором 2 px, скругление по краям). */
export function SeverityBar({ counts }: { counts: Partial<Record<Severity, number>> }) {
  const total = SEVERITIES.reduce((s, k) => s + (counts[k] ?? 0), 0);
  if (!total) return <div className="stackbar" aria-hidden="true" />;
  return (
    <div
      className="stackbar"
      role="img"
      aria-label={SEVERITIES.filter((k) => counts[k])
        .map((k) => `${SEVERITY_LABELS[k]}: ${formatNumber(counts[k])}`)
        .join(", ")}
    >
      {SEVERITIES.filter((k) => counts[k]).map((k) => (
        <span
          key={k}
          className={`sev-${k}`}
          style={{ flexGrow: counts[k], flexBasis: 0 }}
          title={`${SEVERITY_LABELS[k]}: ${formatNumber(counts[k])}`}
        />
      ))}
    </div>
  );
}
