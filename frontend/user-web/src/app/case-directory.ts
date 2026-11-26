/*
 * Viewpoint memory for case screens.
 *
 * `GET /cases` returns the scope each case was listed under (`mine` when the
 * current account is the reporter, `received` when it is the punished side). The
 * detail endpoint deliberately does not state the viewpoint, and
 * `appeal_deadline_at` only exists for the punished side, so it cannot stand in
 * for "is this the reporter". The list therefore feeds this directory and the
 * detail reads it.
 *
 * A case can legitimately appear in both scopes — for example when the account
 * reported the case and was also punished in it — so both are remembered. When
 * nothing was remembered (a deep link straight to the detail screen) the privileged
 * entries stay hidden instead of guessing.
 */
import { ref } from "vue";
import type { CaseScope } from "../api/contracts";

const scopes = ref<Map<string, Set<CaseScope>>>(new Map());

export function rememberCaseScope(caseId: string, scope: CaseScope): void {
  const current = scopes.value.get(caseId);
  if (current?.has(scope)) return;
  const next = new Map(scopes.value);
  const entry = new Set(current ?? []);
  entry.add(scope);
  next.set(caseId, entry);
  scopes.value = next;
}

export function caseHasScope(caseId: string, scope: CaseScope): boolean {
  return scopes.value.get(caseId)?.has(scope) ?? false;
}

/** Forget every remembered viewpoint; called when the session ends. */
export function clearCaseScopes(): void {
  scopes.value = new Map();
}
