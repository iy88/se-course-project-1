/*
 * Page-local inquiry replies and appeals.
 *
 * Both entries write to the same case conversation but keep independent drafts,
 * pending and error state. The detail read at submit time is the write target.
 */
import { ref, type Ref } from "vue";
import { postCaseMessage } from "../../api/cases";
import type { CaseDetail } from "../../api/contracts";
import { refreshBadges } from "../../app/badges";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { notify } from "../../app/toast";

export interface CaseThreadRepliesOptions {
  /** Detail payload whose thread is the write target. */
  detail: Ref<CaseDetail | null>;
  /** Capabilities projected for the current viewer. */
  canRespond: Ref<boolean>;
  canAppeal: Ref<boolean>;
  /** Reloads detail, thread and pending inquiries after a successful write. */
  reload: () => Promise<void>;
}

export function useCaseThreadReplies(options: CaseThreadRepliesOptions) {
  const replyingTo = ref<string | null>(null);
  const replyBody = ref("");
  const replyPending = ref(false);
  const replyError = ref<string | null>(null);

  const appealBody = ref("");
  const appealPending = ref(false);
  const appealError = ref<string | null>(null);

  function openInquiryReply(actionId: string): void {
    replyingTo.value = replyingTo.value === actionId ? null : actionId;
    replyBody.value = "";
    replyError.value = null;
  }

  async function submitInquiryReply(): Promise<void> {
    const current = options.detail.value;
    const thread = current?.thread;
    const actionId = replyingTo.value;
    if (!current || !thread || !actionId || !options.canRespond.value || replyPending.value) return;
    if (!replyBody.value.trim()) {
      replyError.value = "请填写说明内容。";
      return;
    }
    const requestCaseId = current.case_id;
    replyError.value = null;
    replyPending.value = true;
    try {
      await postCaseMessage(
        requestCaseId,
        {
          thread,
          message_kind: "statement",
          body: replyBody.value.trim(),
          inquiry_action_id: actionId,
        },
        newIdempotencyKey(),
      );
      replyBody.value = "";
      replyingTo.value = null;
      notify.success("说明已提交。");
      await options.reload();
      void refreshBadges();
    } catch (caught) {
      replyError.value = problemMessage(caught);
    } finally {
      replyPending.value = false;
    }
  }

  async function submitAppeal(): Promise<void> {
    const current = options.detail.value;
    const thread = current?.thread;
    if (!current || !thread || !options.canAppeal.value || appealPending.value) return;
    if (!appealBody.value.trim()) {
      appealError.value = "请填写申辩内容。";
      return;
    }
    const requestCaseId = current.case_id;
    appealError.value = null;
    appealPending.value = true;
    try {
      await postCaseMessage(
        requestCaseId,
        { thread, message_kind: "appeal", body: appealBody.value.trim() },
        newIdempotencyKey(),
      );
      appealBody.value = "";
      notify.success("申辩已提交。");
      await options.reload();
      void refreshBadges();
    } catch (caught) {
      appealError.value = problemMessage(caught);
    } finally {
      appealPending.value = false;
    }
  }

  return {
    replyingTo,
    replyBody,
    replyPending,
    replyError,
    appealBody,
    appealPending,
    appealError,
    openInquiryReply,
    submitInquiryReply,
    submitAppeal,
  };
}
