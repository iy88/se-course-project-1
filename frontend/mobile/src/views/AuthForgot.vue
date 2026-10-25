<template>
  <div class="auth-page">
    <van-nav-bar title="忘记密码" left-arrow @click-left="$router.back()" />
    <van-steps :active="step" active-color="#1989fa">
      <van-step>发送验证码</van-step>
      <van-step>重置密码</van-step>
    </van-steps>

    <van-cell-group inset v-if="step === 0">
      <van-field v-model="email" label="绑定邮箱" placeholder="账户绑定的邮箱" />
    </van-cell-group>
    <div class="actions" v-if="step === 0">
      <van-button round block type="primary" :loading="loading" @click="send">发送验证码</van-button>
      <p v-if="devCode" class="dev-code">开发环境验证码：<b>{{ devCode }}</b></p>
    </div>

    <van-cell-group inset v-if="step === 1">
      <van-field v-model="code" label="验证码" placeholder="6 位验证码" />
      <van-field v-model="newPassword" type="password" label="新密码" placeholder="至少 6 位" />
    </van-cell-group>
    <div class="actions" v-if="step === 1">
      <van-button round block type="primary" :loading="loading" @click="reset">重置密码</van-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import http from '../api/http'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const step = ref(0)
const email = ref('')
const code = ref('')
const newPassword = ref('')
const devCode = ref('')
const loading = ref(false)

async function send() {
  if (!email.value) return showToast('请输入邮箱')
  loading.value = true
  try {
    const data = await http.post('/auth/forgot-password/send-code', { email: email.value })
    devCode.value = data.dev_code || ''
    step.value = 1
    showToast('验证码已发送')
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
  padding-bottom: 40px;
}
.actions {
  margin: 24px 16px 0;
}
.dev-code {
  text-align: center;
  color: #969799;
  font-size: 13px;
}
</style>
