/*
 * Project the permitted product-history fields into before/after rows.
 *
 * The edit snapshot keeps arbitrary content, while a trade participant may only
 * see the fields the history projection provides. Only the known public fields
 * are rendered; a missing or unchanged value is omitted instead of guessed.
 */
import { formatCents } from "./format";

export interface ProductEditChange {
  key: string;
  label: string;
  before: string;
  after: string;
}

interface FieldRule {
  key: string;
  label: string;
  format: (value: unknown) => string;
}

function textValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function moneyValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? formatCents(value)
    : textValue(value);
}

const fields: FieldRule[] = [
  { key: "title", label: "标题", format: textValue },
  { key: "description", label: "描述", format: textValue },
  { key: "price_cents", label: "价格", format: moneyValue },
];

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

export function productEditChanges(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): ProductEditChange[] {
  return fields
    .filter((field) => field.key in before || field.key in after)
    .filter((field) => !sameValue(before[field.key], after[field.key]))
    .map((field) => ({
      key: field.key,
      label: field.label,
      before: field.format(before[field.key]),
      after: field.format(after[field.key]),
    }));
}
