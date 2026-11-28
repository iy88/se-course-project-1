<script setup lang="ts">
import {
  caseEvidenceFileHref,
  resolveCaseAppeal,
  type AppealableEnforcement,
  type CaseReplacementEnforcement,
  type PendingCaseAppeal,
} from "../api/cases";
import { formatDateTime } from "../app/format";
import type { IdempotencyKeys } from "../app/keys";
import { problemMessage } from "../app/problems";
import { useToastStore } from "../app/toast";
import type { AppealDraft, AppealDraftEntry } from "./useCaseAppeals";

interface EnforcementOption {
  action: string;
  target: string;
  label: string;
}

interface CaseBasisAction {
  action_id: string;
  action_kind: string;
  occurred_at: string;
  note: string | null;
}

interface CaseBasisEvidence {
  evidence_id: string;
  submitted_at?: string;
}

interface AppealWriteState {
  readonly writing: boolean;
  begin: () => boolean;
  end: () => void;
  setError: (message: string) => void;
}

const props = defineProps<{
  caseId: string;
  entries: AppealDraftEntry[];
  basisActions?: CaseBasisAction[];
  basisEvidence?: CaseBasisEvidence[];
  messages: Record<string, string>;
  enforcementOptions: readonly EnforcementOption[];
  keys: IdempotencyKeys;
  writeState: AppealWriteState;
  refresh: () => Promise<void>;
  reloadThread: (appeal: PendingCaseAppeal) => Promise<void>;
  removeAppeal: (appealActionId: string) => void;
}>();

const { notify } = useToastStore();

function selectedAppealEnforcement(
  appeal: PendingCaseAppeal,
  draft: AppealDraft,
): AppealableEnforcement | undefined {
  return appeal.original_enforcements?.find((item) => item.enforcement_id === draft.originalId);
}

function appealEnforcementLabel(item: AppealableEnforcement): string {
  return (
    props.enforcementOptions.find(
      (option) => option.action === item.action && option.target === item.target_type,
    )?.label ?? item.action
  );
}

function appealReplacementOptions(
  appeal: PendingCaseAppeal,
  draft: AppealDraft,
): EnforcementOption[] {
  const original = selectedAppealEnforcement(appeal, draft);
  if (!original) return [];
  const liftActions = new Set(["lift_account_restriction", "restore_display", "lift_trade_freeze"]);
  return props.enforcementOptions.filter(
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
  const option = props.enforcementOptions.find(
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
  if (props.writeState.writing) return;
  const resolution = draft.resolution;
  if (!resolution) {
    props.writeState.setError("请选择处理结果。");
    return;
  }
  if (resolution !== "uphold" && !draft.originalId) {
    props.writeState.setError("请选择要撤销或调整的原处置。");
    return;
  }
  const replacements = resolution === "adjust" ? appealReplacement(appeal, draft) : [];
  if (resolution === "adjust" && replacements.length === 0) {
    props.writeState.setError("请选择替代处置。");
    return;
  }
  const reply = draft.reply.trim();
  const basisRefs = draft.basis;
  if (!basisRefs.length) {
    props.writeState.setError("请选择依据引用。");
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
  if (!props.writeState.begin()) return;
  props.writeState.setError("");
  try {
    await resolveCaseAppeal(
      props.caseId,
      appeal,
      resolution,
      draft.originalId || null,
      replacements,
      reply,
      basisRefs,
      props.keys.current(key),
    );
    props.keys.rotate(key);
    props.removeAppeal(appeal.appeal_action_id);
    notify.success("已处理申辩。");
    await props.reloadThread(appeal);
    await props.refresh();
  } catch (caught) {
    props.writeState.setError(problemMessage(caught));
  } finally {
    props.writeState.end();
  }
}
</script>

<template>
  <section class="card stack">
    <h2>待处理申辩</h2>
    <form
      v-for="{ appeal, draft } in entries"
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
      <label v-if="draft.resolution === 'revoke' || draft.resolution === 'adjust'" class="field">
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
        <label v-for="item in basisActions" :key="item.action_id">
          <input v-model="draft.basis" type="checkbox" :value="`action:${item.action_id}`" />
          {{ messages[item.action_kind] }} · {{ formatDateTime(item.occurred_at) }}
          <span v-if="item.note" class="pre-line"> · {{ item.note }}</span>
        </label>
        <div v-for="item in basisEvidence" :key="item.evidence_id" class="inline">
          <label>
            <input v-model="draft.basis" type="checkbox" :value="`evidence:${item.evidence_id}`" />
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
        <button type="submit" class="btn btn--primary" :disabled="writeState.writing">
          提交处理
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
/* Keep the moved appeal fieldsets visually aligned with the page's other forms. */
fieldset {
  border: 1px solid var(--line);
  padding: var(--space-3);
  min-inline-size: 0;
}

.pre-line {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
