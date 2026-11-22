/*
 * Formatting helpers. Money is stored as integer cents everywhere, timestamps
 * are UTC ISO 8601 strings, and all user-visible output is localised to zh-CN.
 */

const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** Render integer cents as a yuan amount with two decimals. */
export function formatCents(cents: number): string {
  if (!Number.isFinite(cents)) return "—";
  return `¥${(cents / 100).toFixed(2)}`;
}

/** Parse a yuan input string into integer cents, or null when unusable. */
export function parseYuanToCents(input: string): number | null {
  const normalised = input.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(normalised)) return null;
  return Math.round(Number.parseFloat(normalised) * 100);
}

export function formatCentsAsYuanInput(cents: number | null | undefined): string {
  if (cents === null || cents === undefined || !Number.isFinite(cents)) return "";
  return (cents / 100).toFixed(2);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return dateTimeFormatter.format(parsed);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return dateFormatter.format(parsed);
}

/** Convert an ISO timestamp into the value format accepted by `datetime-local`. */
export function toLocalInputValue(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  const pad = (segment: number) => String(segment).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(
    parsed.getHours(),
  )}:${pad(parsed.getMinutes())}`;
}

/** Parse a `datetime-local` value into a UTC ISO string. */
export function fromLocalInputValue(value: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}

/** Human readable remaining time for a countdown, e.g. `6 天 4 小时`. */
export function formatRemaining(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "已到期";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days} 天 ${hours} 小时`;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  return `${Math.max(minutes, 1)} 分钟`;
}

/** Relative label used by lists, e.g. `3 天前`. */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  const diffSeconds = Math.round((parsed.getTime() - Date.now()) / 1000);
  const absolute = Math.abs(diffSeconds);
  const suffix = diffSeconds < 0 ? "前" : "后";
  if (absolute < 60) return `刚刚`;
  if (absolute < 3_600) return `${Math.round(absolute / 60)} 分钟${suffix}`;
  if (absolute < 86_400) return `${Math.round(absolute / 3_600)} 小时${suffix}`;
  if (absolute < 30 * 86_400) return `${Math.round(absolute / 86_400)} 天${suffix}`;
  return formatDate(value);
}

/** Shorten long user supplied text for list previews. */
export function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

/** First character of a display name, used by the avatar fallback. */
export function initialOf(displayName: string): string {
  const trimmed = displayName.trim();
  if (!trimmed) return "?";
  const [first] = Array.from(trimmed);
  return first.toUpperCase();
}
