<script setup lang="ts">
/*
 * Registration in two steps: verify the mailbox, then create the account with the
 * returned verification id. The code sent to the mailbox is never displayed by
 * the application; the development fixture accepts any six characters.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { register, requestEmailVerification } from "../../api/account";
import type { EmailVerificationTicket } from "../../api/contracts";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { setAccount } from "../../app/session";
import { refreshBadges } from "../../app/badges";
import { ensureEntryContext, entryLimits, passwordRuleText } from "../../app/entry";

const router = useRouter();

const email = ref("");
const displayName = ref("");
const password = ref("");
const code = ref("");
const ticket = ref<EmailVerificationTicket | null>(null);
const sending = ref(false);
const submitting = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const canSendCode = computed(() => !sending.value && email.value.trim().length > 3);
const canSubmit = computed(
  () =>
    !submitting.value &&
    ticket.value !== null &&
    code.value.trim().length > 0 &&
    password.value.length > 0 &&
    displayName.value.trim().length > 0,
);

onMounted(() => {
  void ensureEntryContext();
});

async function sendCode(): Promise<void> {
  if (!canSendCode.value) return;
  error.value = null;
  notice.value = null;
  sending.value = true;
  try {
    const accepted = await requestEmailVerification(
      { purpose: "registration", email: email.value.trim() },
      newIdempotencyKey(),
    );
    ticket.value = accepted.requests[0] ?? null;
    notice.value = "验证码申请已受理，邮件正在发送，请在有效期内填写。";
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    sending.value = false;
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value || !ticket.value) return;
  error.value = null;
  submitting.value = true;
  try {
    const created = await register(
      {
        email: email.value.trim(),
        display_name: displayName.value.trim(),
        password: password.value,
        verification_id: ticket.value.verification_id,
        code: code.value.trim(),
      },
      newIdempotencyKey(),
    );
    setAccount({
      account_id: created.account_id,
      display_name: created.display_name,
      email: created.email,
      roles: ["user"],
      avatar_url: null,
    });
    await refreshBadges();
    await router.replace("/");
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="auth">
    <header class="auth__head">
      <h1>注册</h1>
      <p class="muted">先验证邮箱，再用验证码创建账户。</p>
    </header>

    <form class="auth__form" @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="reg-email">校园邮箱</label>
        <div class="inline">
          <input
            id="reg-email"
            v-model="email"
            class="input"
            type="email"
            autocomplete="email"
            required
          />
          <button type="button" class="btn" :disabled="!canSendCode" @click="sendCode">
            {{ sending ? "发送中…" : ticket ? "重新发送" : "获取验证码" }}
          </button>
        </div>
      </div>

      <div class="field">
        <label class="field__label" for="reg-code">邮箱验证码</label>
        <input
          id="reg-code"
          v-model="code"
          class="input"
          inputmode="numeric"
          autocomplete="one-time-code"
          :maxlength="entryLimits?.email_code_length ?? 6"
          required
        />
        <span class="field__hint">
          {{ entryLimits ? `${entryLimits.email_code_length} 位，` : "" }}有效期
          {{ entryLimits ? Math.round(entryLimits.code_ttl_seconds / 60) : 10 }} 分钟
        </span>
      </div>

      <div class="field">
        <label class="field__label" for="reg-name">显示名称</label>
        <input
          id="reg-name"
          v-model="displayName"
          class="input"
          :maxlength="entryLimits?.display_name_max_length ?? 24"
          required
        />
      </div>

      <div class="field">
        <label class="field__label" for="reg-password">密码</label>
        <input
          id="reg-password"
          v-model="password"
          class="input"
          type="password"
          autocomplete="new-password"
          :minlength="entryLimits?.password_min_length ?? 10"
          :maxlength="entryLimits?.password_max_length ?? 128"
          required
        />
        <span class="field__hint">{{ passwordRuleText(entryLimits) }}</span>
      </div>

      <p v-if="notice" class="banner banner--info">{{ notice }}</p>
      <p v-if="error" class="field__error" role="alert">{{ error }}</p>

      <button class="btn btn--primary btn--block" type="submit" :disabled="!canSubmit">
        {{ submitting ? "正在创建账户…" : "创建账户" }}
      </button>
    </form>

    <div class="auth__links">
      <RouterLink to="/login">已有账户，去登录</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.auth {
  inline-size: min(26rem, 100%);
  padding: var(--space-5);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-soft);
}

.auth__head {
  margin-block-end: var(--space-4);
}

.auth__head h1 {
  font-size: 1.375rem;
  margin-block-end: var(--space-1);
}

.auth__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.auth__links {
  margin-block-start: var(--space-4);
  font-size: 0.8125rem;
}
</style>
