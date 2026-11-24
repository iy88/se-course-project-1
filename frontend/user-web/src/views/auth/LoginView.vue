<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { login } from "../../api/account";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { setAccount } from "../../app/session";
import { refreshBadges } from "../../app/badges";
import { ensureEntryContext, entryLimits, passwordRuleText } from "../../app/entry";

const router = useRouter();
const route = useRoute();

const email = ref("");
const password = ref("");
const pending = ref(false);
const error = ref<string | null>(null);

onMounted(() => {
  void ensureEntryContext();
});

async function submit(): Promise<void> {
  if (pending.value) return;
  error.value = null;
  pending.value = true;
  try {
    const identity = await login(
      { email: email.value.trim(), password: password.value },
      newIdempotencyKey(),
    );
    setAccount(identity.account);
    await refreshBadges();
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.replace(redirect);
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <section class="auth">
    <header class="auth__head">
      <h1>登录</h1>
      <p class="muted">使用校园邮箱登录，发布和交易都需要登录后进行。</p>
    </header>

    <form class="auth__form" @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="login-email">邮箱</label>
        <input
          id="login-email"
          v-model="email"
          class="input"
          type="email"
          autocomplete="username"
          required
        />
      </div>
      <div class="field">
        <label class="field__label" for="login-password">密码</label>
        <input
          id="login-password"
          v-model="password"
          class="input"
          type="password"
          autocomplete="current-password"
          :placeholder="passwordRuleText(entryLimits)"
          required
        />
      </div>
      <p v-if="error" class="field__error" role="alert">{{ error }}</p>
      <button class="btn btn--primary btn--block" type="submit" :disabled="pending">
        {{ pending ? "正在登录…" : "登录" }}
      </button>
    </form>

    <div class="auth__links">
      <RouterLink to="/register">还没有账户？注册</RouterLink>
      <RouterLink to="/reset-password">忘记密码</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.auth {
  inline-size: min(24rem, 100%);
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
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  margin-block-start: var(--space-4);
  font-size: 0.8125rem;
}
</style>
