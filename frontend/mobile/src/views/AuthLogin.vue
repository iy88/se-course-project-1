<template>
  <div class="auth-page">
    <div class="auth-shell">
      <header class="auth-brand">
        <BrandMark :size="52" />
        <div>
          <h1>校园二手</h1>
          <p>校内闲置交易 · 沟通与记录都在这里</p>
        </div>
      </header>

      <section class="surface auth-card">
        <div class="auth-card__head">
          <h2>欢迎回来</h2>
          <p>使用注册邮箱登录</p>
        </div>

        <van-form @submit="submit">
          <div class="auth-fields">
            <van-field
              v-model="form.email"
              label="邮箱"
              placeholder="请输入注册邮箱"
              autocomplete="username"
              :rules="[{ required: true, message: '请输入邮箱' }]"
            >
              <template #left-icon>
                <AppIcon name="mail" :size="18" />
              </template>
            </van-field>
            <van-field
              v-model="form.password"
              type="password"
              label="密码"
              placeholder="请输入密码"
              autocomplete="current-password"
              :rules="[{ required: true, message: '请输入密码' }]"
            >
              <template #left-icon>
                <AppIcon name="lock" :size="18" />
              </template>
            </van-field>
          </div>

          <div class="auth-actions">
            <van-button block type="primary" native-type="submit" :loading="loading">登录</van-button>
          </div>
        </van-form>

        <div class="auth-links">
          <router-link to="/auth/register">注册账户</router-link>
          <span class="auth-links__dot" aria-hidden="true">·</span>
          <router-link to="/auth/forgot">忘记密码</router-link>
        </div>
      </section>

      <p class="auth-foot">校园闲置物品发布、检索、沟通与交易记录</p>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { safePostLoginRedirect } from '../router/redirect'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import http from '../api/http'
import { useSession } from '../stores/session'

const router = useRouter()
const route = useRoute()
const session = useSession()
const form = reactive({ email: '', password: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    const data = await http.post('/auth/login', form)
    session.setSession(data.access_token, data.user)
    showToast('登录成功')
    const redirect = route.query.redirect
    router.replace(safePostLoginRedirect(redirect))
  } catch {
    // Error messages are shown by the HTTP interceptor.
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: 100vh;
  padding: calc(28px + var(--safe-top)) 16px calc(24px + var(--safe-bottom));
  background: var(--bg);
}

.auth-shell {
  width: 100%;
  max-width: 440px;
  min-width: 0;
  margin: auto;
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 4px 20px;
}

.auth-brand h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.auth-brand p {
  margin: 2px 0 0;
  color: var(--ink-meta);
  font-size: 12.5px;
}

.auth-card {
  padding: 20px 16px 16px;
}

.auth-card__head {
  padding: 0 4px 14px;
}

.auth-card__head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}

.auth-card__head p {
  margin: 3px 0 0;
  color: var(--ink-meta);
  font-size: 12.5px;
}

.auth-fields {
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: var(--panel);
}

.auth-fields :deep(.van-field) {
  padding: 12px 12px;
}

.auth-fields :deep(.van-field::after) {
  left: 12px;
  right: 12px;
  border-color: var(--line);
}

.auth-fields :deep(.van-field:last-child::after) {
  display: none;
}

.auth-fields :deep(.van-field__left-icon) {
  display: flex;
  align-items: center;
  margin-right: 8px;
  color: var(--ink-meta);
}

.auth-fields :deep(.van-field__label) {
  width: 46px;
  margin-right: 8px;
  color: var(--ink-soft);
  font-size: 13px;
}

.auth-actions {
  margin-top: 18px;
}

.auth-actions :deep(.van-button) {
  height: 44px;
}

.auth-links {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
  padding-top: 4px;
  font-size: 13px;
}

.auth-links a {
  display: inline-block;
  padding: 6px 8px;
  border-radius: 8px;
  font-weight: 600;
}

.auth-links a:active {
  background: var(--brand-soft);
}

.auth-links__dot {
  color: var(--line-strong);
}

.auth-foot {
  margin: 18px 0 0;
  color: var(--ink-meta);
  font-size: 12px;
  text-align: center;
}
</style>
