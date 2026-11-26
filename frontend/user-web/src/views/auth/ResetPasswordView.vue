<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { requestEmailVerification, resetPassword } from "../../api/account";
import type { EmailVerificationTicket } from "../../api/contracts";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { ensureEntryContext, entryLimits, passwordRuleText } from "../../app/entry";

const router = useRouter();

const email = ref("");
const code = ref("");
const password = ref("");
const passwordConfirmation = ref("");
const confirmationChecked = ref(false);
const passwordsDiffer = computed(
  () => confirmationChecked.value && passwordConfirmation.value !== password.value,
);
const ticket = ref<EmailVerificationTicket | null>(null);
const sending = ref(false);
const submitting = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const canSubmit = computed(
  () =>
    !submitting.value &&
    ticket.value !== null &&
    code.value.trim().length > 0 &&
    password.value.length > 0 &&
    passwordConfirmation.value.length > 0,
);

onMounted(() => {
  void ensureEntryContext();
});

async function sendCode(): Promise<void> {
  if (sending.value || email.value.trim().length < 4) return;
  error.value = null;
  notice.value = null;
  sending.value = true;
  try {
    const accepted = await requestEmailVerification(
      { purpose: "password_reset", email: email.value.trim() },
      newIdempotencyKey(),
    );
    ticket.value = accepted.requests[0] ?? null;
    notice.value = "如该邮箱已注册，验证码会发送到该地址。";
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    sending.value = false;
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value || !ticket.value) return;
  error.value = null;
  confirmationChecked.value = true;
  if (passwordsDiffer.value) return;
  submitting.value = true;
  try {
    await resetPassword(
      {
        verification_id: ticket.value.verification_id,
        code: code.value.trim(),
        new_password: password.value,
      },
      newIdempotencyKey(),
    );
    await router.replace({ name: "login" });
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
      <h1>重置密码</h1>
      <p class="muted">通过邮箱验证码设置新密码，重置后其他设备上的登录状态会失效。</p>
    </header>

    <form class="auth__form" @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="reset-email">邮箱</label>
        <div class="inline">
          <input
            id="reset-email"
            v-model="email"
            class="input"
            type="email"
            autocomplete="email"
            required
          />
          <button type="button" class="btn" :disabled="sending" @click="sendCode">
            {{ sending ? "发送中…" : "获取验证码" }}
          </button>
        </div>
      </div>

      <div class="field">
        <label class="field__label" for="reset-code">邮箱验证码</label>
        <input
          id="reset-code"
          v-model="code"
          class="input"
          inputmode="numeric"
          autocomplete="one-time-code"
          required
        />
      </div>

      <div class="field">
        <label class="field__label" for="reset-password">新密码</label>
        <input
          id="reset-password"
          v-model="password"
          class="input"
          type="password"
          autocomplete="new-password"
          :minlength="entryLimits?.password_min_length ?? 10"
          required
        />
        <span class="field__hint">{{ passwordRuleText(entryLimits) }}</span>
      </div>

      <div class="field">
        <label class="field__label" for="reset-password-confirmation">确认新密码</label>
        <input
          id="reset-password-confirmation"
          v-model="passwordConfirmation"
          class="input"
          type="password"
          autocomplete="new-password"
          :aria-invalid="passwordsDiffer || undefined"
          :aria-describedby="passwordsDiffer ? 'reset-password-confirmation-error' : undefined"
          required
        />
        <p
          v-if="passwordsDiffer"
          id="reset-password-confirmation-error"
          class="field__error"
          role="alert"
        >
          两次输入的新密码不一致。
        </p>
      </div>

      <p v-if="notice" class="banner banner--info">{{ notice }}</p>
      <p v-if="error" class="field__error" role="alert">{{ error }}</p>

      <button class="btn btn--primary btn--block" type="submit" :disabled="!canSubmit">
        {{ submitting ? "正在重置…" : "重置密码" }}
      </button>
    </form>

    <div class="auth__links">
      <RouterLink to="/login">返回登录</RouterLink>
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
