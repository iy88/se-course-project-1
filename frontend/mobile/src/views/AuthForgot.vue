<template>
  <div class="auth-page auth-page--nav">
    <div class="auth-nav">
      <AppNavBar title="忘记密码" :fixed="false" />
    </div>

    <div class="auth-shell">
      <section class="surface auth-card">
        <div class="auth-card__head">
          <h2>重置登录密码</h2>
          <p>验证账户绑定邮箱后设置新密码</p>
        </div>

        <van-steps :active="step" active-color="#2f6b4f" class="auth-steps">
          <van-step>发送验证码</van-step>
          <van-step>重置密码</van-step>
        </van-steps>

        <div v-if="step === 0" class="auth-fields">
          <van-field v-model="email" label="绑定邮箱" placeholder="账户绑定的邮箱" autocomplete="email">
            <template #left-icon>
              <AppIcon name="mail" :size="18" />
            </template>
          </van-field>
        </div>

        <div v-if="step === 0" class="auth-actions">
          <van-button block type="primary" :loading="loading" @click="send">发送验证码</van-button>
        </div>

        <div v-if="step === 1" class="auth-fields">
          <van-field v-model="code" label="验证码" placeholder="6 位验证码" autocomplete="one-time-code">
            <template #left-icon>
              <AppIcon name="key" :size="18" />
            </template>
          </van-field>
          <van-field v-model="newPassword" type="password" label="新密码" placeholder="至少 6 位" autocomplete="new-password">
            <template #left-icon>
              <AppIcon name="lock" :size="18" />
            </template>
          </van-field>
        </div>

        <div v-if="step === 1" class="auth-actions">
          <van-button block type="primary" :loading="loading" @click="reset">重置密码</van-button>
        </div>

        <p class="auth-note">验证码仅用于本次密码重置；重置成功后将直接进入已登录状态。</p>
      </section>

      <p class="auth-foot">想起密码了？<router-link to="/auth/login">返回登录</router-link></p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import http from '../api/http'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const step = ref(0)
const email = ref('')
const code = ref('')
const newPassword = ref('')
const loading = ref(false)

async function send() {
  if (!email.value) return showToast('请输入邮箱')
  loading.value = true
  try {
    await http.post('/auth/forgot-password/send-code', { email: email.value })
    step.value = 1
    showToast('验证码已发送，请查收邮箱')
  } finally {
    loading.value = false
  }
}

async function reset() {
  if (!code.value || !newPassword.value) return showToast('请完整填写')
  loading.value = true
  try {
    const data = await http.post('/auth/forgot-password/reset', {
      email: email.value,
      code: code.value,
      new_password: newPassword.value,
    })
    session.setSession(data.access_token, data.user)
    showToast('密码已重置')
    router.replace('/home')
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
  padding: 0 16px calc(24px + var(--safe-bottom));
  background: var(--bg);
}

.auth-nav {
  width: 100%;
  max-width: 440px;
}

.auth-shell {
  width: 100%;
  max-width: 440px;
  min-width: 0;
  margin: 12px auto auto;
}

.auth-card {
  padding: 20px 16px 18px;
}

.auth-card__head {
  padding: 0 4px 6px;
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

.auth-steps {
  padding: 12px 0 14px;
  background: transparent;
}

.auth-steps :deep(.van-step__title) {
  font-size: 12.5px;
}

.auth-steps :deep(.van-step__circle-container) {
  background: var(--panel);
}

.auth-fields {
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: var(--panel);
}

.auth-fields :deep(.van-field) {
  padding: 12px;
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
  width: 56px;
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

.auth-note {
  margin: 14px 2px 0;
  color: var(--ink-meta);
  font-size: 12px;
  line-height: 1.55;
}

.auth-foot {
  margin: 16px 0 0;
  color: var(--ink-meta);
  font-size: 12.5px;
  text-align: center;
}

.auth-foot a {
  font-weight: 600;
}
</style>
