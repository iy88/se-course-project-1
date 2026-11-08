<template>
  <div class="auth-page auth-page--nav">
    <div class="auth-nav">
      <AppNavBar title="注册账户" :fixed="false" />
    </div>

    <div class="auth-shell">
      <section class="surface auth-card">
        <div class="auth-card__head">
          <h2>创建账户</h2>
          <p>验证邮箱后即可发布闲置、发起沟通</p>
        </div>

        <van-form @submit="submit">
          <div class="auth-fields">
            <van-field
              v-model="form.email"
              label="邮箱"
              placeholder="全平台唯一，用于登录"
              autocomplete="email"
              :rules="[{ required: true, message: '请输入邮箱' }, { pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: '邮箱格式不正确' }]"
            >
              <template #left-icon>
                <AppIcon name="mail" :size="18" />
              </template>
            </van-field>

            <van-field
              v-model="form.code"
              label="验证码"
              placeholder="6 位验证码"
              maxlength="6"
              autocomplete="one-time-code"
              :rules="[{ required: true, message: '请输入邮箱验证码' }, { pattern: /^\d{6}$/, message: '请输入 6 位数字验证码' }]"
            >
              <template #left-icon>
                <AppIcon name="key" :size="18" />
              </template>
              <template #button>
                <van-button size="small" type="primary" plain native-type="button" :loading="sending" :disabled="loading" @click="sendCode">
                  发送验证码
                </van-button>
              </template>
            </van-field>

            <TextField :limit="64"
              v-model="form.display_name"
              label="显示名称"
              placeholder="其他用户可见的名称"
              :rules="[{ required: true, message: '请输入显示名称' }]"
            >
              <template #left-icon>
                <AppIcon name="user" :size="18" />
              </template>
            </TextField>

            <van-field
              v-model="form.password"
              type="password"
              label="密码"
              placeholder="至少 6 位"
              autocomplete="new-password"
              :rules="[{ required: true, message: '请输入密码' }, { validator: (v) => v.length >= 6, message: '密码至少 6 位' }]"
            >
              <template #left-icon>
                <AppIcon name="lock" :size="18" />
              </template>
            </van-field>

            <van-field
              v-model="form.password2"
              type="password"
              label="确认密码"
              placeholder="再次输入密码"
              autocomplete="new-password"
              :rules="[{ required: true, message: '请再次输入密码' }, { validator: (v) => v === form.password, message: '两次输入不一致' }]"
            >
              <template #left-icon>
                <AppIcon name="lock" :size="18" />
              </template>
            </van-field>
          </div>

          <div class="auth-actions">
            <van-button block type="primary" native-type="submit" :loading="loading" :disabled="sending">注册</van-button>
          </div>
        </van-form>


      </section>

      <p class="auth-foot">已有账户？<router-link to="/auth/login">返回登录</router-link></p>
    </div>
  </div>
</template>

<script setup>
import TextField from '../components/TextField.vue'
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import http from '../api/http'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const form = reactive({ email: '', code: '', display_name: '', password: '', password2: '' })
const loading = ref(false)
const sending = ref(false)

const emailValid = () => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)

// After the target email changes, an entered verification code no longer matches it, so clear the input; the server remains authoritative for verification results.
watch(
  () => form.email,
  () => {
    form.code = ''
  },
)

async function sendCode() {
  if (!emailValid()) return showToast('请先填写正确的邮箱')
  sending.value = true
  try {
    await http.post('/auth/register/send-code', { email: form.email })
    showToast('验证码已发送，请查收邮箱')
  } finally {
    sending.value = false
  }
}

async function submit() {
  if (!form.code || !/^\d{6}$/.test(form.code)) return showToast('请输入 6 位邮箱验证码')
  // Whether the code is valid is decided only by the server: if sending the code times out or the network fails, the user may still submit a code already received.
  loading.value = true
  try {
    const data = await http.post('/auth/register', {
      email: form.email,
      code: form.code,
      display_name: form.display_name,
      password: form.password,
    })
    // Create the login session only after the server verifies the code and creates the account; on failure do not enter the account.
    session.setSession(data.access_token, data.user)
    showToast('注册成功')
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
  padding: 11px 12px;
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
