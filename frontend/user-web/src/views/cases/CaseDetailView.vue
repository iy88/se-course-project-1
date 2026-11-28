<script setup lang="ts">
/*
 * Case detail with the constrained conversation (US-08, US-14).
 *
 * A reporter only reads the progress and can add supplements; a related account
 * answers an inquiry or submits an appeal before its deadline. The screen derives
 * those capabilities from the case payload (`thread`, `appeal_deadline_at`,
 * archived state) instead of from the case status alone.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { getCase, postCaseMessage, supplementReport } from "../../api/cases";
import { listMyTodos } from "../../api/aggregation";
import type { CaseDetail, TodoItem } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { caseHasScope } from "../../app/case-directory";
import { caseActionAvailability } from "../../app/case-actions";
import {
  appealOpenAt,
  appealRemainingMs,
  inquiryIdsForCase,
  shouldLoadNextPage,
} from "../../app/case-inquiries";
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
import { useCaseThread } from "./useCaseThread";

const route = useRoute();
const caseId = computed(() => String(route.params.caseId ?? ""));
const detail = useAsyncData<CaseDetail>((signal) => getCase(caseId.value, signal));

const { threadMessages, threadStatus, threadError, anchorMessageId, loadThread, cancelThread } =
  useCaseThread(() => detail.data.value?.thread);

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

const supplementDialog = ref<HTMLDialogElement | null>(null);
const supplementOpen = ref(false);
const reportMaterials = computed(() => detail.data.value?.report_materials);
const caseTypeLabel = computed(() => {
  const kind = detail.data.value?.case_type;
  if (kind === "report") return "举报";
  if (kind === "product_review") return "商品审核";
  return "异常交易";
});
const pageDescription = computed(() =>
  detail.data.value
    ? `${caseTypeLabel.value} · 当前进度：${caseStatusLabels[detail.data.value.case_status]}`
    : "查看事项进度与材料。",
);

function attachmentKindLabel(contentType?: string): string {
  if (contentType === "application/pdf") return "PDF 附件";
  if (contentType?.startsWith("image/")) return "图片附件";
  return "附件";
}

function toggleSupplement(): void {
  const dialog = supplementDialog.value;
  if (!dialog) return;
  if (dialog.open) {
    dialog.close();
  } else {
    dialog.showModal();
    supplementOpen.value = true;
  }
}

const supplementNote = ref("");
const supplementFiles = ref<string[]>([]);
const supplementPending = ref(false);
const supplementError = ref<string | null>(null);

/*
 * The reporter viewpoint comes from the server projection when present, otherwise from
 * the list scope. It never comes from the appeal deadline: that field only exists for
 * the punished side, so a merely inquired account would otherwise look like a reporter.
 * A deep link has no remembered scope and therefore hides the reporter-only entry.
 */
const isReporterView = computed(() => {
  const viewpoint = detail.data.value?.viewpoint;
  if (viewpoint) return viewpoint === "reporter";
  // A deep link has no remembered list scope, so fall back to it only when the
  // server did not project a viewpoint.
  return caseHasScope(caseId.value, "mine");
});
const archived = computed(() => Boolean(detail.data.value?.archived_at));
const appealDeadline = computed(() => detail.data.value?.appeal_deadline_at ?? null);
/*
 * The deadline is compared against a ticking clock: a computed that reads `Date.now()`
 * only recomputes when its dependencies change, so a page left open across the deadline
 * would keep offering the appeal form.
 */
const clock = ref(Date.now());
let clockTimer: ReturnType<typeof setInterval> | null = null;
const appealOpen = computed(() => appealOpenAt(appealDeadline.value, clock.value));
const appealRemaining = computed(() =>
  Math.round(appealRemainingMs(appealDeadline.value, clock.value) / 1000),
);

/*
 * Server-projected actions win when present; otherwise the viewer falls back to the
 * list scope (reporter entry), the appeal deadline and the pending inquiry ids.
 */
const availability = computed(() =>
  caseActionAvailability({
    projected: detail.data.value?.available_actions ?? null,
    archived: archived.value,
    reporterView: isReporterView.value,
    caseType: detail.data.value?.case_type ?? null,
    appealOpen: appealOpen.value,
    pendingInquiryCount: pendingInquiryIds.value.length,
  }),
);

const canSupplement = computed(() => availability.value.supplement);
const canRespond = computed(() => availability.value.respond);
const canAppeal = computed(() => availability.value.appeal);

/*
 * The todo projection is global, so the case is located by paging `inquiry_response`
 * todos until it appears. The request counter drops a response that belongs to a case
 * the reader already left, which would otherwise write ids into the new page.
 */
const INQUIRY_PAGE_SIZE = 50;
const INQUIRY_MAX_PAGES = 5;
let inquiryRequest = 0;

async function loadPendingInquiries(): Promise<void> {
  const current = detail.data.value;
  const request = ++inquiryRequest;
  pendingInquiryIds.value = [];
  if (!current) return;
  const caseId = current.case_id;
  const projected = current.pending_inquiries;
  if (Array.isArray(projected)) {
    // The detail projection is authoritative and already limited to this viewer.
    pendingInquiryIds.value = projected
      .map((inquiry) => String(inquiry.inquiry_action_id ?? "").trim())
      .filter((id) => id !== "");
    return;
  }
  const pages: TodoItem[][] = [];
  try {
    for (let page = 1; page <= INQUIRY_MAX_PAGES; page += 1) {
      const todos = await listMyTodos({
        kind: "inquiry_response",
        page,
        page_size: INQUIRY_PAGE_SIZE,
      });
      if (request !== inquiryRequest || detail.data.value?.case_id !== caseId) return;
      pages.push(todos.items);
      const found = inquiryIdsForCase(pages, caseId).length > 0;
      if (
        !shouldLoadNextPage({
          found,
          pagesRead: page,
          pageSize: INQUIRY_PAGE_SIZE,
          total: todos.total,
          maxPages: INQUIRY_MAX_PAGES,
        })
      ) {
        break;
      }
    }
    if (request !== inquiryRequest) return;
    pendingInquiryIds.value = inquiryIdsForCase(pages, caseId);
  } catch {
    // The todo projection is an auxiliary entry point; a failure must not hide the case.
    if (request === inquiryRequest) pendingInquiryIds.value = [];
  }
}

async function load(): Promise<void> {
  await detail.run();
  if (!isReporterView.value) {
    await loadThread();
    await loadPendingInquiries();
  }
}

onMounted(() => {
  // A one second tick is enough to hide the appeal entry at its deadline.
  clockTimer = setInterval(() => {
    clock.value = Date.now();
  }, 1000);
  void load();
});

onUnmounted(() => {
  cancelThread();
  if (clockTimer !== null) {
    clearInterval(clockTimer);
    clockTimer = null;
  }
});

watch(caseId, () => {
  supplementDialog.value?.close();
  supplementNote.value = "";
  supplementFiles.value = [];
  supplementError.value = null;
  cancelThread();
  void load();
});

watch(anchorMessageId, (anchor) => {
  if (
    anchor &&
    detail.data.value?.case_id === caseId.value &&
    !threadMessages.value.some((message) => message.case_message_id === anchor)
  ) {
    void loadThread();
  }
});

watch([anchorMessageId, threadStatus], async ([anchor, status]) => {
  if (!anchor || status !== "ready") return;
  await nextTick();
  if (anchor === anchorMessageId.value && detail.data.value?.case_id === caseId.value) {
    document.getElementById(`case-message-${anchor}`)?.scrollIntoView({ block: "start" });
  }
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
  if (!current || !thread || !actionId || !canRespond.value || replyPending.value) return;
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
  if (!current || !thread || !canAppeal.value || appealPending.value) return;
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
  if (!current || !canSupplement.value || supplementPending.value) return;
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
    if (current.case_id !== caseId.value) return;
    supplementNote.value = "";
    supplementFiles.value = [];
    supplementDialog.value?.close();
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
        :description="pageDescription"
      >
        <template #actions>
          <RouterLink to="/me/cases" class="btn btn--ghost">返回事项列表</RouterLink>
        </template>
      </PageHeader>

      <section class="card case-summary">
        <div class="case-summary__top">
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
            <span class="chip">{{ caseTypeLabel }}</span>
            <span v-if="detail.data.value.decision_kind" class="chip chip--active">
              {{ caseDecisionLabels[detail.data.value.decision_kind] }}
            </span>
          </div>

          <button
            v-if="canSupplement"
            type="button"
            class="btn btn--small btn--ghost supplement-toggle"
            aria-haspopup="dialog"
            aria-controls="case-supplement"
            :aria-expanded="supplementOpen"
            @click="toggleSupplement"
          >
            补充材料
          </button>
        </div>

        <div v-if="detail.data.value.reason_text" class="summary-copy">
          <span class="field__label">处理说明</span>
          <p class="reason pre-line break-anywhere">{{ detail.data.value.reason_text }}</p>
        </div>

        <p v-if="appealDeadline" class="banner banner--warn">
          申辩截止：{{ formatDateTime(appealDeadline) }}
          <template v-if="appealOpen"> · 剩余 {{ formatRemaining(appealRemaining) }}</template>
          <template v-else>· 申辩期已结束</template>
        </p>

        <div v-if="detail.data.value.enforcements.length" class="summary-enforcements">
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

      <section v-if="isReporterView" class="card materials-card">
        <div class="card__head">
          <div>
            <p class="section-kicker">举报记录</p>
            <h2>我的举报材料</h2>
          </div>
          <span class="chip">
            {{ reportMaterials?.supplements.length ?? 0 }} 次补充 ·
            {{ reportMaterials?.attachments.length ?? 0 }} 个附件
          </span>
        </div>

        <div class="material-overview">
          <section
            v-if="detail.data.value.reported_reason || reportMaterials?.original_note"
            class="material-block"
          >
            <h3>举报说明</h3>
            <p
              v-if="detail.data.value.reported_reason"
              class="pre-line break-anywhere material-copy"
            >
              {{ detail.data.value.reported_reason }}
            </p>
            <p v-if="reportMaterials?.original_note" class="pre-line break-anywhere">
              {{ reportMaterials.original_note }}
            </p>
          </section>

          <section v-if="reportMaterials?.product" class="material-block">
            <div class="section-heading">
              <h3>关联商品快照</h3>
              <span class="muted">举报提交时</span>
            </div>
            <dl class="case-fields">
              <dt>商品名称</dt>
              <dd>{{ reportMaterials.product.title || "未填写" }}</dd>
              <dt>商品编号</dt>
              <dd>#{{ reportMaterials.product.id }}</dd>
              <dt>商品简介</dt>
              <dd class="pre-line">{{ reportMaterials.product.description || "未填写" }}</dd>
            </dl>
            <RouterLink
              class="text-link"
              :to="{ name: 'product-detail', params: { productId: reportMaterials.product.id } }"
            >
              查看当前商品页
            </RouterLink>
          </section>
        </div>

        <div class="material-streams">
          <section v-if="reportMaterials?.supplements.length" class="material-block">
            <div class="section-heading">
              <h3>补充说明</h3>
              <span class="muted">{{ reportMaterials.supplements.length }} 条</span>
            </div>
            <ol class="note-list">
              <li
                v-for="item in reportMaterials.supplements"
                :key="item.action_id"
                class="note-item"
              >
                <div class="record-meta">
                  <span class="record-type">补充说明</span>
                  <time :datetime="item.occurred_at">{{ formatDateTime(item.occurred_at) }}</time>
                </div>
                <p class="pre-line break-anywhere">{{ item.note }}</p>
              </li>
            </ol>
          </section>

          <section v-if="reportMaterials?.attachments.length" class="material-block">
            <div class="section-heading">
              <h3>附件</h3>
              <span class="muted">{{ reportMaterials.attachments.length }} 项</span>
            </div>
            <ul class="attachment-list">
              <li v-for="item in reportMaterials.attachments" :key="item.evidence_id">
                <div class="record-meta">
                  <span class="record-type">{{ attachmentKindLabel(item.content_type) }}</span>
                  <span class="mono">证据 #{{ item.evidence_id }}</span>
                  <time :datetime="item.submitted_at"
                    >提交于 {{ formatDateTime(item.submitted_at) }}</time
                  >
                </div>
                <img
                  v-if="item.content_type?.startsWith('image/')"
                  :src="`/api/v1/cases/${caseId}/evidence/${item.evidence_id}/file`"
                  :alt="`已提交的图片 #${item.evidence_id}`"
                  class="evidence-image"
                  width="640"
                  height="480"
                  loading="lazy"
                  decoding="async"
                />
                <a
                  v-else
                  class="evidence-link"
                  :href="`/api/v1/cases/${caseId}/evidence/${item.evidence_id}/file`"
                  target="_blank"
                  rel="noopener noreferrer"
                  :aria-label="`在新标签页打开${attachmentKindLabel(item.content_type)} #${item.evidence_id}`"
                >
                  <span class="file-link">
                    <span class="file-type">{{ attachmentKindLabel(item.content_type) }}</span>
                    <span>{{
                      item.content_type === "application/pdf" ? "在浏览器中查看 PDF" : "查看附件"
                    }}</span>
                  </span>
                </a>
              </li>
            </ul>
          </section>
        </div>
      </section>

      <section class="card progress-card">
        <div class="card__head">
          <div>
            <p class="section-kicker">处理轨迹</p>
            <h2>进度</h2>
          </div>
          <span class="chip">{{ detail.data.value.actions.length }} 条</span>
        </div>
        <ol class="timeline">
          <li v-for="(action, index) in detail.data.value.actions" :key="index">
            <span class="timeline__dot" aria-hidden="true" />
            <span class="timeline__body">
              <strong>{{ caseActionKindText(action.action_kind) }}</strong>
              <span class="muted">
                {{ formatDateTime(action.occurred_at) }} ·
                {{ caseActorKindText(action.actor_kind) }}
              </span>
            </span>
          </li>
          <li v-if="!detail.data.value.actions.length" class="muted">暂无进度记录。</li>
        </ol>
      </section>

      <section v-if="!isReporterView" class="card">
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
            :id="`case-message-${message.case_message_id}`"
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
          <div v-if="canRespond" class="stack stack--tight">
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

          <template v-if="canAppeal">
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

          <p v-if="!canRespond && !canAppeal" class="muted">
            当前没有需要回复的问询或可提交的申辩。
          </p>
        </template>
      </section>

      <!--
        Reporter-only entry: shown when the server projects the reporter viewpoint, or
        is taken from the list scope. Without it the entry stays hidden and the page
        says how to reach it instead of guessing.
      -->
      <p
        v-if="
          !availability.projected &&
          !detail.data.value.viewpoint &&
          !archived &&
          detail.data.value.case_type === 'report' &&
          !isReporterView
        "
        class="banner banner--info"
      >
        从「我的事项 → 我提交的」打开本事项，才能补充说明与证据。
      </p>

      <dialog
        v-if="canSupplement"
        id="case-supplement"
        ref="supplementDialog"
        class="card supplement-dialog"
        aria-labelledby="case-supplement-title"
        @close="supplementOpen = false"
        @cancel="supplementPending && $event.preventDefault()"
      >
        <form class="stack" @submit.prevent="submitSupplement">
          <h2 id="case-supplement-title">补充材料</h2>
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
            :target="null"
          />
          <p v-if="supplementError" class="field__error" role="alert">{{ supplementError }}</p>
          <div class="inline">
            <button
              type="button"
              class="btn btn--ghost"
              :disabled="supplementPending"
              @click="toggleSupplement"
            >
              关闭
            </button>
            <button type="submit" class="btn btn--primary" :disabled="supplementPending">
              {{ supplementPending ? "提交中…" : "提交补充" }}
            </button>
          </div>
        </form>
      </dialog>
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

.case-summary {
  display: grid;
  gap: var(--space-3);
}

.case-summary__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.case-summary__top > .inline {
  flex: 1 1 20rem;
}

.summary-copy,
.summary-enforcements {
  padding-block-start: var(--space-3);
  border-block-start: 1px solid var(--line);
}

.summary-copy {
  display: grid;
  gap: var(--space-1);
}

.materials-card {
  display: grid;
  gap: var(--space-4);
}

.material-overview,
.material-streams {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
  gap: var(--space-3);
  align-items: start;
}

.material-block {
  min-inline-size: 0;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: linear-gradient(180deg, #fff, #fbfcfb);
}

.material-block h3,
.material-block > h3 {
  margin: 0;
  font-size: 0.875rem;
}

.material-copy {
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

.case-fields {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--space-1) var(--space-3);
  margin: 0;
  font-size: 0.8125rem;
}

.case-fields dt {
  color: var(--ink-soft);
  font-weight: 650;
}

.case-fields dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.text-link {
  display: inline-flex;
  margin-block-start: var(--space-2);
  color: var(--info);
  font-size: 0.8125rem;
}

.note-list,
.attachment-list,
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
}

.note-list,
.attachment-list {
  display: grid;
  gap: var(--space-2);
}

.note-item,
.attachment-list > li {
  min-inline-size: 0;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: #fbfcfb;
}

.note-item > p {
  margin-block-start: var(--space-2);
  font-size: 0.875rem;
}

.record-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.record-meta time {
  color: var(--ink-faint);
  font-size: 0.75rem;
}

.record-type,
.file-type {
  display: inline-flex;
  align-items: center;
  border: 1px solid #cad9eb;
  border-radius: 999px;
  padding: 0.06rem 0.48rem;
  color: var(--info);
  background: var(--info-soft);
  font-size: 0.7rem;
  font-weight: 650;
}

.evidence-link {
  display: block;
  margin-block-start: var(--space-2);
  color: inherit;
  text-decoration: none;
}

.file-link {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--control-line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  font-size: 0.8125rem;
}

.evidence-image {
  display: block;
  inline-size: min(100%, 32rem);
  block-size: auto;
  max-inline-size: min(100%, 32rem);
  max-block-size: 24rem;
  aspect-ratio: 4 / 3;
  object-fit: contain;
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
}

.supplement-toggle {
  flex: 0 0 auto;
  align-self: flex-start;
}

.supplement-dialog {
  position: fixed;
  inset: 0;
  margin: auto;
  width: min(36rem, calc(100% - 2rem));
  max-height: calc(100dvh - 2rem);
  overflow: auto;
  color: inherit;
}

.supplement-dialog::backdrop {
  background: rgb(0 0 0 / 38%);
}

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
  gap: 0;
}

.timeline li {
  position: relative;
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
  padding-block: var(--space-2);
}

.timeline li:not(:last-child)::before {
  position: absolute;
  inset-block: 1.15rem calc(-0.1rem);
  inset-inline-start: 0.22rem;
  inline-size: 1px;
  background: var(--line);
  content: "";
}

.timeline__dot {
  position: relative;
  z-index: 1;
  inline-size: 0.5rem;
  block-size: 0.5rem;
  margin-block-start: 0.42rem;
  border: 2px solid var(--panel);
  border-radius: 50%;
  background: var(--brand);
  flex: 0 0 auto;
  box-shadow: 0 0 0 1px var(--brand);
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
  scroll-margin-block-start: 5rem;
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
