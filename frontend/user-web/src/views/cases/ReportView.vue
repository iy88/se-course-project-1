<script setup lang="ts">
/*
 * Report submission (US-07, US-08).
 *
 * The target usually arrives from the object being reported (product, comment,
 * message, evaluation, account). When the page is opened directly the user must
 * name the target explicitly, so the same form covers both entry points.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { submitReport } from "../../api/cases";
import type { ConversationKind, ReportTarget, ReportTargetType } from "../../api/contracts";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { notify } from "../../app/toast";
import { refreshBadges } from "../../app/badges";
import ImageUploader from "../../components/ImageUploader.vue";
import PageHeader from "../../components/PageHeader.vue";

const route = useRoute();
const router = useRouter();

const targetType = ref<ReportTargetType>("product");
const targetId = ref("");
const conversationKind = ref<ConversationKind | "">("");
const conversationId = ref("");
const reason = ref("");
const note = ref("");
const files = ref<string[]>([]);
const pending = ref(false);
const error = ref<string | null>(null);

const targetTypes: { value: ReportTargetType; label: string }[] = [
  { value: "product", label: "商品" },
  { value: "comment", label: "评论" },
  { value: "message", label: "消息" },
  { value: "evaluation", label: "评价" },
  { value: "account", label: "账户" },
];

const needsConversation = computed(() => targetType.value === "message");
const targetReady = computed(
  () =>
    targetId.value.trim() !== "" &&
    (!needsConversation.value ||
      (conversationKind.value !== "" && conversationId.value.trim() !== "")),
);

onMounted(() => {
  const query = route.query;
  if (typeof query.target_type === "string" && query.target_type !== "") {
    targetType.value = query.target_type as ReportTargetType;
  }
  if (typeof query.target_id === "string") targetId.value = query.target_id;
  if (typeof query.conversation_kind === "string") {
    conversationKind.value = query.conversation_kind as ConversationKind;
  }
  if (typeof query.conversation_id === "string") conversationId.value = query.conversation_id;
});

function buildTarget(): ReportTarget | null {
  if (!targetReady.value) return null;
  const target: ReportTarget = {
    target_type: targetType.value,
    target_id: targetId.value.trim(),
  };
  if (needsConversation.value && conversationKind.value !== "") {
    target.conversation_kind = conversationKind.value;
    target.conversation_id = conversationId.value.trim();
  }
  return target;
}

async function submit(): Promise<void> {
  if (pending.value) return;
  error.value = null;
  if (!reason.value.trim()) {
    error.value = "请填写举报理由。";
    return;
  }
  const target = buildTarget();
  if (!target) {
    error.value = "请填写被举报对象。消息类举报还需指定所属会话。";
    return;
  }
  pending.value = true;
  try {
    const result = await submitReport(
      {
        target,
        reason: reason.value.trim(),
        note: note.value.trim() || undefined,
        attachments: files.value.map((fileId) => ({ file_id: fileId })),
      },
      newIdempotencyKey(),
    );
    void refreshBadges();
    notify.success(
      result.reused ? "该对象已有未结的举报，本次内容已作为补充记录。" : "举报已提交。",
    );
    await router.push({ name: "case-detail", params: { caseId: result.case_id } });
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="事项"
      title="提交举报"
      description="举报对象可以是商品、评论、消息、评价或账户；请尽量附上可核对的证据。"
    >
      <template #actions>
        <RouterLink to="/me/cases" class="btn btn--ghost">我的事项</RouterLink>
      </template>
    </PageHeader>

    <form class="stack stack--loose" @submit.prevent="submit">
      <section class="card stack">
        <div class="card__head"><h2>举报对象</h2></div>
        <div class="form-row">
          <div class="field">
            <label class="field__label" for="target-type">对象类型</label>
            <select id="target-type" v-model="targetType" class="select">
              <option v-for="option in targetTypes" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>
          <div class="field">
            <label class="field__label" for="target-id">对象标识</label>
            <input id="target-id" v-model="targetId" class="input" placeholder="例如 12" />
          </div>
        </div>
        <div v-if="needsConversation" class="form-row">
          <div class="field">
            <label class="field__label" for="conversation-kind">会话类型</label>
            <select id="conversation-kind" v-model="conversationKind" class="select">
              <option value="">请选择</option>
              <option value="chat">私聊</option>
              <option value="trade">交易会话</option>
            </select>
          </div>
          <div class="field">
            <label class="field__label" for="conversation-id">会话标识</label>
            <input id="conversation-id" v-model="conversationId" class="input" />
          </div>
        </div>
        <p class="muted">从商品页或消息页进入时，对象标识会自动填入；直接打开本页时请手动填写。</p>
      </section>

      <section class="card stack">
        <div class="card__head"><h2>举报内容</h2></div>
        <div class="field">
          <label class="field__label" for="report-reason">理由</label>
          <input id="report-reason" v-model="reason" class="input" maxlength="200" required />
          <span class="field__hint">简要说明涉及的禁发范围或违规类型</span>
        </div>
        <div class="field">
          <label class="field__label" for="report-note">补充说明（可选）</label>
          <textarea id="report-note" v-model="note" class="textarea" maxlength="2000" />
          <span class="field__hint">{{ note.length }}/2000</span>
        </div>
        <ImageUploader
          v-model="files"
          purpose="case_evidence"
          label="证据文件"
          hint="支持 JPG、PNG、PDF"
          :max-count="5"
          :target="null"
        />
      </section>

      <p v-if="error" class="banner banner--danger" role="alert">{{ error }}</p>

      <div class="inline">
        <button type="submit" class="btn btn--primary" :disabled="pending">
          {{ pending ? "正在提交…" : "提交举报" }}
        </button>
        <RouterLink to="/me/cases" class="btn btn--ghost">取消</RouterLink>
      </div>
      <p class="muted">
        举报不会立即改变被举报对象的状态；处理结果会通过站内通知告知，且公开结果不包含举报人身份。
      </p>
    </form>
  </div>
</template>
