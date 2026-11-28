/* Page-local case thread selection, anchor targeting, paging and cancellation. */
import { ref } from "vue";
import {
  readCaseThread,
  type CaseThreadPage,
  type ManagementCaseDetail,
  type ManagementCaseThread,
} from "../api/cases";
import { AbortedError } from "../api/errors";

export function useCaseThread(getAnchor: () => string | undefined) {
  const selectedThread = ref<ManagementCaseThread>();
  const thread = ref<CaseThreadPage>();
  const threadError = ref<unknown>();
  const threadLoading = ref(false);
  let threadRequest: AbortController | undefined;

  function selectThreadFor(next: ManagementCaseDetail): void {
    const threads = next.threads ?? [];
    const messageId = getAnchor()?.match(/^case-message-([1-9][0-9]*)$/)?.[1];
    const messageAccount = messageId
      ? next.actions.find((action) => action.message_id === messageId)?.related_account_id
      : undefined;
    const messageThread = threads.find((item) => item.related_account_id === messageAccount);
    const chosen =
      messageThread ??
      threads.find((item) => item.conversation_id === selectedThread.value?.conversation_id) ??
      threads[0];
    if (chosen) {
      void loadThread(chosen, false, messageThread ? messageId : undefined);
      return;
    }
    selectedThread.value = undefined;
    thread.value = undefined;
  }

  async function loadThread(
    source: ManagementCaseThread,
    older = false,
    messageId?: string,
  ): Promise<void> {
    threadRequest?.abort();
    const controller = new AbortController();
    threadRequest = controller;
    const previous = older ? thread.value : undefined;
    selectedThread.value = source;
    thread.value = previous;
    threadError.value = undefined;
    threadLoading.value = true;
    try {
      let before = previous?.next_before_seq ?? undefined;
      let items = previous?.items ?? [];
      while (!controller.signal.aborted) {
        const next = await readCaseThread(source.conversation_id, before, controller.signal);
        if (controller.signal.aborted) return;
        // Prepend older pages so the merged thread stays chronological.
        items = [...next.items, ...items];
        const cursor = next.next_before_seq ?? undefined;
        // Stop when no anchor was requested or found, or when history cannot advance.
        if (
          !messageId ||
          items.some((item) => item.case_message_id === messageId) ||
          !cursor ||
          cursor <= 1 ||
          next.items.length === 0 ||
          (before && cursor >= before)
        ) {
          thread.value = { ...next, items };
          break;
        }
        before = cursor;
      }
    } catch (caught) {
      if (threadRequest === controller && !(caught instanceof AbortedError))
        threadError.value = caught;
    } finally {
      if (threadRequest === controller) threadLoading.value = false;
    }
  }

  function abortThread(): void {
    threadRequest?.abort();
  }

  return {
    selectedThread,
    thread,
    threadError,
    threadLoading,
    selectThreadFor,
    loadThread,
    abortThread,
  };
}
