<script setup lang="ts">
import AuthLayout from "../../../../shared/AuthLayout.vue";
import UiIcon from "../../../../shared/UiIcon.vue";
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { login } from "../../api/account";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { setAccount } from "../../app/session";
import { refreshBadges } from "../../app/badges";
import { ensureEntryContext } from "../../app/entry";

const router = useRouter();
const route = useRoute();

const registeredEmail: unknown = window.history.state?.registrationEmail;
const registrationEmail = typeof registeredEmail === "string" ? registeredEmail : "";
const email = ref(registrationEmail);
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
  <AuthLayout
    flat
    brand="校园二手交易"
    intro-title="在校园里买卖闲置"
    intro-description="找一件用得上的商品，也让自己的闲置找到新主人。"
    :intro-features="[
      { title: '找商品', description: '按关键词、分类和价格范围筛选。' },
      { title: '收藏商品', description: '把感兴趣的商品存到「我的收藏」，方便回来查看。' },
      { title: '发布闲置', description: '填写商品信息并提交审核，在「我的商品」查看进度。' },
    ]"
    title="登录"
    description="使用邮箱登录。"
  >
    <p v-if="registrationEmail" class="banner banner--ok auth__notice" role="status">
      注册成功，请使用邮箱和密码登录。
    </p>
    <form class="auth-form" method="post" @submit.prevent="submit">
      <div class="field">
        <label class="field__label" for="login-email">邮箱</label>
        <input
          id="login-email"
          placeholder="请输入邮箱地址"
          v-model="email"
          class="input"
          type="email"
          name="email"
          autocomplete="username"
          required
        />
      </div>
      <div class="field">
        <div class="auth__password-label">
          <label class="field__label" for="login-password">密码</label>
          <RouterLink to="/reset-password">忘记密码</RouterLink>
        </div>
        <input
          id="login-password"
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
      <button class="btn btn--primary btn--block" type="submit" :disabled="pending">
        <UiIcon name="login" />
        {{ pending ? "正在登录…" : "登录" }}
      </button>
    </form>

    <template #footer>
      <p>还没有账户？ <RouterLink to="/register">注册</RouterLink></p>
    </template>
  </AuthLayout>
</template>

<style scoped>
.auth__notice {
  margin-block-end: var(--space-4);
}

.auth__password-label {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: baseline;
  font-size: 0.875rem;
}

.auth__password-label a {
  font-weight: 650;
}
</style>
