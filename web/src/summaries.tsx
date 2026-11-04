/**
 * Тело карточки продукта на Главной (контракт v1.1, п. 10 и 10.1).
 *
 * Любой продукт получает карточку по общему формату `data.kpis[]` — без доработки оболочки.
 * Особое оформление для известных продуктов (SUMMARY_RENDERERS) — необязательное улучшение:
 * без записи в этом реестре карточка всё равно работает (roadmap §1а).
 */
import {
  formatDateTime,
  formatNumber,
  formatPercent,
  SEVERITIES,
  SEVERITY_LABELS,
  SeverityBadge,
  SeverityBar,
  type Severity,
} from "@platform/ui";
import type { ReactNode } from "react";

import { RUN_STATUS } from "./labels";

type SummaryData = Record<string, unknown>;

/** Ссылка только на свой origin: продукт не должен уводить пользователя наружу. */
export function safeLink(link: unknown, fallback: string): string {
  return typeof link === "string" && link.startsWith("/") && !link.startsWith("//") ? link : fallback;
}

const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" ? (v as Record<string, unknown>) : null);
const isSeverity = (v: unknown): v is Severity => typeof v === "string" && (SEVERITIES as readonly string[]).includes(v);

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/** Не больше 6 показателей (контракт v1.1, п. 10.1). */
export const MAX_KPIS = 6;

type Kpi = { label: string; value: number | string; severity?: Severity; link?: string };

/** Отбирает показатели по контракту; некорректные элементы пропускает. */
export function parseKpis(raw: unknown): Kpi[] | null {
  if (!Array.isArray(raw)) return null;
  const out: Kpi[] = [];
  for (const item of raw) {
    const k = obj(item);
    if (!k || typeof k.label !== "string") continue;
    const value = k.value;
    if (!(typeof value === "string" || (typeof value === "number" && Number.isFinite(value)))) continue;
    out.push({
      label: k.label,
      value,
      severity: isSeverity(k.severity) ? k.severity : undefined,
      link: typeof k.link === "string" ? safeLink(k.link, "") || undefined : undefined,
    });
    if (out.length === MAX_KPIS) break;
  }
  return out;
}

/** Общая карточка: показатели `kpis` и строка `note`. */
export function KpiSummary({ data }: { data: SummaryData }) {
  const kpis = parseKpis(data.kpis) ?? [];
  const note = typeof data.note === "string" ? data.note : "";
  if (!kpis.length && !note) return <p className="muted">Продукт не передал показателей.</p>;
  return (
    <>
      {kpis.length > 0 && (
        <dl className="stat-list">
          {kpis.map((k, i) => {
            const text = typeof k.value === "number" ? formatNumber(k.value) : k.value;
            const shown = k.severity ? <SeverityBadge level={k.severity} label={text} /> : text;
            return <Stat key={`${i}:${k.label}`} label={k.label} value={k.link ? <a href={k.link}>{shown}</a> : shown} />;
          })}
        </dl>
      )}
      {note && <p className="muted">{note}</p>}
    </>
  );
}

/** Запасной вариант для сводки без `kpis`: числовые поля как есть. */
function RawSummary({ data }: { data: SummaryData }) {
  const fields = Object.entries(data).filter(([, v]) => typeof v === "number");
  if (!fields.length) return <p className="muted">Продукт не передал показателей.</p>;
  return (
    <dl className="stat-list">
      {fields.map(([k, v]) => (
        <Stat key={k} label={k} value={formatNumber(v as number)} />
      ))}
    </dl>
  );
}

// --- Особое оформление известных продуктов (необязательно) ---

function ScannerSummary({ data }: { data: SummaryData }) {
  const open = obj(data.open) ?? {};
  const counts = Object.fromEntries(SEVERITIES.map((s) => [s, num(open[s])])) as Record<Severity, number>;
  const total = SEVERITIES.reduce((s, k) => s + counts[k], 0);
  const run = obj(data.last_run);
  const st = run ? RUN_STATUS[String(run.status)] : undefined;
  return (
    <div className="hero">
      <div>
        <div className="kpi-label">Открытые уязвимости</div>
        <div className="kpi-value">{formatNumber(total)}</div>
      </div>
      <SeverityBar counts={counts} />
      <div className="legend">
        {SEVERITIES.filter((s) => s !== "info").map((s) => (
          <span key={s} style={{ display: "inline-flex", gap: 6 }}>
            <SeverityBadge level={s} label={SEVERITY_LABELS[s]} /> <span className="muted">{formatNumber(counts[s])}</span>
          </span>
        ))}
      </div>
      <dl className="stat-list">
        <Stat
          label="Последний прогон"
          value={run ? <span className={`pill ${st?.pill ?? "pill-muted"}`}>{st?.label ?? String(run.status)}</span> : "—"}
        />
        {run && <Stat label="Завершён" value={formatDateTime(run.finished_at as string)} />}
      </dl>
    </div>
  );
}

function VmSummary({ data }: { data: SummaryData }) {
  const win = obj(data.next_window);
  return (
    <dl className="stat-list">
      <Stat label="Открытые заявки" value={formatNumber(num(data.open_tickets))} />
      <Stat label="Просрочено" value={formatNumber(num(data.overdue_tickets))} />
      <Stat label="Подтверждено за неделю" value={formatNumber(num(data.verified_week))} />
      <Stat label="Ближайшее окно" value={win ? formatDateTime(win.starts_at as string) : "—"} />
    </dl>
  );
}

function GrcSummary({ data }: { data: SummaryData }) {
  const docs = obj(data.documents) ?? {};
  return (
    <dl className="stat-list">
      <Stat label="Объекты" value={formatNumber(num(data.systems))} />
      <Stat label="Реализация мер" value={formatPercent(num(data.measures_percent))} />
      <Stat label="Документы готовы" value={`${formatNumber(num(docs.ready))} из ${formatNumber(num(docs.total))}`} />
    </dl>
  );
}

/** Особое оформление по id продукта. Новому продукту запись не нужна. */
export const SUMMARY_RENDERERS: Record<string, (props: { data: SummaryData }) => ReactNode> = {
  scanner: ScannerSummary,
  vm: VmSummary,
  grc: GrcSummary,
};

export function SummaryBody({ productId, data }: { productId: string; data: SummaryData }) {
  const Custom = Object.hasOwn(SUMMARY_RENDERERS, productId) ? SUMMARY_RENDERERS[productId] : undefined;
  if (Custom) return <Custom data={data} />;
  if (Array.isArray(data.kpis)) return <KpiSummary data={data} />;
  return <RawSummary data={data} />;
}
