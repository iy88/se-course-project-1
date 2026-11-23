<script setup lang="ts">
/*
 * Case detail with the constrained conversation (US-08, US-14).
 *
 * A reporter only reads the progress and can add supplements; a related account
 * answers an inquiry or submits an appeal before its deadline. The screen derives
 * those capabilities from the case payload (`thread`, `appeal_deadline_at`,
 * archived state) instead of from the case status alone.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { getCase, postCaseMessage, supplementReport } from "../../api/cases";
import { listMyTodos } from "../../api/aggregation";
import { listMessages } from "../../api/conversations";
import type { CaseDetail, CaseMessage, CaseMessageKind } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { caseHasScope } from "../../app/case-directory";
import { formatDateTime, formatRemaining } from "../../app/format";
import { newIdempotencyKey } from "../../app/keys";
import {
  caseActionKindText,
  caseActorKindText,
  caseDecisionLabels,
  caseMessageKindLabels,
  caseStatusLabels,
  caseStatusTones,
  enforcementActionText,
  enforcementStateText,
} from "../../app/labels";
import { problemMessage } from "../../app/problems";
import { session } from "../../app/session";
import { notify } from "../../app/toast";
import { refreshBadges } from "../../app/badges";
import ErrorNotice from "../../components/ErrorNotice.vue";
import ImageUploader from "../../components/ImageUploader.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import StateBadge from "../../components/StateBadge.vue";

const route = useRoute();
const caseId = computed(() => String(route.params.caseId ?? ""));
const detail = useAsyncData<CaseDetail>((signal) => getCase(caseId.value, signal));

const threadMessages = ref<CaseMessage[]>([]);
const threadStatus = ref<"idle" | "loading" | "ready" | "failed">("idle");
const threadError = ref<unknown>(null);

/* One open reply form at a time, keyed by the inquiry action it answers. */
const replyingTo = ref<string | null>(null);
const replyBody = ref("");
const replyPending = ref(false);
const replyError = ref<string | null>(null);

/* Appeals are a separate entry point and carry no inquiry reference. */
const appealBody = ref("");
const appealPending = ref(false);
const appealError = ref<string | null>(null);

/* Pending inquiries come from the todo aggregation, not from the message list. */
const pendingInquiryIds = ref<string[]>([]);

const supplementNote = ref("");
const supplementFiles = ref<string[]>([]);
const supplementPending = ref(false);
const supplementError = ref<string | null>(null);

/*
 * The reporter viewpoint comes from the list scope, not from the appeal deadline:
 * `appeal_deadline_at` only exists for the punished side, so a merely inquired
 * account would otherwise look like a reporter. A deep link has no remembered
 * scope and therefore hides the reporter-only entry instead of guessing.
 */
const isReporterView = computed(() => caseHasScope(caseId.value, "mine"));
const archived = computed(() => Boolean(detail.data.value?.archived_at));
const appealDeadline = computed(() => detail.data.value?.appeal_deadline_at ?? null);
const appealOpen = computed(() => {
  if (!appealDeadline.value) return false;
  return new Date(appealDeadline.value).getTime() > Date.now();
});
const appealRemaining = computed(() => {
  if (!appealDeadline.value) return 0;
  return Math.max(0, Math.round((new Date(appealDeadline.value).getTime() - Date.now()) / 1000));
});

const canSupplement = computed(
  () => !archived.value && isReporterView.value && detail.data.value?.case_type === "report",
);

async function loadThread(): Promise<void> {
  const thread = detail.data.value?.thread;
  if (!thread) {
    threadStatus.value = "ready";
    threadMessages.value = [];
    return;
  }
  threadStatus.value = "loading";
  threadError.value = null;
  try {
    const page = await listMessages(thread.conversation_kind, thread.conversation_id, {
      limit: 100,
    });
    threadMessages.value = page.items.map((message) => ({
      case_message_id: message.message_id,
      seq: message.seq,
      message_kind: (message.message_type as CaseMessageKind) ?? "statement",
      body: message.body,
      sender: message.sender,
      created_at: message.created_at,
    }));
    threadStatus.value = "ready";
  } catch (caught) {
    threadError.value = caught;
    threadStatus.value = "failed";
  }
}

async function loadPendingInquiries(): Promise<void> {
  const current = detail.data.value;
  pendingInquiryIds.value = [];
  if (!current) return;
  try {
    const todos = await listMyTodos({ page: 1, page_size: 50 });
    const ids = new Set<string>();
    for (const todo of todos.items) {
      if (todo.kind !== "inquiry_response") continue;
      const source = todo.source as { case_id?: unknown; inquiry_action_ids?: unknown };
      if (String(source.case_id ?? "") !== current.case_id) continue;
      if (!Array.isArray(source.inquiry_action_ids)) continue;
      for (const id of source.inquiry_action_ids) {
        if (id !== null && id !== undefined && String(id) !== "") ids.add(String(id));
      }
    }
    pendingInquiryIds.value = [...ids];
  } catch {
    // The todo projection is an auxiliary entry point; a failure must not hide the case.
    pendingInquiryIds.value = [];
  }
}

async function load(): Promise<void> {
  await detail.run();
  await loadThread();
  await loadPendingInquiries();
}

onMounted(() => {
  void load();
});

watch(caseId, () => {
  void load();
});

function openInquiryReply(actionId: string): void {
  replyingTo.value = replyingTo.value === actionId ? null : actionId;
  replyBody.value = "";
  replyError.value = null;
}

async function submitInquiryReply(): Promise<void> {
  const current = detail.data.value;
  const thread = current?.thread;
  const actionId = replyingTo.value;
  if (!current || !thread || !actionId || replyPending.value) return;
  if (!replyBody.value.trim()) {
    replyError.value = "请填写说明内容。";
    return;
  }
  replyError.value = null;
  replyPending.value = true;
  try {
    await postCaseMessage(
      current.case_id,
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
    await load();
    void refreshBadges();
  } catch (caught) {
    replyError.value = problemMessage(caught);
  } finally {
    replyPending.value = false;
  }
}

async function submitAppeal(): Promise<void> {
  const current = detail.data.value;
  const thread = current?.thread;
  if (!current || !thread || appealPending.value) return;
  if (!appealBody.value.trim()) {
    appealError.value = "请填写申辩内容。";
    return;
  }
  appealError.value = null;
  appealPending.value = true;
  try {
    await postCaseMessage(
      current.case_id,
      { thread, message_kind: "appeal", body: appealBody.value.trim() },
      newIdempotencyKey(),
    );
    appealBody.value = "";
    notify.success("申辩已提交。");
    await load();
    void refreshBadges();
  } catch (caught) {
    appealError.value = problemMessage(caught);
  } finally {
    appealPending.value = false;
  }
}

async function submitSupplement(): Promise<void> {
  const current = detail.data.value;
  if (!current || supplementPending.value) return;
  if (!supplementNote.value.trim() && !supplementFiles.value.length) {
    supplementError.value = "请填写补充说明或上传证据。";
    return;
  }
  supplementError.value = null;
  supplementPending.value = true;
  try {
    const result = await supplementReport(
      current.case_id,
      {
        note: supplementNote.value.trim() || undefined,
        attachments: supplementFiles.value.map((fileId) => ({ file_id: fileId })),
      },
      newIdempotencyKey(),
    );
    supplementNote.value = "";
    supplementFiles.value = [];
    notify.success(`已补充材料（第 ${result.supplement_count} 次）。`);
    await load();
  } catch (caught) {
    supplementError.value = problemMessage(caught);
  } finally {
    supplementPending.value = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <LoadingBlock v-if="detail.isLoading.value && !detail.data.value" label="正在加载事项…" />
    <ErrorNotice v-else-if="detail.problem.value" :error="detail.error.value" @retry="load" />
    <template v-else-if="detail.data.value">
      <PageHeader
        eyebrow="事项"
        :title="`事项 #${detail.data.value.case_id}`"
        :description="`当前进度：${caseStatusLabels[detail.data.value.case_status]}`"
      >
        <template #actions>
          <RouterLink to="/me/cases" class="btn btn--ghost">返回事项列表</RouterLink>
        </template>
      </PageHeader>

      <section class="card stack">
        <div class="inline">
          <StateBadge
            :label="
              detail.data.value.archived_at
                ? '已结案'
                : caseStatusLabels[detail.data.value.case_status]
            "
            :tone="
              detail.data.value.archived_at
                ? 'neutral'
                : caseStatusTones[detail.data.value.case_status]
            "
          />
          <span class="chip">{{
            detail.data.value.case_type === "report"
              ? "举报"
              : detail.data.value.case_type === "product_review"
                ? "商品审核"
                : "异常交易"
          }}</span>
          <span v-if="detail.data.value.decision_kind" class="chip chip--active">
            {{ caseDecisionLabels[detail.data.value.decision_kind] }}
          </span>
        </div>

        <p v-if="detail.data.value.reason_text" class="reason pre-line break-anywhere">
          {{ detail.data.value.reason_text }}
        </p>

        <p v-if="appealDeadline" class="banner banner--warn">
          申辩截止：{{ formatDateTime(appealDeadline) }}
          <template v-if="appealOpen"> · 剩余 {{ formatRemaining(appealRemaining) }}</template>
          <template v-else>· 申辩期已结束</template>
        </p>

        <div v-if="detail.data.value.enforcements.length" class="stack stack--tight">
          <span class="field__label">处置结果</span>
          <ul class="plain-list">
            <li v-for="(item, index) in detail.data.value.enforcements" :key="index">
              <span class="state state--danger">{{ enforcementActionText(item.action) }}</span>
              <span class="muted">当前状态：{{ enforcementStateText(item.current_state) }}</span>
            </li>
          </ul>
        </div>

        <div v-if="detail.data.value.public_result_at" class="banner banner--info">
          该事项的匿名结果已于 {{ formatDateTime(detail.data.value.public_result_at) }} 公开。
        </div>
      </section>

      <section class="card">
        <div class="card__head"><h2>进度</h2></div>
        <ol class="timeline">
          <li v-for="(action, index) in detail.data.value.actions" :key="index">
            <span class="timeline__dot" aria-hidden="true" />
            <span class="timeline__body">
              <span>{{ caseActionKindText(action.action_kind) }}</span>
              <span class="muted">
                {{ formatDateTime(action.occurred_at) }} ·
                {{ caseActorKindText(action.actor_kind) }}
              </span>
            </span>
          </li>
          <li v-if="!detail.data.value.actions.length" class="muted">暂无进度记录。</li>
        </ol>
      </section>

      <section class="card">
        <div class="card__head">
          <h2>沟通记录</h2>
          <span class="chip">{{ threadMessages.length }} 条</span>
        </div>
        <LoadingBlock v-if="threadStatus === 'loading'" label="正在加载沟通记录…" />
        <ErrorNotice v-else-if="threadError" :error="threadError" @retry="loadThread" />
        <p v-else-if="!threadMessages.length" class="muted">
          暂无沟通记录。管理员发起问询后会显示在这里。
        </p>
        <ul v-else class="thread">
          <li
            v-for="message in threadMessages"
            :key="message.case_message_id"
            class="thread__item"
            :class="{ 'thread__item--mine': message.sender.account_id === session.accountId.value }"
          >
            <div class="thread__meta">
              <span class="chip">{{
                caseMessageKindLabels[message.message_kind] ?? message.message_kind
              }}</span>
              <span class="muted">{{ message.sender.display_name }}</span>
              <span class="muted">{{ formatDateTime(message.created_at) }}</span>
            </div>
            <p class="thread__body pre-line break-anywhere">{{ message.body }}</p>
          </li>
        </ul>

        <p v-if="archived" class="banner banner--info">
          事项已结案，不能再发言；历史记录仍可查看。
        </p>
        <template v-else>
          <div v-if="pendingInquiryIds.length" class="stack stack--tight">
            <span class="field__label">待回复的问询</span>
            <div v-for="(actionId, index) in pendingInquiryIds" :key="actionId" class="reply-entry">
              <div class="inline">
                <button
                  type="button"
                  class="btn btn--small"
                  :disabled="replyPending"
                  @click="openInquiryReply(actionId)"
                >
                  {{ replyingTo === actionId ? "收起" : "回复问询" }}
                  <template v-if="pendingInquiryIds.length > 1">
                    （{{ index + 1 }}/{{ pendingInquiryIds.length }}）
                  </template>
                </button>
                <span class="muted">针对该条问询提交说明</span>
              </div>
              <form
                v-if="replyingTo === actionId"
                class="thread__compose"
                @submit.prevent="submitInquiryReply"
              >
                <div class="field">
                  <label class="field__label" :for="`reply-body-${actionId}`">说明内容</label>
                  <textarea
                    :id="`reply-body-${actionId}`"
                    v-model="replyBody"
                    class="textarea"
                    maxlength="2000"
                  />
                </div>
                <p v-if="replyError" class="field__error" role="alert">{{ replyError }}</p>
                <div class="inline">
                  <button type="submit" class="btn btn--primary" :disabled="replyPending">
                    {{ replyPending ? "提交中…" : "提交说明" }}
                  </button>
                </div>
              </form>
            </div>
          </div>

          <template v-if="appealDeadline && appealOpen">
            <div class="reply-entry">
              <div class="inline">
                <span class="field__label">处置申辩</span>
                <span class="muted">截止 {{ formatDateTime(appealDeadline) }}</span>
              </div>
              <form class="thread__compose" @submit.prevent="submitAppeal">
                <div class="field">
                  <label class="field__label" for="appeal-body">申辩内容</label>
                  <textarea
                    id="appeal-body"
                    v-model="appealBody"
                    class="textarea"
                    maxlength="2000"
                  />
                </div>
                <p v-if="appealError" class="field__error" role="alert">{{ appealError }}</p>
                <div class="inline">
                  <button type="submit" class="btn btn--primary" :disabled="appealPending">
                    {{ appealPending ? "提交中…" : "提交申辩" }}
                  </button>
                </div>
              </form>
            </div>
          </template>

          <p v-if="!pendingInquiryIds.length && !(appealDeadline && appealOpen)" class="muted">
            当前没有需要回复的问询或可提交的申辩。
          </p>
        </template>
      </section>

      <!--
        Reporter-only entry: the viewpoint is not part of the detail payload, so it
        is taken from the list scope. Without it the entry stays hidden and the page
        says how to reach it instead of guessing.
      -->
      <p
        v-if="
          !canSupplement && !archived && detail.data.value.case_type === 'report' && !isReporterView
        "
        class="banner banner--info"
      >
        从「我的事项 → 我提交的」打开本事项，才能补充说明与证据。
      </p>

      <section v-if="canSupplement" class="card">
        <div class="card__head"><h2>补充材料</h2></div>
        <p class="muted">可补充说明与证据；补充不会改变事项状态与已作出的决定。</p>
        <div class="field">
          <label class="field__label" for="supplement-note">补充说明</label>
          <textarea
            id="supplement-note"
            v-model="supplementNote"
            class="textarea"
            maxlength="1000"
          />
        </div>
        <ImageUploader
          v-model="supplementFiles"
          purpose="case_evidence"
          label="证据文件"
          hint="支持 JPG、PNG、PDF"
          :max-count="5"
          :target="{ resource_type: 'case', resource_id: detail.data.value.case_id }"
        />
        <p v-if="supplementError" class="field__error" role="alert">{{ supplementError }}</p>
        <div class="inline">
          <button
            type="button"
            class="btn btn--primary"
            :disabled="supplementPending"
            @click="submitSupplement"
          >
            {{ supplementPending ? "提交中…" : "提交补充" }}
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.reason {
  font-size: 0.875rem;
  color: var(--ink-soft);
}

.plain-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: 0.875rem;
}

.plain-list li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.timeline li {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}

.timeline__dot {
  inline-size: 0.5rem;
  block-size: 0.5rem;
  margin-block-start: 0.5rem;
  border-radius: 50%;
  background: var(--brand);
  flex: 0 0 auto;
}

.timeline__body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  font-size: 0.875rem;
}

.thread {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.thread__item {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: #fbfcfb;
  max-inline-size: 90%;
}

.thread__item--mine {
  margin-inline-start: auto;
  background: var(--brand-soft);
  border-color: #cbe3d4;
}

.thread__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-block-end: 0.125rem;
}

.thread__body {
  font-size: 0.875rem;
}

.reply-entry {
  padding: var(--space-3);
  background: #fbfcfb;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}

.reply-entry + .reply-entry {
  margin-block-start: var(--space-2);
}

.thread__compose {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  border-block-start: 1px solid var(--line);
  margin-block-start: var(--space-4);
  padding-block-start: var(--space-3);
}
</style>
