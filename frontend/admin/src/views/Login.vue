<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 style="text-align: center; margin-top: 0">校园二手交易平台 · 管理端</h2>
      <p style="text-align: center; color: #909399; font-size: 13px">仅平台管理员登录 · 桌面端使用</p>
      <el-form :model="form" label-position="top" @keyup.enter="submit">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="admin@campus.edu" size="large" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password size="large" />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">登 录</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../api/http'

const router = useRouter()
const form = reactive({ email: '', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.email || !form.password) return ElMessage.warning('请输入邮箱和密码')
  loading.value = true
  try {
    const data = await http.post('/auth/login', form)
    if (data.user.role !== 'admin') {
      ElMessage.error('该账户不是平台管理员')
      return
    }
    localStorage.setItem('admin_token', data.access_token)
    localStorage.setItem('admin_name', data.user.display_name)
    router.push('/cases')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-card {
  width: 380px;
}
</style>
