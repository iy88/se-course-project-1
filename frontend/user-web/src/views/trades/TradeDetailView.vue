<script setup lang="ts">
/*
 * Trade detail and lifecycle actions (US-05, US-06).
 *
 * The action set is taken from `permissions.allowed_actions`; the screen never
 * derives eligibility from the status itself. Every write sends the version it
 * rendered with, so a change made on another device surfaces as a refresh request
 * instead of an accidental overwrite.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  acceptTrade,
  confirmDisputeResolution,
  decideCancellation,
  getTrade,
  openDispute,
  proposeCancellation,
  rejectTrade,
  submitCompletionConfirmation,
  withdrawTrade,
} from "../../api/trades";
import type { TradeView } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { formatCents, formatDateTime, formatRelative, formatRemaining } from "../../app/format";
import { IdempotencyKeys } from "../../app/keys";
import {
  agreementStatusLabels,
  tradeStageLabel,
  tradeStatusLabels,
  tradeStatusTones,
  tradeTerminalReasonLabel,
} from "../../app/labels";
import { session } from "../../app/session";
import { useToastStore } from "../../app/toast";
import { refreshBadges } from "../../app/badges";
import AvatarBadge from "../../components/AvatarBadge.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import StateBadge from "../../components/StateBadge.vue";
import StartChatButton from "../../components/interaction/StartChatButton.vue";
import TradeProductHistory from "../../components/interaction/TradeProductHistory.vue";
import TradeReviewSection from "../../components/interaction/TradeReviewSection.vue";
import TradeAgreementSection from "./TradeAgreementSection.vue";
import { useTradeAgreementDraft } from "./useTradeAgreementDraft";

const { notify } = useToastStore();

const route = useRoute();
const router = useRouter();
const tradeId = computed(() => String(route.params.tradeId ?? ""));
const trade = useAsyncData<TradeView>((signal) => getTrade(tradeId.value, signal, "state_history"));
const terminalReasonLabel = computed(() => {
  const detail = trade.data.value;
  return detail
    ? tradeTerminalReasonLabel(
        detail.terminal_reason,
        detail.confirmations.both_current,
        detail.state_history,
      )
    : null;
});
const keys = new IdempotencyKeys();
const agreementForm = useTradeAgreementDraft(trade.data);

const completionNote = ref("");
const cancelReason = ref("");
const disputeStatement = ref("");
const formError = ref<string | null>(null);

const allowed = computed(() => new Set(trade.data.value?.permissions.allowed_actions ?? []));
const isBuyer = computed(() => trade.data.value?.buyer.id === session.accountId.value);
const counterparty = computed(() => {
  const detail = trade.data.value;
  if (!detail) return null;
  return isBuyer.value ? detail.seller : detail.buyer;
});
const currentAgreement = computed(() => trade.data.value?.agreement.current ?? null);
const confirmations = computed(() => trade.data.value?.confirmations.current ?? []);
const selfConfirmed = computed(() =>
  confirmations.value.some((item) => item.confirmer_id === session.accountId.value),
);
const cancellation = computed(() => trade.data.value?.cancellation.pending ?? null);
const cancellationIsMine = computed(
  () => cancellation.value?.proposed_by === session.accountId.value,
);
const dispute = computed(() => trade.data.value?.dispute.open ?? null);
const waits = computed(() => trade.data.value?.wait ?? null);
const freeze = computed(() => trade.data.value?.freeze ?? null);

watch(tradeId, () => {
  void trade.run();
});

onMounted(() => {
  void trade.run();
});

async function refresh(): Promise<void> {
  await trade.run();
  void refreshBadges();
}

async function run(operation: string, task: () => Promise<void>): Promise<void> {
  await task();
  keys.rotate(operation);
  await refresh();
}

async function submitCompletion(): Promise<void> {
  const detail = trade.data.value;
  if (!detail) return;
  await run("completion", async () => {
    const result = await submitCompletionConfirmation(
      detail.id,
      { note: completionNote.value.trim() || undefined, expected_version: detail.version },
      keys.current("completion"),
    );
    completionNote.value = "";
    notify.success(
      result.trade.status === "completed"
        ? "双方均已确认，交易已完成。"
        : "完成确认已提交，等待对方确认。",
    );
  });
}

async function submitCancellation(): Promise<void> {
  const detail = trade.data.value;
  if (!detail) return;
  await run("cancellation", async () => {
    const result = await proposeCancellation(
      detail.id,
      { reason: cancelReason.value.trim() || undefined, expected_version: detail.version },
      keys.current("cancellation"),
    );
    cancelReason.value = "";
    notify.success(
      result.trade.status === "terminated" ? "交易已取消。" : "取消申请已提交，等待对方回应。",
    );
  });
}

async function respondToCancellation(decision: "accept" | "reject" | "withdraw"): Promise<void> {
  const detail = trade.data.value;
  const proposal = cancellation.value;
  if (!detail || !proposal) return;
  await run("decide-cancellation", async () => {
    await decideCancellation(
      detail.id,
      proposal.id,
      decision,
      detail.version,
      keys.current("decide-cancellation"),
    );
    notify.success(decision === "accept" ? "交易已取消。" : "已提交回应。");
  });
}

async function submitDispute(): Promise<void> {
  const detail = trade.data.value;
  if (!detail) return;
  if (!disputeStatement.value.trim()) {
    formError.value = "请填写争议说明。";
    return;
  }
  await run("dispute", async () => {
    await openDispute(
      detail.id,
      { statement: disputeStatement.value.trim(), expected_version: detail.version },
      keys.current("dispute"),
    );
    disputeStatement.value = "";
    notify.success("争议已提交，交易进入争议状态。");
  });
}

async function confirmResolution(): Promise<void> {
  const detail = trade.data.value;
  const current = dispute.value;
  if (!detail || !current) return;
  await run("dispute-resolution", async () => {
    await confirmDisputeResolution(
      detail.id,
      current.id,
      detail.version,
      keys.current("dispute-resolution"),
    );
    notify.success("已确认争议处理结果，交易恢复进行。");
  });
}

function openConversation(): void {
  const detail = trade.data.value;
  if (!detail?.trade_conversation_id) return;
  void router.push({
    name: "conversation",
    params: { kind: "trade", conversationId: detail.trade_conversation_id },
  });
}
</script>

<template>
  <div class="stack stack--loose">
    <LoadingBlock v-if="trade.isLoading.value && !trade.data.value" label="正在加载交易…" />
    <ErrorNotice v-else-if="trade.problem.value" :error="trade.error.value" @retry="refresh" />
    <template v-else-if="trade.data.value">
      <PageHeader
        eyebrow="交易"
        :title="trade.data.value.product.title ?? `交易 ${trade.data.value.id}`"
        :description="tradeStageLabel(trade.data.value.status, trade.data.value.phase)"
      >
        <template #actions>
          <RouterLink to="/me/trades" class="btn btn--ghost">返回交易列表</RouterLink>
          <button
            v-if="trade.data.value.trade_conversation_id"
            type="button"
            class="btn"
            @click="openConversation"
          >
            进入交易会话
          </button>
          <StartChatButton
            v-if="counterparty"
            :target-account-id="counterparty.id"
            :target-name="counterparty.display_name"
            variant="ghost"
          />
        </template>
      </PageHeader>

      <section class="card overview">
        <div class="overview__state">
          <StateBadge
            :label="tradeStatusLabels[trade.data.value.status]"
            :tone="tradeStatusTones[trade.data.value.status]"
          />
          <span v-if="terminalReasonLabel" class="muted">结束原因：{{ terminalReasonLabel }}</span>
        </div>
        <div class="parties">
          <div class="party">
            <AvatarBadge
              :display-name="trade.data.value.seller.display_name"
              :url="trade.data.value.seller.avatar_url"
              size="sm"
            />
            <span>卖家 {{ trade.data.value.seller.display_name }}</span>
          </div>
          <div class="party">
            <AvatarBadge
              :display-name="trade.data.value.buyer.display_name"
              :url="trade.data.value.buyer.avatar_url"
              size="sm"
            />
            <span>买家 {{ trade.data.value.buyer.display_name }}</span>
          </div>
          <span class="muted">创建于 {{ formatDateTime(trade.data.value.created_at) }}</span>
        </div>
        <p v-if="freeze?.active" class="banner banner--danger">
          交易已被冻结：{{ freeze.items.map((item) => item.reason).join("；") }}
        </p>
        <p v-if="waits?.active" class="banner banner--info">
          等待对方完成确认，剩余 {{ formatRemaining(waits.remaining_seconds) }}
          <template v-if="waits.deadline_at"
            >（截止 {{ formatDateTime(waits.deadline_at) }}）</template
          >
          <template v-if="waits.paused">，当前因处置暂停计时</template>
        </p>
      </section>

      <section v-if="trade.data.value.status === 'pending_acceptance'" class="card">
        <div class="card__head"><h2>购买请求</h2></div>
        <p class="muted">
          {{ trade.data.value.buyer.display_name }} 于
          {{ formatDateTime(trade.data.value.request.requested_at) }} 提交
        </p>
        <p v-if="trade.data.value.request.note" class="quote">
          “{{ trade.data.value.request.note }}”
        </p>
        <div class="inline">
          <template v-if="allowed.has('accept')">
            <button
              type="button"
              class="btn btn--primary"
              @click="
                async () => {
                  await run('accept', async () => {
                    await acceptTrade(
                      trade.data.value!.id,
                      trade.data.value!.version,
                      keys.current('accept'),
                    );
                    notify.success('已接受请求，请提出交付与支付约定。');
                  });
                }
              "
            >
              接受请求
            </button>
          </template>
          <template v-if="allowed.has('reject')">
            <button
              type="button"
              class="btn btn--ghost"
              @click="
                async () => {
                  await run('reject', async () => {
                    await rejectTrade(
                      trade.data.value!.id,
                      trade.data.value!.version,
                      keys.current('reject'),
                    );
                    notify.info('已拒绝该请求。');
                  });
                }
              "
            >
              拒绝请求
            </button>
          </template>
          <template v-if="allowed.has('withdraw')">
            <button
              type="button"
              class="btn btn--ghost"
              @click="
                async () => {
                  await run('withdraw', async () => {
                    await withdrawTrade(
                      trade.data.value!.id,
                      trade.data.value!.version,
                      keys.current('withdraw'),
                    );
                    notify.info('已撤回购买请求。');
                  });
                }
              "
            >
              撤回请求
            </button>
          </template>
        </div>
        <p class="muted">接受后商品立即锁单，该商品上的其他待接受请求会关闭并分别通知对应买家。</p>
      </section>

      <TradeAgreementSection
        v-model:form-error="formError"
        :trade="trade.data.value"
        :allowed="allowed"
        :agreement-form="agreementForm"
        :keys="keys"
        :run="run"
      />

      <section v-if="currentAgreement" class="card">
        <div class="card__head">
          <h2>完成确认</h2>
          <span class="chip">{{ confirmations.length }}/2 已确认</span>
        </div>
        <p class="muted">一次声明同时涵盖交付与支付已完成；双方均确认后交易才显示为已完成。</p>
        <ul class="confirmations">
          <li v-for="item in confirmations" :key="item.id">
            <span class="state state--ok">已确认</span>
            <span>
              {{
                item.confirmer_id === session.accountId.value ? "你" : counterparty?.display_name
              }}
              于 {{ formatDateTime(item.submitted_at) }} 确认
            </span>
            <span v-if="item.note" class="muted">备注：{{ item.note }}</span>
          </li>
          <li v-if="!confirmations.length" class="muted">还没有完成确认。</li>
        </ul>
        <div v-if="allowed.has('submit_confirmation')" class="stack">
          <div class="field">
            <label class="field__label" for="completion-note">备注（可选）</label>
            <textarea
              id="completion-note"
              v-model="completionNote"
              class="textarea"
              maxlength="1000"
            />
          </div>
          <div class="inline">
            <button type="button" class="btn btn--primary" @click="submitCompletion">
              我已交付并收款完成
            </button>
          </div>
        </div>
        <p
          v-else-if="
            selfConfirmed && confirmations.length === 1 && trade.data.value.status === 'in_progress'
          "
          class="banner banner--info"
        >
          你已提交完成确认，等待对方确认。
        </p>
      </section>

      <section
        v-if="
          trade.data.value.status === 'in_progress' ||
          trade.data.value.status === 'disputed' ||
          trade.data.value.status === 'completed' ||
          trade.data.value.status === 'terminated'
        "
        class="card"
      >
        <div class="card__head"><h2>取消与争议</h2></div>

        <div v-if="cancellation" class="stack stack--tight">
          <p class="inline">
            <span class="state state--warn">
              {{ cancellation.mode === "approval" ? "待对方同意" : "已直接生效" }}
            </span>
            <span class="muted">
              {{ cancellationIsMine ? "你" : "对方" }}于
              {{ formatDateTime(cancellation.proposed_at) }} 提出
            </span>
          </p>
          <p v-if="cancellation.reason" class="quote">“{{ cancellation.reason }}”</p>
          <div v-if="allowed.has('decide_cancellation')" class="inline">
            <button
              v-if="!cancellationIsMine"
              type="button"
              class="btn btn--danger"
              @click="respondToCancellation('accept')"
            >
              同意取消
            </button>
            <button
              v-if="!cancellationIsMine"
              type="button"
              class="btn btn--ghost"
              @click="respondToCancellation('reject')"
            >
              拒绝
            </button>
            <button
              v-if="cancellationIsMine"
              type="button"
              class="btn btn--ghost"
              @click="respondToCancellation('withdraw')"
            >
              撤回取消申请
            </button>
          </div>
        </div>

        <div v-else-if="allowed.has('propose_cancellation')" class="stack">
          <p class="muted">
            约定生效前买方可以取消，卖方取消需买方同意；约定生效后双方同意才终止并计为失败交易。
          </p>
          <div class="field">
            <label class="field__label" for="cancel-reason">取消原因（可选）</label>
            <input id="cancel-reason" v-model="cancelReason" class="input" maxlength="500" />
          </div>
          <div class="inline">
            <button type="button" class="btn btn--danger" @click="submitCancellation">
              申请取消交易
            </button>
          </div>
        </div>

        <div class="divider" />

        <div v-if="dispute" class="stack stack--tight">
          <p class="inline">
            <span class="state state--danger">
              {{
                dispute.status === "open"
                  ? "争议处理中"
                  : dispute.status === "resolved"
                    ? "已处理待确认"
                    : "已结束"
              }}
            </span>
            <span class="muted">
              {{ dispute.initiator_id === session.accountId.value ? "你" : "对方" }}于
              {{ formatDateTime(dispute.opened_at) }} 发起
            </span>
          </p>
          <p class="quote pre-line break-anywhere">{{ dispute.statement }}</p>
          <p v-if="dispute.case_id" class="banner banner--info">
            已提交管理处理，事项编号 #{{
              dispute.case_id
            }}。可继续与对方协商；双方确认处理结果后交易恢复进行。
          </p>
          <div v-if="allowed.has('confirm_dispute_resolution')" class="inline">
            <button type="button" class="btn btn--primary" @click="confirmResolution">
              确认争议已解决
            </button>
          </div>
          <p v-else-if="dispute.status === 'open'" class="muted">
            争议不会自动冻结交易；双方可协商解决，也可由管理员处理。
          </p>
        </div>

        <div v-else-if="allowed.has('open_dispute')" class="stack">
          <p class="muted">存在争议时可先协商；必要时提交管理员处理。</p>
          <div class="field">
            <label class="field__label" for="dispute-statement">争议说明</label>
            <textarea
              id="dispute-statement"
              v-model="disputeStatement"
              class="textarea"
              maxlength="2000"
            />
            <span class="field__hint">{{ disputeStatement.length }}/2000</span>
          </div>
          <div class="inline">
            <button type="button" class="btn btn--danger" @click="submitDispute">发起争议</button>
          </div>
        </div>
        <p v-else class="muted">当前阶段没有可用的取消或争议操作。</p>
      </section>

      <TradeReviewSection
        v-if="trade.data.value.status === 'completed'"
        :trade-id="trade.data.value.id"
        :reviewee-name="counterparty?.display_name ?? '对方'"
      />

      <TradeProductHistory
        :product-id="trade.data.value.product.id"
        :trade-id="trade.data.value.id"
      />

      <details class="card history">
        <summary>约定历史</summary>
        <ul class="history__list">
          <li v-for="agreement in trade.data.value.agreement_history ?? []" :key="agreement.id">
            <span class="state state--neutral">
              {{ agreementStatusLabels[agreement.status] }}
            </span>
            <span>
              第 {{ agreement.version_no }} 版 · {{ formatCents(agreement.amount_cents) }} ·
              {{ agreement.delivery_place_text }}
            </span>
            <span class="muted">{{ formatDateTime(agreement.proposed_at) }}</span>
          </li>
          <li v-if="!(trade.data.value.agreement_history ?? []).length" class="muted">
            暂无历史约定。
          </li>
        </ul>
        <p class="muted">最近更新 {{ formatRelative(trade.data.value.updated_at) }}</p>
      </details>
    </template>

    <p v-if="formError && !trade.data.value" class="banner banner--danger">{{ formError }}</p>
  </div>
</template>

<style scoped>
.overview {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.overview__state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.parties {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  flex-wrap: wrap;
}

.party {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.875rem;
}

.quote {
  border-inline-start: 3px solid var(--line-strong);
  padding-inline-start: var(--space-3);
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.confirmations {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: 0.875rem;
  margin-block: var(--space-2);
}

.confirmations li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.history summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9375rem;
}

.history__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-block-start: var(--space-3);
  font-size: 0.8125rem;
}

.history__list li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
</style>
