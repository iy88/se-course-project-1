/*
 * Server-projected case actions (API-CASE-010 projection).
 *
 * The detail endpoint may return `available_actions` for the current viewer. When
 * the field is an array the server is authoritative: the client shows exactly the
 * entries it allows, and an empty array hides every write entry. When the field is
 * missing the backend does not project the capability yet, so the client keeps its
 * own rules (list scope for the reporter entry, the appeal deadline for the appeal
 * entry, pending inquiry ids for replies).
 */
import type { CaseKind } from "../api/contracts";

export const CASE_SUPPLEMENT = "supplement_evidence";
export const CASE_RESPOND = "respond_inquiry";
export const CASE_APPEAL = "submit_appeal";

export interface CaseActionInput {
  /** `available_actions` as returned by the server, or null/undefined when absent. */
  projected: readonly string[] | null | undefined;
  archived: boolean;
  reporterView: boolean;
  caseType: CaseKind | null;
  appealOpen: boolean;
  pendingInquiryCount: number;
}

export interface CaseActionAvailability {
  /** Whether the entry is shown at all. */
  supplement: boolean;
  respond: boolean;
  appeal: boolean;
  /** True when the server projected the capability, so the view can say so. */
  projected: boolean;
}

function allowedSet(projected: readonly string[]): Set<string> {
  return new Set(projected.map((action) => action.trim().toLowerCase()).filter(Boolean));
}

export function caseActionAvailability(input: CaseActionInput): CaseActionAvailability {
  const projected = Array.isArray(input.projected);
  if (input.archived) {
    return { supplement: false, respond: false, appeal: false, projected };
  }
  if (projected) {
    const allowed = allowedSet(input.projected as readonly string[]);
    return {
      supplement: allowed.has(CASE_SUPPLEMENT),
      // A reply still needs an inquiry to answer, even when the server allows the action.
      respond: allowed.has(CASE_RESPOND) && input.pendingInquiryCount > 0,
      appeal: allowed.has(CASE_APPEAL) && input.appealOpen,
      projected: true,
    };
  }
  return {
    supplement: input.reporterView && input.caseType === "report",
    respond: input.pendingInquiryCount > 0,
    appeal: input.appealOpen,
    projected: false,
  };
}
