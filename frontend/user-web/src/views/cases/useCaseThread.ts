/* Page-local case thread loading, cancellation and deep-link anchor reading. */
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { listMessages } from "../../api/conversations";
import type { CaseMessage, CaseMessageKind, CaseThread } from "../../api/contracts";

const THREAD_PAGE_SIZE = 100;

export function useCaseThread(getThread: () => CaseThread | null | undefined) {
  const route = useRoute();
  const threadMessages = ref<CaseMessage[]>([]);
  const threadStatus = ref<"idle" | "loading" | "ready" | "failed">("idle");
  const threadError = ref<unknown>(null);
  const anchorMessageId = computed(() => /^#case-message-([1-9][0-9]*)$/.exec(route.hash)?.[1]);
  let threadRequest: AbortController | undefined;

  async function loadThread(): Promise<void> {
    threadRequest?.abort();
    const thread = getThread();
    if (!thread) {
      threadStatus.value = "ready";
      threadMessages.value = [];
      return;
    }
    const request = new AbortController();
    threadRequest = request;
    const anchor = anchorMessageId.value;
    threadStatus.value = "loading";
    threadError.value = null;
    try {
      const page = await listMessages(
        thread.conversation_kind,
        thread.conversation_id,
        { limit: THREAD_PAGE_SIZE },
        request.signal,
      );
      const pages = [page.items];
      let before = page.next_before_seq ?? null;
      let found = page.items.some((message) => message.message_id === anchor);
      while (anchor && !found && before !== null && before > 1) {
        const older = await listMessages(
          thread.conversation_kind,
          thread.conversation_id,
          { limit: THREAD_PAGE_SIZE, before_seq: before },
          request.signal,
        );
        pages.push(older.items);
        found = older.items.some((message) => message.message_id === anchor);
        before =
          older.next_before_seq != null && older.next_before_seq < before
            ? older.next_before_seq
            : null;
      }
      if (request.signal.aborted) return;
      threadMessages.value = pages
        .reverse()
        .flat()
        .map((message) => ({
          case_message_id: message.message_id,
          seq: message.seq,
          message_kind: (message.message_type as CaseMessageKind) ?? "statement",
          body: message.body,
          sender: message.sender,
          created_at: message.created_at,
        }));
      threadStatus.value = "ready";
    } catch (caught) {
      if (request.signal.aborted) return;
      threadError.value = caught;
      threadStatus.value = "failed";
    }
  }

  function cancelThread(): void {
    threadRequest?.abort();
  }

  return {
    threadMessages,
    threadStatus,
    threadError,
    anchorMessageId,
    loadThread,
    cancelThread,
  };
}
