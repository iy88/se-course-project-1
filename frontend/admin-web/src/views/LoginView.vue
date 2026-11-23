<script setup lang="ts">
/* Administrator sign-in. The identity endpoint is shared with the user app. */
import { ref } from "vue";
import { IdempotencyKeys } from "../app/keys";
import { problemMessage } from "../app/problems";
import { session } from "../app/session";

const email = ref("");
const password = ref("");
const error = ref<string | null>(null);
const pending = ref(false);
const keys = new IdempotencyKeys();

async function submit(): Promise<void> {
  if (pending.value) return;
  error.value = null;
  if (!email.value.trim() || !password.value) {
    error.value = "请输入邮箱和密码。";
    return;
  }
  pending.value = true;
  try {
    await session.signIn(email.value.trim(), password.value, keys.current("login"));
    keys.rotate("login");
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <main class="login">
    <section class="card login__card">
      <p class="login__brand">
        <span class="login__logo" aria-hidden="true">二</span> 校园二手交易 · 管理端
      </p>
      <h1>管理员登录</h1>
      <p class="muted">使用平台管理员账号登录。待审商品、分类与禁发范围只对管理员开放。</p>
      <form class="stack" @submit.prevent="submit">
        <label class="field">
          <span class="field__label">邮箱</span>
          <input v-model="email" class="input" type="email" autocomplete="username" required />
        </label>
        <label class="field">
          <span class="field__label">密码</span>
          <input
            v-model="password"
            class="input"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>
        <p v-if="error" class="field__error" role="alert">{{ error }}</p>
        <button type="submit" class="btn btn--primary btn--block" :disabled="pending">
          {{ pending ? "正在登录…" : "登录管理端" }}
        </button>
      </form>
    </section>
    <p class="muted login__hint">当前进程：API 与两个前端由本机开发启动器管理。</p>
  </main>
</template>

<style scoped>
.login {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: clamp(2rem, 10vh, 6rem) var(--space-4);
}

.login__card {
  inline-size: min(26rem, 100%);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  box-shadow: var(--shadow);
}

.login__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--brand-ink);
}

.login__logo {
  display: inline-grid;
  place-items: center;
  inline-size: 1.75rem;
  block-size: 1.75rem;
  border-radius: var(--radius-sm);
  background: var(--brand);
  color: #fff;
  font-size: 0.8125rem;
}

.login__hint {
  text-align: center;
}
</style>
