<script setup lang="ts">
/* Administrator sign-in. The identity endpoint is shared with the user app. */
import { ref } from "vue";
import AuthLayout from "../../../shared/AuthLayout.vue";
import UiIcon from "../../../shared/UiIcon.vue";
import { IdempotencyKeys } from "../app/keys";
import { problemMessage } from "../app/problems";
import { useSessionStore } from "../app/session";

const session = useSessionStore();
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
  <AuthLayout
    brand="校园二手交易 · 管理端"
    intro-title="维护校园商品平台"
    intro-description="从待审队列认领商品，核对发布内容并提交审核结论。"
    :intro-features="[
      { title: '分类管理', description: '维护分类名称和别名，停用不再使用的分类。' },
      { title: '禁发范围', description: '维护禁发细目，供用户发布商品和管理员审核时查阅。' },
    ]"
    title="管理员登录"
    description="使用平台管理员账号登录。"
  >
    <form class="auth-form" method="post" @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="admin-email">邮箱</label>
        <input
          id="admin-email"
          placeholder="请输入管理员邮箱"
          v-model="email"
          class="input"
          type="email"
          name="email"
          autocomplete="username"
          required
        />
      </div>
      <div class="field">
        <label class="field__label" for="admin-password">密码</label>
        <input
          id="admin-password"
          placeholder="请输入密码"
          v-model="password"
          class="input"
          type="password"
          name="password"
          autocomplete="current-password"
          required
        />
      </div>
      <p v-if="error" class="field__error" role="alert">{{ error }}</p>
      <button type="submit" class="btn btn--primary btn--block" :disabled="pending">
        <UiIcon name="login" />
        {{ pending ? "正在登录…" : "登录管理端" }}
      </button>
    </form>
  </AuthLayout>
</template>
