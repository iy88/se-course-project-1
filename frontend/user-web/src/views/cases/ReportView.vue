<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { submitReport } from "../../api/cases";
import type { ReportTarget, ReportTargetType } from "../../api/contracts";
import { newIdempotencyKey } from "../../app/keys";
import { rememberCaseScope } from "../../app/case-directory";
import { problemMessage } from "../../app/problems";
import { useToastStore } from "../../app/toast";
import { refreshBadges } from "../../app/badges";
import ImageUploader from "../../components/ImageUploader.vue";
import PageHeader from "../../components/PageHeader.vue";

const { notify } = useToastStore();

const route = useRoute();
const router = useRouter();

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

const resourceId = /^[1-9][0-9]*$/;
const target = computed<ReportTarget | null>(() => {
  const { target_type, target_id, conversation_kind, conversation_id } = route.query;
  const type = targetTypes.find((option) => option.value === target_type)?.value;
  if (!type || typeof target_id !== "string" || !resourceId.test(target_id)) return null;

  if (type !== "message") {
    const source = route.query.source_product_id;
    return {
      target_type: type,
      target_id,
      source_product_id:
        type === "account" && typeof source === "string" && resourceId.test(source)
          ? source
          : undefined,
    };
  }
  if (
    (conversation_kind !== "chat" && conversation_kind !== "trade") ||
    typeof conversation_id !== "string" ||
    !resourceId.test(conversation_id)
  )
    return null;

  return { target_type: type, target_id, conversation_kind, conversation_id };
});

const targetLabel = computed(
  () => targetTypes.find((option) => option.value === target.value?.target_type)?.label,
);

watch(
  () => route.fullPath,
  () => {
    reason.value = "";
    note.value = "";
    files.value = [];
    error.value = null;
  },
);

async function submit(): Promise<void> {
  const reportTarget = target.value;
  if (pending.value || !reportTarget) return;
  error.value = null;
  if (!reason.value.trim()) {
    error.value = "请填写举报理由。";
    return;
  }
  pending.value = true;
  try {
    const result = await submitReport(
      {
        target: reportTarget,
        reason: reason.value.trim(),
        note: note.value.trim() || undefined,
        attachments: files.value.map((fileId) => ({ file_id: fileId })),
      },
      newIdempotencyKey(),
    );
    rememberCaseScope(result.case_id, "mine");
    void refreshBadges();
    notify.success(
      result.reused ? "该对象已有未结的举报，本次内容已作为补充记录。" : "举报已提交。",
    );
    if (target.value === reportTarget) {
      await router.push({ name: "case-detail", params: { caseId: result.case_id } });
    }
  } catch (caught) {
    if (target.value === reportTarget) error.value = problemMessage(caught);
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader eyebrow="事项" title="提交举报">
      <template #actions>
        <RouterLink to="/me/cases" class="btn btn--ghost">我的事项</RouterLink>
      </template>
    </PageHeader>

    <p v-if="!target" class="banner banner--info">
      请从商品、评论、评价、消息或商品卖方旁的举报入口发起。
    </p>
    <form v-else class="stack" @submit.prevent="submit">
      <p class="muted break-anywhere">
        举报对象 · {{ targetLabel }} #{{ target.target_id }}
        <template v-if="target.target_type === 'message'">
          · {{ target.conversation_kind === "chat" ? "私聊" : "交易会话" }} #{{
            target.conversation_id
          }}
        </template>
      </p>

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
