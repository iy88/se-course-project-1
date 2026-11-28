<script setup lang="ts">
/* The page retains drafts and in-flight state while this component owns the modal interaction. */
import { ref, toRefs } from "vue";
import { supplementReport } from "../../api/cases";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { useToastStore } from "../../app/toast";
import ImageUploader from "../../components/ImageUploader.vue";

const { notify } = useToastStore();

type SupplementState = { note: string; files: string[]; pending: boolean; error: string | null };

const props = defineProps<{
  /** Case projected by the detail payload, which is also the write target. */
  caseId: string;
  /** Only the active case and draft may trigger page effects after a write. */
  isCurrent: (caseId: string, state: SupplementState) => boolean;
  state: SupplementState;
  /** Reloads the page detail after a successful supplement. */
  reload: () => Promise<void>;
  canSupplement: boolean;
}>();

const emit = defineEmits<{ "update:open": [value: boolean] }>();

const dialog = ref<HTMLDialogElement | null>(null);
const state = props.state;
const { note, files, pending, error } = toRefs(state);

function toggle(): void {
  const element = dialog.value;
  if (!element) return;
  if (element.open) {
    element.close();
  } else {
    element.showModal();
    emit("update:open", true);
  }
}

function onClose(): void {
  emit("update:open", false);
}

function onCancel(event: Event): void {
  if (pending.value) event.preventDefault();
}

function close(): void {
  dialog.value?.close();
}

async function submit(): Promise<void> {
  if (!props.canSupplement || pending.value) return;
  if (!note.value.trim() && !files.value.length) {
    error.value = "请填写补充说明或上传证据。";
    return;
  }
  const requestCaseId = props.caseId;
  error.value = null;
  pending.value = true;
  try {
    const result = await supplementReport(
      requestCaseId,
      {
        note: note.value.trim() || undefined,
        attachments: files.value.map((fileId) => ({ file_id: fileId })),
      },
      newIdempotencyKey(),
    );
    if (!props.isCurrent(requestCaseId, state)) return;
    note.value = "";
    files.value = [];
    dialog.value?.close();
    notify.success(`已补充材料（第 ${result.supplement_count} 次）。`);
    await props.reload();
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    pending.value = false;
  }
}

defineExpose({ toggle, close });
</script>

<template>
  <dialog
    id="case-supplement"
    ref="dialog"
    class="card supplement-dialog"
    aria-labelledby="case-supplement-title"
    @close="onClose"
    @cancel="onCancel"
  >
    <form class="stack" @submit.prevent="submit">
      <h2 id="case-supplement-title">补充材料</h2>
      <div class="field">
        <label class="field__label" for="supplement-note">补充说明</label>
        <textarea id="supplement-note" v-model="note" class="textarea" maxlength="1000" />
      </div>
      <ImageUploader
        v-model="files"
        purpose="case_evidence"
        label="证据文件"
        hint="支持 JPG、PNG、PDF"
        :max-count="5"
        :target="null"
      />
      <p v-if="error" class="field__error" role="alert">{{ error }}</p>
      <div class="inline">
        <button type="button" class="btn btn--ghost" :disabled="pending" @click="toggle">
          关闭
        </button>
        <button type="submit" class="btn btn--primary" :disabled="pending">
          {{ pending ? "提交中…" : "提交补充" }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
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
</style>
