<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId } from "vue";
import {
  caseEvidenceFileHref,
  liftCaseEnforcement,
  readCase,
  readCaseThread,
  writeCase,
  upholdCaseAppeal,
  type CaseDecision,
  type CaseEnforcementInput,
  type CaseManagementWrites,
  type CaseThreadPage,
  type ManagementCaseDetail,
  type ManagementCaseThread,
  type PendingCaseAppeal,
} from "../api/cases";
import { AbortedError } from "../api/errors";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { decisionKindLabels, todoKindLabels } from "../app/labels";
import { problemMessage } from "../app/problems";
import { notify } from "../app/toast";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";

const props = defineProps<{ caseId: string; backHref: string }>();
const ids = useId();
const detail = ref<ManagementCaseDetail>();
const error = ref<unknown>();
const loading = ref(false);
const writing = ref(false);
const writeError = ref("");
const keys = new IdempotencyKeys();
let detailRequest: AbortController | undefined;

const selectedThread = ref<ManagementCaseThread>();
const thread = ref<CaseThreadPage>();
const threadError = ref<unknown>();
const threadLoading = ref(false);
let threadRequest: AbortController | undefined;

const peer = ref("");
const inquiry = ref("");
const decisionKind = ref<CaseDecision>("no_action");
const decisionReason = ref("");
const basis = ref("");
const publicSummary = ref("");
const publicReason = ref("");
const confirmClose = ref(false);
const appealDraft = ref<{ id: string; reply: string; basis: string }>();
const liftDraft = ref<{ enforcementId: string; reason: string }>();
const enforcementOptions = [
  { action: "restrict_account", target: "account", label: "封禁账户" },
  { action: "withdraw_public_access", target: "product", label: "撤销商品展示" },
  { action: "remove_content", target: "comment", label: "移除评论" },
  { action: "remove_content", target: "evaluation", label: "移除评价" },
  { action: "freeze_trade", target: "trade", label: "冻结交易" },
  { action: "adjust_trade_status", target: "trade", label: "结束交易" },
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
const actions = computed(() => new Set(detail.value?.available_actions ?? []));

async function load(): Promise<void> {
  detailRequest?.abort();
  const controller = new AbortController();
  detailRequest = controller;
  loading.value = true;
  error.value = undefined;
  try {
    const next = await readCase(props.caseId, controller.signal);
    if (detailRequest === controller) detail.value = next;
  } catch (caught) {
    if (detailRequest === controller && !(caught instanceof AbortedError)) {
      detail.value = undefined;
      error.value = caught;
    }
  } finally {
    if (detailRequest === controller) loading.value = false;
  }
}

async function loadThread(source: ManagementCaseThread, older = false): Promise<void> {
  threadRequest?.abort();
  const controller = new AbortController();
  threadRequest = controller;
  const previous = older ? thread.value : undefined;
  selectedThread.value = source;
  thread.value = previous;
  threadError.value = undefined;
  threadLoading.value = true;
  try {
    const next = await readCaseThread(
      source.conversation_id,
      previous?.next_before_seq ?? undefined,
      controller.signal,
    );
    if (threadRequest === controller) {
      thread.value = { ...next, items: [...next.items, ...(previous?.items ?? [])] };
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

async function uphold(appeal: PendingCaseAppeal): Promise<void> {
  const draft = appealDraft.value;
  if (writing.value || draft?.id !== appeal.appeal_action_id) return;
  const reply = draft.reply.trim();
  const basisRef = draft.basis.trim();
  const key = JSON.stringify(["uphold", appeal.appeal_action_id, reply, basisRef]);
  writing.value = true;
  writeError.value = "";
  try {
    await upholdCaseAppeal(props.caseId, appeal, reply, basisRef, keys.current(key));
    keys.rotate(key);
    appealDraft.value = undefined;
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
  const enforcements: CaseEnforcementInput[] =
    decisionKind.value === "violation"
      ? instructions.value.map((entry) => {
          const option = enforcementOptions[entry.option];
          return {
            action: option.action,
            target_type: option.target,
            target_id: entry.targetId.trim(),
            expected_result: option.action === "adjust_trade_status" ? entry.expected : undefined,
          };
        })
      : [];
  void submit("decisions", {
    decision_kind: decisionKind.value,
    reason: decisionReason.value.trim(),
    basis_refs: basis.value.split(/[\s,，]+/).filter(Boolean),
    enforcements,
  });
}

function addInstruction(): void {
  instructions.value.push({ id: ++instructionId, option: 0, targetId: "", expected: "terminated" });
}

onMounted(load);
onUnmounted(() => {
  detailRequest?.abort();
  threadRequest?.abort();
});
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader :title="`事项 #${caseId}`">
      <template #actions>
        <a :href="backHref" class="btn btn--ghost">返回事项工作台</a>
      </template>
    </PageHeader>
    <LoadingBlock v-if="loading && !detail" label="正在读取事项…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="load" />
    <template v-else-if="detail">
      <section class="card stack">
        <div class="spread">
          <h2>{{ todoKindLabels[detail.case_type] }}</h2>
          <span class="chip">{{ currentStatus }}</span>
        </div>
        <p v-if="detail.reported_reason" class="pre-line">{{ detail.reported_reason }}</p>
        <div v-if="detail.decision_kind" class="stack">
          <h3>{{ decisionKindLabels[detail.decision_kind] }}</h3>
          <p v-if="detail.reason_text" class="pre-line">{{ detail.reason_text }}</p>
          <p v-if="detail.archived_at">结案于 {{ formatDateTime(detail.archived_at) }}</p>
          <p v-if="detail.public_result_at">公开于 {{ formatDateTime(detail.public_result_at) }}</p>
        </div>
        <ul v-if="detail.enforcements.length" class="stack">
          <li
            v-for="item in detail.enforcements"
            :key="item.enforcement_id"
            class="stack stack--tight"
          >
            <div class="spread">
              <span>
                {{
                  enforcementOptions.find((option) => option.action === item.action)?.label ??
                  "处置"
                }}
                {{ item.result_status === "failed" ? "失败" : "已记录" }}
                <span v-if="item.current_state"> · {{ item.current_state }}</span>
              </span>
              <button
                v-if="item.can_lift"
                type="button"
                class="btn"
                @click="openLift(item.enforcement_id)"
              >
                解除处置
              </button>
            </div>
            <form
              v-if="item.can_lift && liftDraft?.enforcementId === item.enforcement_id"
              class="stack"
              :aria-labelledby="`${ids}-lift`"
              @submit.prevent="submitLift"
            >
              <h3 :id="`${ids}-lift`">解除处置</h3>
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
                <button type="button" class="btn" @click="cancelLift">取消</button>
                <button type="submit" class="btn btn--primary" :disabled="writing">确认解除</button>
              </div>
            </form>
          </li>
        </ul>
      </section>
      <section v-if="detail.evidence?.length" class="card stack">
        <h2>证据引用</h2>
        <ul>
          <li v-for="item in detail.evidence" :key="item.evidence_id">
            证据 #{{ item.evidence_id
            }}<template v-if="item.file_id"> · 文件 #{{ item.file_id }}</template>
            <a
              v-if="item.file_id"
              :href="caseEvidenceFileHref(caseId, item.evidence_id)"
              target="_blank"
              rel="noopener noreferrer"
              >打开证据</a
            >
          </li>
        </ul>
      </section>
      <section v-if="detail.actions.length" class="card stack">
        <h2>处理记录</h2>
        <ol>
          <li v-for="(item, index) in detail.actions" :key="index">
            {{ messages[item.action_kind] ?? "事项更新" }} · {{ formatDateTime(item.occurred_at) }}
          </li>
        </ol>
      </section>
      <section v-if="detail.threads?.length" class="card stack">
        <h2>事项会话</h2>
        <div class="inline">
          <button
            v-for="item in detail.threads"
            :key="item.conversation_id"
            type="button"
            class="btn"
            :aria-pressed="selectedThread?.conversation_id === item.conversation_id"
            @click="loadThread(item)"
          >
            账户 #{{ item.related_account_id }}
          </button>
        </div>
        <LoadingBlock v-if="threadLoading && !thread" label="正在读取会话…" />
        <ErrorNotice
          v-else-if="threadError"
          :error="threadError"
          @retry="selectedThread && loadThread(selectedThread, Boolean(thread))"
        />
        <template v-if="thread">
          <button
            v-if="
              thread.items.length >= 20 &&
              thread.next_before_seq &&
              thread.next_before_seq > 1 &&
              selectedThread
            "
            type="button"
            class="btn"
            :disabled="threadLoading"
            @click="loadThread(selectedThread, true)"
          >
            加载更早消息
          </button>
          <ol class="stack">
            <li v-for="message in thread.items" :key="message.case_message_id">
              <p>
                {{ message.sender.display_name }} · {{ messages[message.message_kind] ?? "消息" }} ·
                {{ formatDateTime(message.created_at) }}
              </p>
              <p class="pre-line">{{ message.body }}</p>
            </li>
          </ol>
        </template>
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
          ><span>相关账户编号</span>
          <input
            v-model="peer"
            name="peer_account_id"
            class="input"
            required
            inputmode="numeric"
            pattern="[1-9][0-9]*"
          />
        </label>
        <label class="field"
          ><span>问询内容</span>
          <textarea v-model="inquiry" name="scope_text" class="textarea" required />
        </label>
        <div>
          <button type="submit" class="btn btn--primary" :disabled="writing">发起问询</button>
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
        <label class="field"
          ><span>依据引用（多个用空格分隔，例如 evidence:12）</span>
          <input v-model="basis" name="basis_refs" class="input" required />
        </label>
        <template v-if="decisionKind === 'violation'">
          <fieldset v-for="instruction in instructions" :key="instruction.id" class="stack">
            <legend>处置项</legend>
            <label class="field"
              ><span>动作</span>
              <select
                v-model="instruction.option"
                :name="`action-${instruction.id}`"
                class="select"
              >
                <option v-for="(option, index) in enforcementOptions" :key="index" :value="index">
                  {{ option.label }}
                </option>
              </select>
            </label>
            <label class="field"
              ><span>目标编号</span>
              <input
                v-model="instruction.targetId"
                :name="`target-${instruction.id}`"
                class="input"
                required
                inputmode="numeric"
                pattern="[1-9][0-9]*"
              />
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
              </select>
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
          <div><button type="button" class="btn" @click="addInstruction">添加处置项</button></div>
        </template>
        <div>
          <button type="submit" class="btn btn--primary" :disabled="writing">提交决定</button>
        </div>
      </form>

      <section
        v-if="actions.has('resolve_appeal') && detail.pending_appeals?.length"
        class="card stack"
      >
        <h2>待处理申辩</h2>
        <div v-for="appeal in detail.pending_appeals" :key="appeal.appeal_action_id" class="stack">
          <div class="spread">
            <p>账户 #{{ appeal.related_account_id }} · {{ formatDateTime(appeal.submitted_at) }}</p>
            <button
              type="button"
              class="btn"
              @click="
                loadThread({ ...appeal.thread, related_account_id: appeal.related_account_id })
              "
            >
              查看申辩会话
            </button>
            <button
              v-if="appealDraft?.id !== appeal.appeal_action_id"
              type="button"
              class="btn"
              @click="appealDraft = { id: appeal.appeal_action_id, reply: '', basis: '' }"
            >
              维持原决定
            </button>
          </div>
          <form
            v-if="appealDraft?.id === appeal.appeal_action_id"
            class="stack"
            :aria-label="`处理申辩 #${appeal.appeal_action_id}`"
            @submit.prevent="uphold(appeal)"
          >
            <label class="field"
              ><span>回复内容</span>
              <textarea v-model="appealDraft.reply" name="reply" class="textarea" required />
            </label>
            <label class="field"
              ><span>依据引用</span>
              <input v-model="appealDraft.basis" name="basis_ref" class="input" required />
            </label>
            <div class="inline">
              <button type="button" class="btn" @click="appealDraft = undefined">取消</button>
              <button type="submit" class="btn btn--primary" :disabled="writing">确认维持</button>
            </div>
          </form>
        </div>
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
