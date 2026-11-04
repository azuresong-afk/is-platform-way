/** Форматирование по правилам интерфейса: даты «04.11.2026 16:54», числа с неразрывным пробелом. */

const dateTime = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDateTime(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  return d ? dateTime.format(d).replace(",", "") : "—";
}

export function formatDate(value: string | number | Date | null | undefined): string {
  const d = toDate(value);
  return d ? dateOnly.format(d) : "—";
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("ru-RU");
}

/** Проценты без дробной части, если она не важна. */
export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: digits })} %`;
}

export function initials(name: string): string {
  const parts = name.replace(/[.]/g, " ").split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}
