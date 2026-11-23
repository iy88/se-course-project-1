/*
 * Composer keyboard rules.
 *
 * Enter sends; Shift+Enter inserts a line break; while an IME owns the keyboard the
 * Enter key belongs to the candidate list and must not send. `composing` carries
 * the composition state because some browsers report `isComposing` inconsistently
 * across `keydown` and `compositionend`.
 */
export interface EnterKeyState {
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
}

export function shouldSendOnEnter(event: EnterKeyState, composing: boolean): boolean {
  if (event.key !== "Enter") return false;
  if (event.shiftKey) return false;
  if (composing || event.isComposing) return false;
  return true;
}
