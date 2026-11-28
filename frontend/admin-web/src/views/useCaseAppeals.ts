/* Page-local pending-appeal drafts that must survive detail reloads and load failures. */
import { ref } from "vue";
import type { AppealResolution, PendingCaseAppeal } from "../api/cases";

export interface AppealDraft {
  reply: string;
  basis: string[];
  resolution: AppealResolution | "";
  originalId: string;
  replacementAction: string;
  replacementExpected: string;
}

export interface AppealDraftEntry {
  appeal: PendingCaseAppeal;
  draft: AppealDraft;
}

export function useCaseAppeals() {
  const appealDrafts = ref<AppealDraftEntry[]>([]);

  function syncAppeals(appeals?: PendingCaseAppeal[]): void {
    appealDrafts.value = (appeals ?? []).map((appeal) => ({
      appeal,
      draft:
        appealDrafts.value.find((item) => item.appeal.appeal_action_id === appeal.appeal_action_id)
          ?.draft ?? emptyAppealDraft(),
    }));
  }

  function removeAppeal(appealActionId: string): void {
    appealDrafts.value = appealDrafts.value.filter(
      (item) => item.appeal.appeal_action_id !== appealActionId,
    );
  }

  return { appealDrafts, syncAppeals, removeAppeal };
}

function emptyAppealDraft(): AppealDraft {
  return {
    reply: "",
    basis: [],
    resolution: "",
    originalId: "",
    replacementAction: "",
    replacementExpected: "terminated",
  };
}
