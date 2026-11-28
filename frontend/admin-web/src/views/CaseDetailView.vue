<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, useId, watch } from "vue";
import {
  caseEvidenceFileHref,
  liftCaseEnforcement,
  readCase,
  readCaseThread,
  resolveCaseAppeal,
  writeCase,
  type AppealableEnforcement,
  type AppealResolution,
  type CaseDecision,
  type CaseEnforcementInput,
  type CaseMessageEvidence,
  type CaseRelatedAccount,
  type CaseManagementWrites,
  type CaseReplacementEnforcement,
  type CaseThreadPage,
  type ManagementCaseDetail,
  type ManagementCaseThread,
  type PendingCaseAppeal,
} from "../api/cases";
import { AbortedError } from "../api/errors";
import { dispositionTargets, resolveDispositionTarget } from "../app/disposition-targets";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { decisionKindLabels, todoKindLabels } from "../app/labels";
import { problemMessage } from "../app/problems";
import { useToastStore } from "../app/toast";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";
import CaseEvidenceSection from "./CaseEvidenceSection.vue";
import { useCaseTradeHistory } from "./useCaseTradeHistory";

const props = defineProps<{ caseId: string; backHref: string; anchor?: string }>();
const { notify } = useToastStore();
const ids = useId();
const detail = ref<ManagementCaseDetail>();
const error = ref<unknown>();
const loading = ref(false);
const writing = ref(false);
const writeError = ref("");
const keys = new IdempotencyKeys();
// Keep evidence state when the detail error replaces the section.
const evidenceState = reactive({
  messageEvidence: undefined as CaseMessageEvidence | undefined,
  evidenceLoading: false,
  evidenceError: "",
});
let detailRequest: AbortController | undefined;

const {
  tradeHistory,
  tradeHistoryLoading,
  tradeHistoryError,
  loadTradeHistory,
  abortTradeHistory,
} = useCaseTradeHistory(() => props.caseId);
const tradeHistoryAvailable = computed(() => {
  const item = detail.value;
  return item && (item.case_type !== "report" || item.reported_object?.target_type === "trade");
});
const agreementStatus = {
  proposed: "待回应",
  effective: "已生效",
  rejected: "已拒绝",
  withdrawn: "已撤回",
  superseded: "已被替代",
};

const selectedThread = ref<ManagementCaseThread>();
const thread = ref<CaseThreadPage>();
const threadError = ref<unknown>();
const threadLoading = ref(false);
let threadRequest: AbortController | undefined;

const peer = ref("");
const inquiry = ref("");
const decisionKind = ref<CaseDecision>("no_action");
const decisionReason = ref("");
const basis = ref<string[]>([]);
const publicSummary = ref("");
const publicReason = ref("");
const confirmClose = ref(false);
interface AppealDraft {
  reply: string;
  basis: string[];
  resolution: AppealResolution | "";
  originalId: string;
  replacementAction: string;
  replacementExpected: string;
}
const appealDrafts = ref<{ appeal: PendingCaseAppeal; draft: AppealDraft }[]>([]);
const liftDraft = ref<{ enforcementId: string; reason: string }>();
const enforcementOptions = [
  { action: "restrict_account", target: "account", label: "封禁账户" },
  { action: "withdraw_public_access", target: "product", label: "撤销商品展示" },
  { action: "remove_content", target: "comment", label: "移除评论" },
  { action: "remove_content", target: "evaluation", label: "移除评价" },
  { action: "freeze_trade", target: "trade", label: "冻结交易" },
  { action: "adjust_trade_status", target: "trade", label: "调整交易状态" },
] as const;
const instructions = ref<{ id: number; option: number; targetId: string; expected: string }[]>([]);
let instructionId = 0;

const messages: Record<string, string> = {
  submit: "提交事项",
  claim: "认领",
  inquire: "发起问询",
  inquiry: "问询",
  statement: "说明",
  supplement: "补充材料",
  decide: "作出决定",
  execute: "执行处置",
  appeal: "申辩",
  manager_reply: "管理员回复",
  close: "结案",
  publish_result: "公开结果",
  lift: "解除处置",
};
const statusLabels = { pending: "待认领", claimed: "处理中", decided: "已决定" };
const currentStatus = computed(() =>
  detail.value?.archived_at ? "已结案" : detail.value && statusLabels[detail.value.case_status],
);
const caseTypeLabel = computed(() =>
  detail.value ? todoKindLabels[detail.value.case_type] : "事项",
);
const pageDescription = computed(() =>
  detail.value
    ? `${caseTypeLabel.value}处理 · ${currentStatus.value} · ${relatedAccounts.value.length} 个相关账户`
    : "读取事项摘要、材料、会话与处置操作。",
);
const reportedObject = computed(() => detail.value?.reported_object);
const basisEvidence = computed(
  () => detail.value?.evidence?.filter((item) => item.decision_basis) ?? [],
);
const submittedNotes = computed(
  () =>
    detail.value?.decision_basis_actions?.filter((item) => item.action_kind === "supplement") ?? [],
);
const relatedAccounts = computed(() => detail.value?.related_accounts ?? []);
const eligibleAccounts = computed(() =>
  relatedAccounts.value.filter((account) => account.eligible),
);
const selectedThreadTitle = computed(() =>
  selectedThread.value ? accountDisplayName(selectedThread.value.related_account_id) : "事项会话",
);
const reportedKinds = {
  account: "账户",
  product: "商品",
  comment: "评论",
  evaluation: "评价",
  message: "消息",
  trade: "交易",
};

function accountLabel(account: CaseRelatedAccount): string {
  const target = reportedObject.value;
  let role = account.reporter ? "举报人" : "相关账户";
  if (target?.target_type === "account" && target.target_id === account.account_id) {
    role = target.product ? "被举报卖方" : "被举报账户";
  } else if (detail.value?.target?.author_account_id === account.account_id) {
    role = "被举报内容作者";
  } else if (!account.reporter && target?.target_type === "product" && account.eligible) {
    role = "商品卖方";
  }
  return `${role} · ${account.display_name ?? "账户"} #${account.account_id}`;
}

const dispositionChoices = computed(() =>
  enforcementOptions.map(({ target }) => dispositionTargets(detail.value, target, accountLabel)),
);

function accountDisplayName(accountId: string): string {
  const account = relatedAccounts.value.find((item) => item.account_id === accountId);
  return account?.display_name ?? `账户 #${accountId}`;
}

function accountInitial(accountId: string): string {
  return accountDisplayName(accountId).trim().slice(0, 1).toUpperCase() || "#";
}

function threadTabLabel(accountId: string): string {
  const account = relatedAccounts.value.find((item) => item.account_id === accountId);
  return account ? accountLabel(account) : `相关账户 #${accountId}`;
}

function messageSide(senderKind: string | null): "manager" | "account" | "system" {
  if (senderKind === "manager") return "manager";
  if (senderKind === "system") return "system";
  return "account";
}

function userProductHref(productId: string): string {
  const path = `/products/${encodeURIComponent(productId)}`;
  if (typeof window === "undefined") return path;
  const target = new URL(window.location.href);
  if (target.port === "3001") {
    target.port = "3000";
  } else if (target.hostname.startsWith("admin.")) {
    target.hostname = `mobile.${target.hostname.slice("admin.".length)}`;
  }
  target.pathname = path;
  target.search = "";
  target.hash = "";
  return target.toString();
}

const actions = computed(() => new Set(detail.value?.available_actions ?? []));

function selectThreadFor(next: ManagementCaseDetail): void {
  const threads = next.threads ?? [];
  const messageId = props.anchor?.match(/^case-message-([1-9][0-9]*)$/)?.[1];
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

function selectDefaultPeer(next: ManagementCaseDetail): void {
  const candidates = (next.related_accounts ?? []).filter((account) => account.eligible);
  if (candidates.some((account) => account.account_id === peer.value)) return;
  peer.value = candidates[0]?.account_id ?? "";
}

async function load(): Promise<void> {
  detailRequest?.abort();
  const controller = new AbortController();
  detailRequest = controller;
  loading.value = true;
  error.value = undefined;
  try {
    const next = await readCase(props.caseId, controller.signal);
    if (detailRequest === controller) {
      detail.value = next;
      appealDrafts.value = (next.pending_appeals ?? []).map((appeal) => ({
        appeal,
        draft: appealDrafts.value.find(
          (item) => item.appeal.appeal_action_id === appeal.appeal_action_id,
        )?.draft ?? {
          reply: "",
          basis: [],
          resolution: "",
          originalId: "",
          replacementAction: "",
          replacementExpected: "terminated",
        },
      }));
      selectDefaultPeer(next);
      selectThreadFor(next);
    }
  } catch (caught) {
    if (detailRequest === controller && !(caught instanceof AbortedError)) {
      detail.value = undefined;
      error.value = caught;
    }
  } finally {
    if (detailRequest === controller) loading.value = false;
  }
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
      items = [...next.items, ...items];
      const cursor = next.next_before_seq ?? undefined;
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

async function submit<T extends keyof CaseManagementWrites>(
  operation: T,
  body: CaseManagementWrites[T],
): Promise<void> {
  if (writing.value) return;
  writing.value = true;
  writeError.value = "";
  const key = JSON.stringify([operation, body]);
  try {
    await writeCase(props.caseId, operation, body, keys.current(key));
    keys.rotate(key);
    notify.success("操作已完成。");
    if (operation === "inquiries") {
      inquiry.value = "";
      if (selectedThread.value) await loadThread(selectedThread.value);
    }
    confirmClose.value = false;
    await load();
  } catch (caught) {
    writeError.value = problemMessage(caught);
  } finally {
    writing.value = false;
  }
}

function selectedAppealEnforcement(
  appeal: PendingCaseAppeal,
  draft: AppealDraft,
): AppealableEnforcement | undefined {
  return appeal.original_enforcements?.find((item) => item.enforcement_id === draft.originalId);
}

function appealEnforcementLabel(item: AppealableEnforcement): string {
  return (
    enforcementOptions.find(
      (option) => option.action === item.action && option.target === item.target_type,
    )?.label ?? item.action
  );
}

function appealReplacementOptions(appeal: PendingCaseAppeal, draft: AppealDraft) {
  const original = selectedAppealEnforcement(appeal, draft);
  if (!original) return [];
  const liftActions = new Set(["lift_account_restriction", "restore_display", "lift_trade_freeze"]);
  return enforcementOptions.filter(
    (option) =>
      option.target === original.target_type &&
      option.action !== original.action &&
      !liftActions.has(option.action),
  );
}

function appealReplacement(
  appeal: PendingCaseAppeal,
  draft: AppealDraft,
): CaseReplacementEnforcement[] {
  const original = selectedAppealEnforcement(appeal, draft);
  const option = enforcementOptions.find(
    (candidate) =>
      candidate.action === draft.replacementAction && candidate.target === original?.target_type,
  );
  if (!original || !option) return [];
  return [
    {
      action: option.action,
      target_type: original.target_type,
      target_id: original.target_id,
      expected_result:
        option.action === "adjust_trade_status" ? draft.replacementExpected : undefined,
    },
  ];
}

async function resolveAppeal(appeal: PendingCaseAppeal, draft: AppealDraft): Promise<void> {
  if (writing.value) return;
  const resolution = draft.resolution;
  if (!resolution) {
    writeError.value = "请选择处理结果。";
    return;
  }
  if (resolution !== "uphold" && !draft.originalId) {
    writeError.value = "请选择要撤销或调整的原处置。";
    return;
  }
  const replacements = resolution === "adjust" ? appealReplacement(appeal, draft) : [];
  if (resolution === "adjust" && replacements.length === 0) {
    writeError.value = "请选择替代处置。";
    return;
  }
  const reply = draft.reply.trim();
  const basisRefs = draft.basis;
  if (!basisRefs.length) {
    writeError.value = "请选择依据引用。";
    return;
  }
  const key = JSON.stringify([
    "resolve-appeal",
    appeal.appeal_action_id,
    resolution,
    resolution === "uphold" ? null : draft.originalId,
    replacements,
    reply,
    basisRefs,
  ]);
  writing.value = true;
  writeError.value = "";
  try {
    await resolveCaseAppeal(
      props.caseId,
      appeal,
      resolution,
      draft.originalId || null,
      replacements,
      reply,
      basisRefs,
      keys.current(key),
    );
    keys.rotate(key);
    appealDrafts.value = appealDrafts.value.filter(
      (item) => item.appeal.appeal_action_id !== appeal.appeal_action_id,
    );
    notify.success("已处理申辩。");
    if (selectedThread.value?.conversation_id === appeal.thread.conversation_id) {
      await loadThread(selectedThread.value);
    }
    await load();
  } catch (caught) {
    writeError.value = problemMessage(caught);
  } finally {
    writing.value = false;
  }
}

function openLift(enforcementId: string): void {
  if (writing.value) return;
  writeError.value = "";
  liftDraft.value = { enforcementId, reason: "" };
}

function cancelLift(): void {
  liftDraft.value = undefined;
  writeError.value = "";
}

function submitLift(): void {
  const draft = liftDraft.value;
  if (!draft || writing.value) return;
  const reason = draft.reason.trim();
  if (!reason) {
    writeError.value = "请填写解除原因。";
    return;
  }
  void lift(draft.enforcementId, reason);
}

async function lift(enforcementId: string, reason: string): Promise<void> {
  writing.value = true;
  writeError.value = "";
  const key = JSON.stringify(["lift", enforcementId, reason]);
  try {
    await liftCaseEnforcement(props.caseId, enforcementId, reason, keys.current(key));
    keys.rotate(key);
    liftDraft.value = undefined;
    notify.success("已解除处置。");
    await load();
  } catch (caught) {
    writeError.value = problemMessage(caught);
  } finally {
    writing.value = false;
  }
}

function submitDecision(): void {
  const enforcements: CaseEnforcementInput[] = [];
  if (decisionKind.value === "violation") {
    for (const entry of instructions.value) {
      const option = enforcementOptions[entry.option];
      const choices = dispositionChoices.value[entry.option];
      const target = resolveDispositionTarget(choices, entry.targetId);
      if (!target) {
        writeError.value = "请选择有效的处置对象。";
        return;
      }
      enforcements.push({
        action: option.action,
        target_type: option.target,
        target_id: target.id,
        expected_result: option.action === "adjust_trade_status" ? entry.expected : undefined,
      });
    }
  }
  void submit("decisions", {
    decision_kind: decisionKind.value,
    reason: decisionReason.value.trim(),
    basis_refs: basis.value,
    enforcements,
  });
}

function addInstruction(): void {
  const option = dispositionChoices.value.findIndex((choices) => choices.length);
  if (option >= 0) {
    instructions.value.push({ id: ++instructionId, option, targetId: "", expected: "terminated" });
  }
}

watch(
  [detail, loading, threadLoading, () => props.anchor],
  ([data, busy, loadingMessages, anchor]) => {
    if (loadingMessages && anchor?.startsWith("case-message-")) return;
    if (data && !busy && anchor)
      document.getElementById(anchor)?.scrollIntoView({ block: "center" });
  },
  { flush: "post" },
);
watch(
  () => props.anchor,
  (anchor) => {
    if (anchor?.startsWith("case-message-") && detail.value) selectThreadFor(detail.value);
  },
);
onMounted(load);
onUnmounted(() => {
  detailRequest?.abort();
  threadRequest?.abort();
  abortTradeHistory();
});
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader eyebrow="治理事项" :title="`事项 #${caseId}`" :description="pageDescription">
      <template #actions>
        <a :href="backHref" data-admin-route class="btn btn--ghost">返回事项工作台</a>
      </template>
    </PageHeader>
    <LoadingBlock v-if="loading && !detail" label="正在读取事项…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="load" />
    <template v-else-if="detail">
      <section class="card case-overview">
        <header class="case-overview__header">
          <div>
            <p class="section-kicker">事项概览</p>
            <h2>{{ todoKindLabels[detail.case_type] }}</h2>
          </div>
          <span
            class="case-status"
            :class="[
              `case-status--${detail.case_status}`,
              { 'case-status--archived': detail.archived_at },
            ]"
          >
            {{ currentStatus }}
          </span>
        </header>

        <div class="case-overview__layout">
          <div class="stack stack--tight">
            <section v-if="detail.reported_reason" class="info-block">
              <h3>举报理由</h3>
              <p class="body-copy pre-line">{{ detail.reported_reason }}</p>
            </section>

            <section v-if="reportedObject" class="info-block">
              <h3>举报对象</h3>
              <dl class="case-fields">
                <dt>对象类型</dt>
                <dd>{{ reportedKinds[reportedObject.target_type] }}</dd>
                <dt>对象编号</dt>
                <dd>#{{ reportedObject.target_id }}</dd>
              </dl>
              <div v-if="reportedObject.product" class="snapshot-panel">
                <div class="section-heading">
                  <h4>商品快照</h4>
                  <span class="muted">
                    {{ reportedObject.product.title }} #{{ reportedObject.product.id }}
                  </span>
                </div>
                <dl class="case-fields">
                  <dt>商品名称</dt>
                  <dd>{{ reportedObject.product.title || "未填写" }}</dd>
                  <dt>商品编号</dt>
                  <dd>#{{ reportedObject.product.id }}</dd>
                  <dt>商品简介</dt>
                  <dd class="pre-line">{{ reportedObject.product.description || "未填写" }}</dd>
                </dl>
                <a
                  class="text-link"
                  :href="userProductHref(reportedObject.product.id)"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  在新标签页打开商品
                </a>
              </div>
              <a
                v-else-if="reportedObject.target_type === 'product'"
                class="text-link"
                :href="userProductHref(reportedObject.target_id)"
                target="_blank"
                rel="noopener noreferrer"
              >
                在新标签页打开商品
              </a>
              <p v-else-if="reportedObject.target_type === 'account'" class="muted">
                未记录来源商品。
              </p>
              <p
                v-else-if="
                  ['comment', 'evaluation'].includes(reportedObject.target_type) && !detail.target
                "
                class="muted"
              >
                原记录不可用。
              </p>
              <dl v-if="detail.reported_message" class="case-fields">
                <dt>举报消息位置</dt>
                <dd>
                  {{
                    detail.reported_message.conversation_kind === "chat"
                      ? "私聊"
                      : detail.reported_message.conversation_kind === "trade"
                        ? "交易会话"
                        : "事项会话"
                  }}
                  #{{ detail.reported_message.conversation_id }}
                </dd>
              </dl>
            </section>

            <section v-if="detail.decision_kind" class="info-block">
              <div class="section-heading">
                <h3>决定理由</h3>
                <span v-if="decisionKindLabels[detail.decision_kind]" class="chip">{{
                  decisionKindLabels[detail.decision_kind]
                }}</span>
              </div>
              <p v-if="detail.reason_text" class="pre-line">{{ detail.reason_text }}</p>
              <p v-if="detail.archived_at" class="muted">
                结案于 {{ formatDateTime(detail.archived_at) }}
              </p>
              <p v-if="detail.public_result_at" class="muted">
                公开于 {{ formatDateTime(detail.public_result_at) }}
              </p>
            </section>

            <section v-if="detail.enforcements.length" class="info-block">
              <div class="section-heading">
                <h3>处置结果</h3>
                <span class="muted">{{ detail.enforcements.length }} 项</span>
              </div>
              <ul class="enforcement-list">
                <li
                  v-for="item in detail.enforcements"
                  :key="item.enforcement_id"
                  class="enforcement-item"
                >
                  <div class="spread">
                    <span>
                      <strong>{{
                        enforcementOptions.find((option) => option.action === item.action)?.label ??
                        "处置"
                      }}</strong>
                      <span class="muted">
                        {{ item.result_status === "failed" ? "失败" : "已记录" }}
                      </span>
                    </span>
                    <button
                      v-if="item.can_lift"
                      type="button"
                      class="btn btn--small"
                      @click="openLift(item.enforcement_id)"
                    >
                      解除处置
                    </button>
                  </div>
                  <form
                    v-if="item.can_lift && liftDraft?.enforcementId === item.enforcement_id"
                    class="stack stack--tight nested-form"
                    :aria-labelledby="`${ids}-lift`"
                    @submit.prevent="submitLift"
                  >
                    <h4 :id="`${ids}-lift`">解除处置</h4>
                    <label class="field" :for="`${ids}-lift-reason`">
                      <span>解除原因</span>
                      <textarea
                        :id="`${ids}-lift-reason`"
                        v-model="liftDraft.reason"
                        name="reason"
                        class="textarea"
                        required
                      />
                    </label>
                    <div class="inline">
                      <button type="button" class="btn btn--small" @click="cancelLift">取消</button>
                      <button type="submit" class="btn btn--primary btn--small" :disabled="writing">
                        确认解除
                      </button>
                    </div>
                  </form>
                </li>
              </ul>
            </section>
          </div>

          <aside class="case-overview__aside">
            <section v-if="relatedAccounts.length" class="info-block">
              <div class="section-heading">
                <h3>相关账户</h3>
                <span class="muted">{{ relatedAccounts.length }} 方</span>
              </div>
              <ul class="account-list">
                <li
                  v-for="account in relatedAccounts"
                  :key="account.account_id"
                  class="account-row"
                >
                  <span class="account-avatar" aria-hidden="true">{{
                    accountInitial(account.account_id)
                  }}</span>
                  <span class="account-copy">
                    <strong>{{ account.display_name ?? "账户" }}</strong>
                    <small>{{ accountLabel(account) }}</small>
                  </span>
                </li>
              </ul>
            </section>
          </aside>
        </div>
      </section>
      <details v-if="detail.target" class="card stack">
        <summary>查看被举报{{ detail.target.target_type === "comment" ? "评论" : "评价" }}</summary>
        <p>
          {{ detail.target.target_type === "comment" ? "评论" : "评价" }} #{{
            detail.target.target_id
          }}
          · 作者账户 #{{ detail.target.author_account_id }} ·
          {{ detail.target.removed ? "已移除" : "待审核" }}
        </p>
        <p v-if="detail.target.context_id">
          {{ detail.target.target_type === "comment" ? "所属商品" : "关联交易" }}
          #{{ detail.target.context_id }}
        </p>
        <p class="pre-line">{{ detail.target.body }}</p>
        <p v-if="detail.target.created_at">发表于 {{ formatDateTime(detail.target.created_at) }}</p>
      </details>
      <section v-if="tradeHistoryAvailable" class="card record-card">
        <div class="card__head">
          <h2>交易约定与确认历史</h2>
          <button
            v-if="!tradeHistory && !tradeHistoryError"
            type="button"
            class="btn btn--small btn--ghost"
            :disabled="tradeHistoryLoading"
            @click="loadTradeHistory"
          >
            {{ tradeHistoryLoading ? "正在读取…" : "查看交易历史" }}
          </button>
        </div>
        <ErrorNotice
          v-if="tradeHistoryError"
          :error="tradeHistoryError"
          @retry="loadTradeHistory"
        />
        <div v-if="tradeHistory" class="stack">
          <p>交易 #{{ tradeHistory.trade_id }}</p>
          <section class="info-block">
            <h3>约定历史</h3>
            <p v-if="!tradeHistory.agreement_history.length">暂无约定记录。</p>
            <ul v-else>
              <li v-for="item in tradeHistory.agreement_history" :key="item.id">
                <strong
                  >第 {{ item.version_no }} 版（#{{ item.id }}） ·
                  {{ agreementStatus[item.status] }}</strong
                >
                <p>提出人 #{{ item.proposed_by }} · {{ formatDateTime(item.proposed_at) }}</p>
                <p class="pre-line">
                  交付地点 {{ item.delivery_place_text }} · {{ formatDateTime(item.delivery_at) }}
                </p>
                <p>约定金额 ¥{{ (item.amount_cents / 100).toFixed(2) }}</p>
              </li>
            </ul>
          </section>
          <section class="info-block">
            <h3>完成确认历史</h3>
            <p v-if="!tradeHistory.confirmation_history.length">暂无完成确认记录。</p>
            <ul v-else>
              <li v-for="item in tradeHistory.confirmation_history" :key="item.id">
                <strong>账户 #{{ item.confirmer_id }} · 约定 #{{ item.agreement_id }}</strong>
                <p>{{ formatDateTime(item.submitted_at) }}</p>
                <p v-if="item.note" class="pre-line">{{ item.note }}</p>
                <p v-if="item.invalidated_at">已失效 · {{ formatDateTime(item.invalidated_at) }}</p>
              </li>
            </ul>
          </section>
        </div>
      </section>
      <div class="record-layout">
        <CaseEvidenceSection
          :case-id="caseId"
          :submitted-notes="submittedNotes"
          :evidence="detail.evidence ?? undefined"
          :reported-message="detail.reported_message"
          :archived-at="detail.archived_at"
          :refresh="load"
          :state="evidenceState"
          :keys="keys"
        />

        <section v-if="detail.actions.length" class="card record-card">
          <div class="card__head">
            <div>
              <p class="section-kicker">处理轨迹</p>
              <h2>处理记录</h2>
            </div>
            <span class="chip">{{ detail.actions.length }} 条</span>
          </div>
          <ol class="activity-list">
            <li
              v-for="(item, index) in detail.actions"
              :id="item.action_id ? `case-action-${item.action_id}` : undefined"
              :key="item.action_id ?? index"
              class="activity-item"
            >
              <span class="activity-marker" aria-hidden="true" />
              <span class="activity-copy">
                <strong>{{ messages[item.action_kind] ?? "事项更新" }}</strong>
                <time :datetime="item.occurred_at">{{ formatDateTime(item.occurred_at) }}</time>
              </span>
            </li>
          </ol>
        </section>
      </div>

      <section v-if="detail.threads?.length" class="card thread-card">
        <div class="card__head">
          <div>
            <p class="section-kicker">问询与回复</p>
            <h2>事项会话</h2>
          </div>
          <span v-if="thread" class="chip">{{ thread.items.length }} 条</span>
        </div>

        <div
          v-if="detail.threads.length > 1"
          class="thread-picker"
          role="group"
          aria-label="选择事项会话对象"
        >
          <button
            v-for="item in detail.threads"
            :key="item.conversation_id"
            type="button"
            class="thread-picker__item"
            :aria-pressed="selectedThread?.conversation_id === item.conversation_id"
            @click="loadThread(item)"
          >
            <span class="account-avatar" aria-hidden="true">{{
              accountInitial(item.related_account_id)
            }}</span>
            <span>
              <strong>{{ accountDisplayName(item.related_account_id) }}</strong>
              <small>{{ threadTabLabel(item.related_account_id) }}</small>
            </span>
          </button>
        </div>

        <LoadingBlock v-if="threadLoading && !thread" label="正在读取会话…" />
        <ErrorNotice
          v-else-if="threadError"
          :error="threadError"
          @retry="selectedThread && loadThread(selectedThread, Boolean(thread))"
        />
        <template v-else-if="thread">
          <header v-if="selectedThread" class="thread-header">
            <span class="account-avatar account-avatar--large" aria-hidden="true">{{
              accountInitial(selectedThread.related_account_id)
            }}</span>
            <span>
              <strong>{{ selectedThreadTitle }}</strong>
              <small>管理员与相关方之间的事项沟通</small>
            </span>
          </header>
          <button
            v-if="
              thread.items.length >= 20 &&
              thread.next_before_seq &&
              thread.next_before_seq > 1 &&
              selectedThread
            "
            type="button"
            class="btn btn--small btn--ghost thread-load-older"
            :disabled="threadLoading"
            @click="loadThread(selectedThread, true)"
          >
            加载更早消息
          </button>
          <ol class="thread-bubbles">
            <li
              v-for="message in thread.items"
              :id="`case-message-${message.case_message_id}`"
              :key="message.case_message_id"
              class="thread-bubble"
              :class="`thread-bubble--${messageSide(message.sender.sender_kind)}`"
            >
              <div class="thread-bubble__meta">
                <strong>{{ message.sender.display_name }}</strong>
                <span>{{ messages[message.message_kind] ?? "消息" }}</span>
                <time :datetime="message.created_at">{{ formatDateTime(message.created_at) }}</time>
              </div>
              <p class="pre-line">{{ message.body }}</p>
            </li>
          </ol>
        </template>
        <p v-else class="muted">暂无沟通记录。</p>
      </section>

      <form
        v-if="actions.has('inquire')"
        class="card stack"
        :aria-labelledby="`${ids}-inquire`"
        @submit.prevent="
          submit('inquiries', { peer_account_id: peer.trim(), scope_text: inquiry.trim() })
        "
      >
        <h2 :id="`${ids}-inquire`">发起问询</h2>
        <label class="field"
          ><span>相关账户</span>
          <select
            v-model="peer"
            name="peer_account_id"
            class="select"
            required
            :disabled="eligibleAccounts.length <= 1"
            :aria-describedby="
              eligibleAccounts.length === 1 ? `${ids}-inquire-single-peer` : undefined
            "
          >
            <option value="" disabled>请选择相关账户</option>
            <option
              v-for="account in eligibleAccounts"
              :key="account.account_id"
              :value="account.account_id"
            >
              {{ accountLabel(account) }}
            </option>
          </select>
          <span
            v-if="eligibleAccounts.length === 1"
            :id="`${ids}-inquire-single-peer`"
            class="field__hint"
          >
            该事项只有一名可问询对象，已默认选中。
          </span>
        </label>
        <label class="field"
          ><span>问询内容</span>
          <textarea v-model="inquiry" name="scope_text" class="textarea" required />
        </label>
        <div>
          <button
            type="submit"
            class="btn btn--primary"
            :disabled="writing || !eligibleAccounts.length"
          >
            发起问询
          </button>
        </div>
      </form>

      <form
        v-if="actions.has('decide')"
        class="card stack"
        :aria-labelledby="`${ids}-decide`"
        @submit.prevent="submitDecision"
      >
        <h2 :id="`${ids}-decide`">处置决定</h2>
        <label class="field"
          ><span>结论</span>
          <select v-model="decisionKind" name="decision_kind" class="select" required>
            <option value="no_action">不予处置</option>
            <option value="not_actionable">不予受理</option>
            <option value="violation">认定违规</option>
          </select>
        </label>
        <label class="field"
          ><span>决定理由</span>
          <textarea v-model="decisionReason" name="reason" class="textarea" required />
        </label>
        <fieldset class="stack">
          <legend>补充依据（可选）</legend>
          <p v-if="!detail.decision_basis_actions?.length && !basisEvidence.length" class="muted">
            暂无可引用的问询、回复或用户材料。
          </p>
          <label v-for="item in detail.decision_basis_actions" :key="item.action_id">
            <input v-model="basis" type="checkbox" :value="`action:${item.action_id}`" />
            {{ messages[item.action_kind] }} · {{ formatDateTime(item.occurred_at) }}
            <span v-if="item.note" class="pre-line"> · {{ item.note }}</span>
          </label>
          <div v-for="item in basisEvidence" :key="item.evidence_id" class="inline">
            <label>
              <input v-model="basis" type="checkbox" :value="`evidence:${item.evidence_id}`" />
              用户上传附件 · 证据 #{{ item.evidence_id }}
              <span v-if="item.submitted_at"> · {{ formatDateTime(item.submitted_at) }}</span>
            </label>
            <a
              :href="caseEvidenceFileHref(caseId, item.evidence_id)"
              target="_blank"
              rel="noopener noreferrer"
              >打开附件</a
            >
          </div>
        </fieldset>
        <template v-if="decisionKind === 'violation'">
          <fieldset v-for="instruction in instructions" :key="instruction.id" class="stack">
            <legend>处置项</legend>
            <label class="field"
              ><span>动作</span>
              <select
                v-model="instruction.option"
                @change="instruction.targetId = ''"
                :name="`action-${instruction.id}`"
                class="select"
              >
                <option
                  v-for="(option, index) in enforcementOptions"
                  :key="option.action + option.target"
                  :value="index"
                  :disabled="!dispositionChoices[index].length"
                >
                  {{ option.label }}
                </option>
              </select>
            </label>
            <p v-if="dispositionChoices[instruction.option].length === 1" class="muted">
              处置对象 · {{ dispositionChoices[instruction.option][0].label }}
            </p>
            <label v-else class="field">
              <span>处置对象</span>
              <select
                v-model="instruction.targetId"
                :name="`target-${instruction.id}`"
                class="select"
                required
              >
                <option value="" disabled>请选择处置对象</option>
                <option
                  v-for="target in dispositionChoices[instruction.option]"
                  :key="target.id"
                  :value="target.id"
                >
                  {{ target.label }}
                </option>
              </select>
            </label>
            <label
              v-if="enforcementOptions[instruction.option].action === 'adjust_trade_status'"
              class="field"
              ><span>目标状态</span>
              <select
                v-model="instruction.expected"
                :name="`state-${instruction.id}`"
                class="select"
              >
                <option value="terminated">已终止</option>
                <option value="completed">已完成</option>
                <option value="in_progress">恢复进行中（仅异常交易）</option>
              </select>
              <span class="muted"
                >恢复进行中保留锁单与冻结，清空当前完成确认但不启动计时；交易须与本案目标一致。</span
              >
            </label>
            <div>
              <button
                type="button"
                class="btn btn--ghost"
                @click="instructions = instructions.filter((item) => item.id !== instruction.id)"
              >
                移除此项
              </button>
            </div>
          </fieldset>
          <div v-if="dispositionChoices.some((choices) => choices.length)">
            <button type="button" class="btn" @click="addInstruction">添加处置项</button>
          </div>
        </template>
        <div>
          <button type="submit" class="btn btn--primary" :disabled="writing">提交决定</button>
        </div>
      </form>

      <section v-if="actions.has('resolve_appeal') && appealDrafts.length" class="card stack">
        <h2>待处理申辩</h2>
        <form
          v-for="{ appeal, draft } in appealDrafts"
          :key="appeal.appeal_action_id"
          class="stack"
          :aria-label="`处理申辩 #${appeal.appeal_action_id}`"
          @submit.prevent="resolveAppeal(appeal, draft)"
        >
          <p>账户 #{{ appeal.related_account_id }} · {{ formatDateTime(appeal.submitted_at) }}</p>
          <fieldset class="stack">
            <legend>处理结果</legend>
            <label>
              <input
                v-model="draft.resolution"
                type="radio"
                name="resolution"
                value="uphold"
                required
              />
              维持原决定
            </label>
            <label>
              <input
                v-model="draft.resolution"
                type="radio"
                name="resolution"
                value="revoke"
                :disabled="!appeal.original_enforcements?.length"
                required
              />
              撤销原处置
            </label>
            <label>
              <input
                v-model="draft.resolution"
                type="radio"
                name="resolution"
                value="adjust"
                :disabled="!appeal.original_enforcements?.length"
                required
              />
              调整处置
            </label>
          </fieldset>
          <p v-if="!appeal.original_enforcements?.length" class="muted">
            没有可撤销或调整的原处置，只能维持原决定。
          </p>
          <label
            v-if="draft.resolution === 'revoke' || draft.resolution === 'adjust'"
            class="field"
          >
            <span>原处置</span>
            <select
              v-model="draft.originalId"
              name="original_enforcement_id"
              class="select"
              required
              @change="draft.replacementAction = ''"
            >
              <option value="" disabled>请选择原处置</option>
              <option
                v-for="item in appeal.original_enforcements ?? []"
                :key="item.enforcement_id"
                :value="item.enforcement_id"
              >
                {{ appealEnforcementLabel(item) }} · {{ item.enforcement_id }} · 目标 #{{
                  item.target_id
                }}
              </option>
            </select>
          </label>
          <template v-if="draft.resolution === 'adjust'">
            <label class="field">
              <span>替代处置</span>
              <select
                v-model="draft.replacementAction"
                name="replacement_action"
                class="select"
                required
              >
                <option value="" disabled>请选择替代处置</option>
                <option
                  v-for="option in appealReplacementOptions(appeal, draft)"
                  :key="`${option.action}-${option.target}`"
                  :value="option.action"
                >
                  {{ option.label }}
                </option>
              </select>
            </label>
            <p
              v-if="draft.originalId && appealReplacementOptions(appeal, draft).length === 0"
              class="muted"
            >
              该原处置暂不支持调整，请选择撤销或维持。
            </p>
            <label v-if="draft.replacementAction === 'adjust_trade_status'" class="field">
              <span>目标状态</span>
              <select
                v-model="draft.replacementExpected"
                name="replacement_expected_result"
                class="select"
              >
                <option value="terminated">已终止</option>
                <option value="completed">已完成</option>
              </select>
            </label>
          </template>
          <label class="field"
            ><span>回复内容</span>
            <textarea v-model="draft.reply" name="reply" class="textarea" required />
          </label>
          <fieldset class="stack">
            <legend>依据引用（至少选一项）</legend>
            <label>
              <input
                v-model="draft.basis"
                type="checkbox"
                :value="`action:${appeal.appeal_action_id}`"
              />
              本次申辩 · {{ formatDateTime(appeal.submitted_at) }}
            </label>
            <label v-for="item in detail.decision_basis_actions" :key="item.action_id">
              <input v-model="draft.basis" type="checkbox" :value="`action:${item.action_id}`" />
              {{ messages[item.action_kind] }} · {{ formatDateTime(item.occurred_at) }}
              <span v-if="item.note" class="pre-line"> · {{ item.note }}</span>
            </label>
            <div v-for="item in basisEvidence" :key="item.evidence_id" class="inline">
              <label>
                <input
                  v-model="draft.basis"
                  type="checkbox"
                  :value="`evidence:${item.evidence_id}`"
                />
                用户上传附件 · 证据 #{{ item.evidence_id }}
                <span v-if="item.submitted_at"> · {{ formatDateTime(item.submitted_at) }}</span>
              </label>
              <a
                :href="caseEvidenceFileHref(caseId, item.evidence_id)"
                target="_blank"
                rel="noopener noreferrer"
              >
                打开附件
              </a>
            </div>
          </fieldset>
          <div class="inline">
            <button type="submit" class="btn btn--primary" :disabled="writing">提交处理</button>
          </div>
        </form>
      </section>

      <section v-if="actions.has('close')" class="card stack">
        <h2>结案归档</h2>
        <div class="inline">
          <button v-if="!confirmClose" type="button" class="btn" @click="confirmClose = true">
            结案
          </button>
          <template v-else>
            <button type="button" class="btn" @click="confirmClose = false">取消</button>
            <button
              type="button"
              class="btn btn--danger"
              :disabled="writing"
              @click="submit('close', undefined)"
            >
              确认结案
            </button>
          </template>
        </div>
      </section>

      <form
        v-if="actions.has('publish_result')"
        class="card stack"
        :aria-labelledby="`${ids}-publish`"
        @submit.prevent="
          submit('publish-result', {
            public_summary: publicSummary.trim(),
            public_reason: publicReason.trim(),
          })
        "
      >
        <h2 :id="`${ids}-publish`">公开匿名结果</h2>
        <p class="muted">公开内容应删去账户身份、会话和申辩信息。</p>
        <label class="field"
          ><span>公开结论</span>
          <input v-model="publicSummary" name="public_summary" class="input" required />
        </label>
        <label class="field"
          ><span>公开原因</span>
          <textarea v-model="publicReason" name="public_reason" class="textarea" required />
        </label>
        <div>
          <button type="submit" class="btn btn--primary" :disabled="writing">公开结果</button>
        </div>
      </form>
      <p v-if="writeError" class="field__error" role="alert">{{ writeError }}</p>
    </template>
  </div>
</template>

<style scoped>
.section-kicker {
  margin: 0;
  color: var(--info);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.case-overview {
  container-type: inline-size;
}

.case-overview__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding-block-end: var(--space-3);
  border-block-end: 1px solid var(--line);
}

.case-overview__header h2 {
  margin-block-start: var(--space-1);
  font-size: 1.125rem;
}

.case-status {
  flex: 0 0 auto;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  padding: 0.18rem 0.62rem;
  color: var(--ink-soft);
  background: var(--panel-soft);
  font-size: 0.75rem;
  font-weight: 650;
}

.case-status--pending {
  color: var(--warn);
  background: var(--warn-soft);
  border-color: #e6d3ad;
}

.case-status--claimed {
  color: var(--info);
  background: var(--info-soft);
  border-color: #cad9eb;
}

.case-status--decided,
.case-status--archived {
  color: var(--ok);
  background: var(--ok-soft);
  border-color: #c9dfd1;
}

.case-overview__layout {
  display: grid;
  gap: var(--space-4);
  margin-block-start: var(--space-3);
}

.case-overview__aside {
  display: grid;
  gap: var(--space-3);
  align-content: start;
}

.info-block {
  min-inline-size: 0;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: linear-gradient(180deg, #fff, #fbfcfb);
}

.info-block h3 {
  margin: 0;
  font-size: 0.875rem;
}

.body-copy {
  margin-block-start: var(--space-2);
  font-size: 0.9375rem;
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-block-end: var(--space-2);
}

.account-list,
.enforcement-list,
.activity-list,
.thread-bubbles {
  list-style: none;
  margin: 0;
  padding: 0;
}

.account-list {
  display: grid;
  gap: var(--space-2);
}

.account-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.account-row + .account-row {
  padding-block-start: var(--space-2);
  border-block-start: 1px solid var(--line);
}

.account-avatar {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  inline-size: 2rem;
  block-size: 2rem;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-size: 0.8125rem;
  font-weight: 700;
}

.account-avatar--large {
  inline-size: 2.5rem;
  block-size: 2.5rem;
}

.account-copy,
.activity-copy,
.thread-header > span:last-child {
  display: grid;
  min-inline-size: 0;
  gap: 0.1rem;
}

.account-copy small,
.thread-header small,
.thread-picker__item small {
  color: var(--ink-faint);
  font-size: 0.75rem;
}

.enforcement-list {
  display: grid;
  gap: var(--space-2);
}

.enforcement-item {
  padding: var(--space-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
}

.enforcement-item strong {
  margin-inline-end: var(--space-2);
}

.nested-form {
  margin-block-start: var(--space-2);
  padding-block-start: var(--space-2);
  border-block-start: 1px dashed var(--line-strong);
}

.nested-form h4 {
  margin: 0;
  font-size: 0.8125rem;
}

.case-fields {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--space-1) var(--space-3);
  margin: 0;
  font-size: 0.8125rem;
}

details > .case-fields {
  margin-block-start: var(--space-2);
}

.case-fields dt {
  font-weight: 600;
}

.case-fields dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.snapshot-panel {
  margin-block-start: var(--space-3);
  padding-block-start: var(--space-2);
  border-block-start: 1px solid var(--line);
}

.snapshot-panel h4 {
  margin: 0;
  font-size: 0.82rem;
}

.text-link {
  display: inline-flex;
  margin-block-start: var(--space-2);
  color: var(--info);
  font-size: 0.8125rem;
}

.record-layout {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 26rem), 1fr));
  gap: var(--space-4);
  align-items: start;
}

.record-card {
  min-inline-size: 0;
}

.activity-list {
  display: grid;
}

.activity-item {
  position: relative;
  display: grid;
  grid-template-columns: 0.65rem minmax(0, 1fr);
  gap: var(--space-3);
  padding-block: 0.55rem;
}

.activity-item:not(:last-child)::before {
  position: absolute;
  inset-block: 1rem calc(-0.55rem);
  inset-inline-start: 0.28rem;
  inline-size: 1px;
  background: var(--line);
  content: "";
}

.activity-marker {
  position: relative;
  z-index: 1;
  inline-size: 0.65rem;
  block-size: 0.65rem;
  margin-block-start: 0.24rem;
  border: 2px solid var(--panel);
  border-radius: 999px;
  background: var(--brand);
  box-shadow: 0 0 0 1px var(--brand);
}

.activity-copy {
  gap: 0.15rem;
  font-size: 0.8125rem;
}

.activity-copy time {
  color: var(--ink-faint);
  font-size: 0.75rem;
}

.thread-card {
  container-type: inline-size;
}

.thread-picker {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-block-end: var(--space-3);
}

.thread-picker__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-block-size: var(--control-min-block);
  padding: var(--space-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  color: inherit;
  background: var(--panel);
  text-align: start;
  cursor: pointer;
}

.thread-picker__item[aria-pressed="true"] {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.thread-picker__item > span:last-child {
  display: grid;
  gap: 0.08rem;
}

.thread-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-block-end: var(--space-3);
  padding-block-end: var(--space-3);
  border-block-end: 1px solid var(--line);
}

.thread-load-older {
  align-self: flex-start;
  margin-block-end: var(--space-3);
}

.thread-bubbles {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.thread-bubble {
  max-inline-size: min(88%, 42rem);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: #fbfcfb;
}

.thread-bubble--manager {
  align-self: flex-end;
  border-color: #cbe3d4;
  background: var(--brand-soft);
}

.thread-bubble--account {
  align-self: flex-start;
}

.thread-bubble--system {
  align-self: center;
  max-inline-size: 36rem;
  border-style: dashed;
  background: var(--panel-soft);
  text-align: center;
}

.thread-bubble__meta {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
  color: var(--ink-faint);
  font-size: 0.72rem;
}

.thread-bubble__meta strong {
  color: var(--ink);
  font-size: 0.78rem;
}

.thread-bubble__meta time {
  margin-inline-start: auto;
}

.thread-bubble > p {
  margin-block-start: var(--space-1);
  font-size: 0.875rem;
}

@container (min-width: 50rem) {
  .case-overview__layout {
    grid-template-columns: minmax(0, 1.2fr) minmax(19rem, 0.8fr);
  }
}

@media (width < 40rem) {
  .case-overview__header {
    align-items: flex-start;
    flex-direction: column;
  }

  .thread-bubble {
    max-inline-size: 96%;
  }

  .thread-bubble__meta time {
    margin-inline-start: 0;
  }
}

.pre-line {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

fieldset {
  border: 1px solid var(--line);
  padding: var(--space-3);
  min-inline-size: 0;
}
</style>
