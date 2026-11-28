<script setup lang="ts">
import { caseEvidenceFileHref } from "../api/cases";
import { formatDateTime } from "../app/format";
import type { DecisionDraft, DispositionChoice, EnforcementOption } from "./useCaseDecision";

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

defineProps<{
  caseId: string;
  ids: string;
  draft: DecisionDraft;
  basisActions?: CaseBasisAction[];
  basisEvidence: CaseBasisEvidence[];
  messages: Record<string, string>;
  enforcementOptions: readonly EnforcementOption[];
  dispositionChoices: DispositionChoice[][];
  writing: boolean;
}>();

const emit = defineEmits<{
  submit: [];
  "add-instruction": [];
  "remove-instruction": [id: number];
}>();
</script>

<template>
  <form class="card stack" :aria-labelledby="`${ids}-decide`" @submit.prevent="emit('submit')">
    <h2 :id="`${ids}-decide`">处置决定</h2>
    <label class="field"
      ><span>结论</span>
      <select v-model="draft.decisionKind" name="decision_kind" class="select" required>
        <option value="no_action">不予处置</option>
        <option value="not_actionable">不予受理</option>
        <option value="violation">认定违规</option>
      </select>
    </label>
    <label class="field"
      ><span>决定理由</span>
      <textarea v-model="draft.decisionReason" name="reason" class="textarea" required />
    </label>
    <fieldset class="stack">
      <legend>补充依据（可选）</legend>
      <p v-if="!basisActions?.length && !basisEvidence.length" class="muted">
        暂无可引用的问询、回复或用户材料。
      </p>
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
          >打开附件</a
        >
      </div>
    </fieldset>
    <template v-if="draft.decisionKind === 'violation'">
      <fieldset v-for="instruction in draft.instructions" :key="instruction.id" class="stack">
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
          <select v-model="instruction.expected" :name="`state-${instruction.id}`" class="select">
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
            @click="emit('remove-instruction', instruction.id)"
          >
            移除此项
          </button>
        </div>
      </fieldset>
      <div v-if="dispositionChoices.some((choices) => choices.length)">
        <button type="button" class="btn" @click="emit('add-instruction')">添加处置项</button>
      </div>
    </template>
    <div>
      <button type="submit" class="btn btn--primary" :disabled="writing">提交决定</button>
    </div>
  </form>
</template>

<style scoped>
/* Keep the moved decision fieldsets visually aligned with the page's other forms. */
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
