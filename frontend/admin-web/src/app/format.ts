/* Formatting helpers for the administration interface. */

const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Render integer cents as a yuan amount with two decimals. */
export function formatCents(cents: number): string {
  if (!Number.isFinite(cents)) return "—";
  return `¥${(cents / 100).toFixed(2)}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return dateTimeFormatter.format(parsed);
}
