<template>
  <div class="auth-page">
    <div class="logo">🛒 校园二手</div>
    <van-form @submit="submit">
      <van-cell-group inset>
        <van-field v-model="form.email" label="邮箱" placeholder="请输入注册邮箱" :rules="[{ required: true, message: '请输入邮箱' }]" />
        <van-field v-model="form.password" type="password" label="密码" placeholder="请输入密码" :rules="[{ required: true, message: '请输入密码' }]" />
      </van-cell-group>
      <div class="actions">
        <van-button round block type="primary" native-type="submit" :loading="loading">登录</van-button>
        <div class="links">
          <van-button size="small" plain to="/auth/register">注册账户</van-button>
          <van-button size="small" plain to="/auth/forgot">忘记密码</van-button>
        </div>
      </div>
    </van-form>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import http from '../api/http'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const form = reactive({ email: '', password: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    const data = await http.post('/auth/login', form)
    session.setSession(data.access_token, data.user)
    showToast('登录成功')
    router.replace('/home')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  padding: 60px 16px 0;
}
.logo {
  text-align: center;
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 32px;
}
.actions {
  margin-top: 24px;
  padding: 0 16px;
}
.links {
  display: flex;
  justify-content: space-between;
  margin-top: 12px;
}
</style>
