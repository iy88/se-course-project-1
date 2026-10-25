<template>
  <div class="auth-page">
    <van-nav-bar title="注册账户" left-arrow @click-left="$router.back()" />
    <van-form @submit="submit">
      <van-cell-group inset>
        <van-field v-model="form.email" label="邮箱" placeholder="邮箱（全平台唯一，用于登录）"
          :rules="[{ required: true, message: '请输入邮箱' }, { pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: '邮箱格式不正确' }]" />
        <van-field v-model="form.display_name" label="显示名称" placeholder="其他用户可见的名称"
          :rules="[{ required: true, message: '请输入显示名称' }]" />
        <van-field v-model="form.password" type="password" label="密码" placeholder="至少 6 位"
          :rules="[{ required: true, message: '请输入密码' }, { validator: (v) => v.length >= 6, message: '密码至少 6 位' }]" />
        <van-field v-model="form.password2" type="password" label="确认密码" placeholder="再次输入密码"
          :rules="[{ validator: (v) => v === form.password, message: '两次输入不一致' }]" />
      </van-cell-group>
      <div class="actions">
        <van-button round block type="primary" native-type="submit" :loading="loading">注 册</van-button>
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
const form = reactive({ email: '', display_name: '', password: '', password2: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    const data = await http.post('/auth/register', {
      email: form.email,
      display_name: form.display_name,
      password: form.password,
    })
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
  padding-bottom: 40px;
}
.actions {
  margin-top: 24px;
  padding: 0 16px;
}
</style>
