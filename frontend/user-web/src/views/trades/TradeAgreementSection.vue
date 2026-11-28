<script setup lang="ts">
/* The page retains the draft and shared write state across detail reload errors. */
import { computed, toRef } from "vue";
import { decideAgreement, proposeAgreement } from "../../api/trades";
import type { TradeView } from "../../api/contracts";
import { formatCents, formatDateTime, fromLocalInputValue } from "../../app/format";
import type { IdempotencyKeys } from "../../app/keys";
import { session } from "../../app/session";
import { notify } from "../../app/toast";
import type { useTradeAgreementDraft } from "./useTradeAgreementDraft";

const props = defineProps<{
  trade: TradeView;
  allowed: Set<string>;
  agreementForm: ReturnType<typeof useTradeAgreementDraft>;
  keys: IdempotencyKeys;
  run: (operation: string, task: () => Promise<void>) => Promise<void>;
}>();
const formError = defineModel<string | null>("formError", { required: true });

const agreementForm = toRef(props, "agreementForm");

const currentAgreement = computed(() => props.trade.agreement.current ?? null);
const pendingAgreement = computed(() => props.trade.agreement.pending ?? null);
const pendingAgreementIsMine = computed(
  () => pendingAgreement.value?.proposed_by === session.accountId.value,
);

async function submitAgreement(): Promise<void> {
  const detail = props.trade;
  formError.value = null;
  const deliveryAt = fromLocalInputValue(agreementForm.value.deliveryAt);
  if (!deliveryAt) {
    formError.value = "请填写交付时间。";
    return;
  }
  if (!agreementForm.value.place.trim()) {
    formError.value = "请填写交付地点。";
    return;
  }
  const cents = Math.round(Number.parseFloat(agreementForm.value.amountYuan) * 100);
  if (!Number.isFinite(cents) || cents <= 0) {
    formError.value = "请填写有效的约定金额。";
    return;
  }
  await props.run("propose-agreement", async () => {
    await proposeAgreement(
      detail.id,
      {
        delivery_at: deliveryAt,
        delivery_place_text: agreementForm.value.place.trim(),
        delivery_method: agreementForm.value.method,
        amount_cents: cents,
        payment_method: agreementForm.value.paymentMethod,
        payment_timing: agreementForm.value.paymentTiming,
        base_agreement_id: currentAgreement.value?.id ?? null,
        expected_version: detail.version,
      },
      props.keys.current("propose-agreement"),
    );
    notify.success("约定已提出，等待对方回应。");
  });
}

async function respondToAgreement(decision: "accept" | "reject" | "withdraw"): Promise<void> {
  const detail = props.trade;
  const proposal = pendingAgreement.value;
  if (!proposal) return;
  await props.run("decide-agreement", async () => {
    await decideAgreement(
      detail.id,
      proposal.id,
      decision,
      detail.version,
      props.keys.current("decide-agreement"),
    );
    notify.success(decision === "accept" ? "约定已生效。" : "已提交回应。");
  });
}
</script>

<template>
  <section class="card">
    <div class="card__head">
      <h2>交易约定</h2>
      <span v-if="currentAgreement" class="chip chip--active">已生效</span>
      <span v-else class="chip">尚未生效</span>
    </div>

    <dl v-if="currentAgreement" class="facts">
      <dt>交付时间</dt>
      <dd>{{ formatDateTime(currentAgreement.delivery_at) }}</dd>
      <dt>交付地点</dt>
      <dd>{{ currentAgreement.delivery_place_text }}</dd>
      <dt>交付方式</dt>
      <dd>{{ currentAgreement.delivery_method }}</dd>
      <dt>约定金额</dt>
      <dd class="amount">{{ formatCents(currentAgreement.amount_cents) }}</dd>
      <dt>支付安排</dt>
      <dd>{{ currentAgreement.payment_method }} · {{ currentAgreement.payment_timing }}</dd>
      <dt>版本</dt>
      <dd>第 {{ currentAgreement.version_no }} 版</dd>
    </dl>

    <div v-if="pendingAgreement" class="pending">
      <div class="divider" />
      <p class="inline">
        <span class="state state--warn">待回应</span>
        <span class="muted">
          {{ pendingAgreement.proposed_by === session.accountId.value ? "你" : "对方" }}于
          {{ formatDateTime(pendingAgreement.proposed_at) }} 提出
        </span>
      </p>
      <dl class="facts">
        <dt>交付时间</dt>
        <dd>{{ formatDateTime(pendingAgreement.delivery_at) }}</dd>
        <dt>交付地点</dt>
        <dd>{{ pendingAgreement.delivery_place_text }}</dd>
        <dt>交付方式</dt>
        <dd>{{ pendingAgreement.delivery_method }}</dd>
        <dt>约定金额</dt>
        <dd class="amount">{{ formatCents(pendingAgreement.amount_cents) }}</dd>
        <dt>支付安排</dt>
        <dd>{{ pendingAgreement.payment_method }} · {{ pendingAgreement.payment_timing }}</dd>
      </dl>
      <div v-if="allowed.has('decide_agreement')" class="inline">
        <button
          v-if="!pendingAgreementIsMine"
          type="button"
          class="btn btn--primary"
          @click="respondToAgreement('accept')"
        >
          同意约定
        </button>
        <button
          v-if="!pendingAgreementIsMine"
          type="button"
          class="btn btn--ghost"
          @click="respondToAgreement('reject')"
        >
          拒绝
        </button>
        <button
          v-if="pendingAgreementIsMine"
          type="button"
          class="btn btn--ghost"
          @click="respondToAgreement('withdraw')"
        >
          撤回本次变更
        </button>
      </div>
    </div>

    <div v-if="allowed.has('propose_agreement')" class="propose">
      <div class="divider" />
      <p class="field__label">
        {{ currentAgreement ? "提出新的约定变更" : "提出首次约定" }}
      </p>
      <div class="form-row">
        <div class="field">
          <label class="field__label" for="delivery-at">交付时间</label>
          <input
            id="delivery-at"
            v-model="agreementForm.deliveryAt"
            class="input"
            type="datetime-local"
          />
        </div>
        <div class="field">
          <label class="field__label" for="delivery-place">交付地点</label>
          <input id="delivery-place" v-model="agreementForm.place" class="input" />
        </div>
        <div class="field">
          <label class="field__label" for="delivery-method">交付方式</label>
          <select id="delivery-method" v-model="agreementForm.method" class="select">
            <option>自提</option>
            <option>校内代送</option>
            <option>约定地点交接</option>
          </select>
        </div>
        <div class="field">
          <label class="field__label" for="agreement-amount">约定金额（元）</label>
          <input
            id="agreement-amount"
            v-model="agreementForm.amountYuan"
            class="input"
            inputmode="decimal"
          />
        </div>
        <div class="field">
          <label class="field__label" for="payment-method">支付安排</label>
          <select id="payment-method" v-model="agreementForm.paymentMethod" class="select">
            <option>当面支付</option>
            <option>线上转账后自取</option>
            <option>线上转账</option>
          </select>
        </div>
        <div class="field">
          <label class="field__label" for="payment-timing">支付时点</label>
          <input id="payment-timing" v-model="agreementForm.paymentTiming" class="input" />
        </div>
      </div>
      <p v-if="formError" class="field__error" role="alert">{{ formError }}</p>
      <div class="inline">
        <button type="button" class="btn btn--primary" @click="submitAgreement">提出约定</button>
      </div>
      <p class="muted">约定变更需对方同意后生效；生效时当前确认与旧计时结束。</p>
    </div>

    <p
      v-if="!currentAgreement && !pendingAgreement && !allowed.has('propose_agreement')"
      class="muted"
    >
      当前阶段不能提出约定。
    </p>
  </section>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: minmax(5.5rem, auto) 1fr;
  gap: var(--space-2) var(--space-4);
  margin: 0;
  font-size: 0.875rem;
}

.facts dt {
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
}

.propose {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.pending {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
</style>
