<template>
  <div>
    <van-nav-bar title="账户设置" left-arrow @click-left="$router.back()" fixed placeholder />

    <van-cell-group inset title="基础信息">
      <van-cell title="用户 ID" :value="String(session.user?.id)" />
      <van-cell title="邮箱" :value="session.user?.email" />
      <van-field v-model="displayName" label="显示名称" placeholder="修改显示名称">
        <template #button>
          <van-button size="small" type="primary" @click="updateName">保存</van-button>
        </template>
      </van-field>
    </van-cell-group>

    <van-cell-group inset title="安全" style="margin-top: 10px">
      <van-field v-model="pwd.current" type="password" label="当前密码" />
      <van-field v-model="pwd.next" type="password" label="新密码" placeholder="至少 6 位" />
      <div class="btn">
        <van-button size="small" type="primary" @click="changePassword">修改密码</van-button>
      </div>
    </van-cell-group>

    <van-cell-group inset title="更换绑定邮箱（需验证新旧邮箱）" style="margin-top: 10px">
      <van-field v-model="emailChange.new_email" label="新邮箱" placeholder="新邮箱地址" />
      <div class="btn-row">
        <van-button size="small" plain @click="sendCode('old')">向当前邮箱发码</van-button>
        <van-button size="small" plain :disabled="!emailChange.new_email" @click="sendCode('new')">向新邮箱发码</van-button>
      </div>
      <van-field v-model="emailChange.old_code" label="当前邮箱验证码" />
      <van-field v-model="emailChange.new_code" label="新邮箱验证码" />
      <div class="btn">
        <van-button size="small" type="primary" @click="changeEmail">确认更换</van-button>
      </div>
      <p v-if="devCode" class="hint">开发环境验证码：{{ devCode }}</p>
    </van-cell-group>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { showToast } from 'vant'
import http from '../api/http'
import { useSession } from '../stores/session'

const session = useSession()
const displayName = ref(session.user?.display_name || '')
const pwd = reactive({ current: '', next: '' })
const emailChange = reactive({ new_email: '', old_code: '', new_code: '' })
const devCode = ref('')

async function updateName() {
  if (!displayName.value.trim()) return showToast('名称不能为空')
  const data = await http.patch('/auth/profile', { display_name: displayName.value })
  session.updateUser(data)
  showToast('已保存')
}

async function changePassword() {
  if (!pwd.current || !pwd.next || pwd.next.length < 6) return showToast('请完整填写，新密码至少 6 位')
  await http.post('/auth/change-password', { current_password: pwd.current, new_password: pwd.next })
  pwd.current = pwd.next = ''
  showToast('密码已修改')
}

async function sendCode(target) {
  const payload = target === 'old' ? { target } : { target, new_email: emailChange.new_email }
  const data = await http.post('/auth/email/send-code', payload)
  devCode.value = data.dev_code || ''
  showToast('验证码已发送')
}

async function changeEmail() {
  if (!emailChange.new_email || !emailChange.old_code || !emailChange.new_code) return showToast('请完整填写')
  const data = await http.post('/auth/email/change', {
    new_email: emailChange.new_email,
    old_code: emailChange.old_code,
    new_code: emailChange.new_code,
  })
  session.updateUser(data)
  showToast('邮箱已更换，用户 ID 不变')
}
</script>

<style scoped>
.btn {
  padding: 8px 16px 12px;
}
.btn-row {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
}
.hint {
  color: #969799;
  font-size: 12px;
  text-align: center;
  padding-bottom: 8px;
}
</style>
