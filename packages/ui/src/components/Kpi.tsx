import type { ReactNode } from "react";

export interface KpiProps {
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  /** good — зелёная дельта, bad — красная. */
  trend?: "good" | "bad";
}

export function Kpi({ label, value, delta, trend }: KpiProps) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {delta !== undefined && <span className={`kpi-delta${trend ? ` ${trend}` : ""}`}>{delta}</span>}
    </div>
  );
}
