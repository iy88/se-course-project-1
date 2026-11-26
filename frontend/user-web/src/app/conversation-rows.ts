/*
 * Row model for one conversation branch.
 *
 * The thread is rendered from a flat message page: day separators are inserted,
 * consecutive messages from the same sender within the same minute are merged so
 * the header is not repeated, and system events are centred instead of aligned to
 * either side. Keeping this pure makes the display rules testable without a DOM.
 */
import type { ConversationMessage } from "../api/contracts";
import { formatDateTime } from "./format";

export interface DateRow {
  kind: "date";
  key: string;
  label: string;
}

export interface MessageRow {
  kind: "message";
  key: string;
  message: ConversationMessage;
  mine: boolean;
  system: boolean;
  merged: boolean;
}

export type ConversationRow = DateRow | MessageRow;

export interface RowOptions {
  /** Account viewing the thread; null when the session is not resolved yet. */
  viewerAccountId: string | null;
  /** Injected so "today" and "yesterday" are testable. */
  now?: Date;
}

function sameCalendarDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

/** Day separator text: 今天 / 昨天 / the date. */
export function dayLabel(value: string, now: Date = new Date()): string {
  const target = new Date(value);
  if (sameCalendarDay(target, now)) return "今天";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameCalendarDay(target, yesterday)) return "昨天";
  return formatDateTime(value).split(" ")[0] ?? value;
}

function dayKey(value: string): string {
  return value.slice(0, 10);
}

/** Same minute, used to merge consecutive messages from one sender. */
function minuteKey(value: string): string {
  return value.slice(0, 16);
}

export function buildConversationRows(
  messages: ConversationMessage[],
  options: RowOptions,
): ConversationRow[] {
  const rows: ConversationRow[] = [];
  let currentDay = "";
  let previous: ConversationMessage | null = null;

  for (const message of messages) {
    const day = dayKey(message.created_at);
    if (day !== currentDay) {
      currentDay = day;
      previous = null;
      rows.push({
        kind: "date",
        key: `date:${day}`,
        label: dayLabel(message.created_at, options.now ?? new Date()),
      });
    }

    const system = message.sender.sender_kind === "system";
    const mine =
      !system &&
      options.viewerAccountId !== null &&
      message.sender.account_id === options.viewerAccountId;
    const merged =
      !system &&
      previous !== null &&
      previous.sender.sender_kind === message.sender.sender_kind &&
      previous.sender.account_id === message.sender.account_id &&
      minuteKey(previous.created_at) === minuteKey(message.created_at);

    rows.push({ kind: "message", key: message.message_id, message, mine, system, merged });
    previous = message;
  }

  return rows;
}
