<script setup lang="ts">
import { computed, toRefs } from "vue";
import {
  caseEvidenceFileHref,
  citeReportedMessage,
  readCaseMessageEvidence,
  type CaseMessageEvidence,
  type ReportedMessageReference,
} from "../api/cases";
import { formatDateTime } from "../app/format";
import type { IdempotencyKeys } from "../app/keys";
import { problemMessage } from "../app/problems";

interface CaseEvidence {
  evidence_id: string;
  evidence_kind?: "submitter_attachment" | "platform_record";
  file_id: string | null;
  decision_basis?: boolean;
  submitted_at?: string;
  content_type?: string;
}

interface CaseSubmittedNote {
  action_id: string;
  action_kind: string;
  occurred_at: string;
  note: string | null;
}

const props = withDefaults(
  defineProps<{
    caseId: string;
    submittedNotes?: CaseSubmittedNote[];
    evidence?: CaseEvidence[];
    reportedMessage?: ReportedMessageReference;
    archivedAt?: string | null;
    // The parent owns the detail request and resolves after its reload completes.
    refresh: () => Promise<void>;
    keys: IdempotencyKeys;
    state: {
      messageEvidence: CaseMessageEvidence | undefined;
      evidenceLoading: boolean;
      evidenceError: string;
    };
  }>(),
  { submittedNotes: () => [], evidence: () => [], archivedAt: null },
);

const { messageEvidence, evidenceLoading, evidenceError } = toRefs(props.state);

const visible = computed(
  () =>
    props.submittedNotes.length > 0 ||
    props.evidence.length > 0 ||
    Boolean(props.reportedMessage && !props.archivedAt),
);
const canCite = computed(
  () =>
    Boolean(props.reportedMessage) &&
    !props.archivedAt &&
    !props.evidence.some((item) => item.evidence_kind === "platform_record"),
);

function attachmentKindLabel(contentType?: string): string {
  if (contentType === "application/pdf") return "PDF 附件";
  if (contentType?.startsWith("image/")) return "图片附件";
  return "附件";
}

async function openMessageEvidence(evidenceId: string): Promise<void> {
  evidenceError.value = "";
  messageEvidence.value = undefined;
  evidenceLoading.value = true;
  try {
    messageEvidence.value = await readCaseMessageEvidence(props.caseId, evidenceId);
  } catch (caught) {
    evidenceError.value = problemMessage(caught);
  } finally {
    evidenceLoading.value = false;
  }
}

async function citeMessage(): Promise<void> {
  const reference = props.reportedMessage;
  if (!reference || evidenceLoading.value) return;
  evidenceError.value = "";
  evidenceLoading.value = true;
  const key = "case-evidence";
  try {
    const result = await citeReportedMessage(props.caseId, reference, props.keys.current(key));
    props.keys.rotate(key);
    await props.refresh();
    await openMessageEvidence(result.evidence_id);
  } catch (caught) {
    evidenceError.value = problemMessage(caught);
  } finally {
    evidenceLoading.value = false;
  }
}
</script>

<template>
  <section v-if="visible" class="card record-card">
    <div class="card__head">
      <div>
        <p class="section-kicker">材料与依据</p>
        <h2>补充材料与证据</h2>
      </div>
      <button
        v-if="canCite"
        type="button"
        class="btn btn--small btn--ghost"
        :disabled="evidenceLoading"
        @click="citeMessage"
      >
        引用被举报消息
      </button>
    </div>

    <section v-if="submittedNotes.length" class="record-section">
      <div class="section-heading">
        <h3>举报人补充说明</h3>
        <span class="muted">{{ submittedNotes.length }} 条</span>
      </div>
      <ol class="note-list">
        <li
          v-for="item in submittedNotes"
          :id="`case-supplement-${item.action_id}`"
          :key="item.action_id"
          class="note-item"
        >
          <div class="record-meta">
            <span class="record-type">补充说明</span>
            <time :datetime="item.occurred_at">{{ formatDateTime(item.occurred_at) }}</time>
          </div>
          <p class="pre-line">{{ item.note }}</p>
        </li>
      </ol>
    </section>

    <section v-if="evidence.length" class="record-section">
      <div class="section-heading">
        <h3>证据与附件</h3>
        <span class="muted">{{ evidence.length }} 项</span>
      </div>
      <ul class="evidence-list">
        <li
          v-for="item in evidence"
          :id="`case-evidence-${item.evidence_id}`"
          :key="item.evidence_id"
          class="evidence-item"
        >
          <div class="record-meta">
            <span class="record-type">
              {{
                item.evidence_kind === "platform_record"
                  ? "平台记录"
                  : attachmentKindLabel(item.content_type)
              }}
            </span>
            <span class="mono">证据 #{{ item.evidence_id }}</span>
            <time v-if="item.submitted_at" :datetime="item.submitted_at">
              {{ item.file_id ? "提交于" : "引用于" }}
              {{ formatDateTime(item.submitted_at) }}
            </time>
          </div>
          <img
            v-if="item.file_id && item.content_type?.startsWith('image/')"
            :src="caseEvidenceFileHref(caseId, item.evidence_id)"
            :alt="`证据图片 #${item.evidence_id}`"
            class="evidence-image"
            width="640"
            height="480"
            loading="lazy"
            decoding="async"
          />
          <a
            v-else-if="item.file_id"
            class="evidence-link"
            :href="caseEvidenceFileHref(caseId, item.evidence_id)"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="`在新标签页打开${attachmentKindLabel(item.content_type)} #${item.evidence_id}`"
          >
            <span class="file-link">
              <span class="file-type">{{ attachmentKindLabel(item.content_type) }}</span>
              <span>
                {{ item.content_type === "application/pdf" ? "在浏览器中查看 PDF" : "查看附件" }}
              </span>
            </span>
          </a>
          <button
            v-else-if="item.evidence_kind === 'platform_record'"
            type="button"
            class="btn btn--small"
            :disabled="evidenceLoading"
            @click="openMessageEvidence(item.evidence_id)"
          >
            读取引用消息
          </button>
        </li>
      </ul>
    </section>

    <p v-if="evidenceError" class="field__error" role="alert">{{ evidenceError }}</p>
    <div v-if="messageEvidence" class="quoted-message">
      <div class="record-meta">
        <span class="record-type">被举报消息</span>
        <span class="mono">#{{ messageEvidence.message.message_id }}</span>
        <time :datetime="messageEvidence.message.created_at">{{
          formatDateTime(messageEvidence.message.created_at)
        }}</time>
      </div>
      <p class="pre-line">{{ messageEvidence.message.body }}</p>
    </div>
  </section>
</template>

<style scoped>
.section-kicker {
  margin: 0;
  color: var(--info);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-block-end: var(--space-2);
}

.record-section h3 {
  margin: 0;
  font-size: 0.875rem;
}

.record-card {
  min-inline-size: 0;
}

.record-section + .record-section {
  margin-block-start: var(--space-4);
  padding-block-start: var(--space-4);
  border-block-start: 1px solid var(--line);
}

.note-list,
.evidence-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-2);
}

.note-item,
.evidence-item,
.quoted-message {
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: #fbfcfb;
}

.note-item > p,
.quoted-message > p {
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

.evidence-image {
  margin-block-start: var(--space-2);
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

.quoted-message {
  margin-block-start: var(--space-3);
  border-inline-start: 3px solid var(--info);
}

.pre-line {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
