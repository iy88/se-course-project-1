<template>
  <div class="settings-page">
    <AppNavBar title="账户设置" />
    <AvatarCropper :file="avatarFile" :busy="avatarUploading" @cancel="avatarFile = null" @confirm="uploadAvatar" />

    <div class="view">
      <section class="surface form-section">
        <header class="form-section__head">
          <h2>基础信息</h2>
        </header>
        <div class="avatar-editor">
          <div class="avatar-editor__preview">
            <img v-if="session.user?.avatar_pending_url || session.user?.avatar_url" :src="session.user.avatar_pending_url || session.user.avatar_url" alt="头像预览" />
            <span v-else>{{ (session.user?.display_name || '我').slice(0, 1) }}</span>
          </div>
          <div class="avatar-editor__info">
            <div class="avatar-editor__title">个人头像
              <van-tag v-if="session.user?.avatar_review_status === 'pending'" round type="warning" plain>待审核</van-tag>
              <van-tag v-else-if="session.user?.avatar_review_status === 'rejected'" round type="danger" plain>未通过</van-tag>
            </div>
            <p>{{ session.user?.avatar_review_status === 'pending' ? '审核通过后更新头像' : session.user?.avatar_review_status === 'rejected' ? session.user.avatar_review_reason : '选一张图片，裁切成你的专属头像' }}</p>
          </div>
          <van-uploader
            class="avatar-editor__upload"
            accept="image/jpeg,image/png,image/webp,image/gif"
            :preview-image="false"
            :max-size="10 * 1024 * 1024"
            :disabled="avatarUploading || session.user?.avatar_review_status === 'pending'"
            :after-read="submitAvatar"
            @oversize="showToast('图片不能超过 10 MiB')"
          >
            <van-button class="avatar-editor__button" size="small" round type="primary" plain :loading="avatarUploading" :disabled="session.user?.avatar_review_status === 'pending'">
              {{ session.user?.avatar_review_status === 'pending' ? '审核中' : '更换头像' }}
            </van-button>
          </van-uploader>
        </div>
        <van-cell title="用户 ID" :value="String(session.user?.id)" />
        <van-cell title="邮箱" :value="session.user?.email" />
        <div class="form-fields">
          <van-field v-model="displayName" label="显示名称" placeholder="修改显示名称">
            <template #button>
              <van-button size="small" type="primary" @click="updateName">保存</van-button>
            </template>
          </van-field>
        </div>
      </section>

      <section class="surface form-section">
        <header class="form-section__head">
          <h2>安全</h2>
          <span>修改登录密码</span>
        </header>
        <div class="form-fields">
          <van-field v-model="pwd.current" type="password" label="当前密码" autocomplete="current-password" />
          <van-field v-model="pwd.next" type="password" label="新密码" placeholder="至少 6 位" autocomplete="new-password" />
        </div>
        <div class="section-actions">
          <van-button size="small" type="primary" @click="changePassword">修改密码</van-button>
        </div>
      </section>

      <section class="surface form-section">
        <header class="form-section__head">
          <h2>更换绑定邮箱</h2>
          <span>需验证新旧邮箱</span>
        </header>
        <div class="form-fields">
          <van-field
            v-model="emailChange.new_email"
            type="email"
            inputmode="email"
            label="新邮箱"
            placeholder="新邮箱地址"
            autocomplete="email"
            :error-message="emailErrors.new_email"
            @blur="emailState.validateNewEmailField"
          />
          <div class="code-buttons">
            <van-button
              size="small"
              plain
              type="primary"
              :loading="sending === 'old'"
              :disabled="sending !== '' || changingEmail"
              @click="sendCode('old')"
            >
              向当前邮箱发码
            </van-button>
            <van-button
              size="small"
              plain
              type="primary"
              :loading="sending === 'new'"
              :disabled="sending !== '' || changingEmail"
              @click="sendCode('new')"
            >
              向新邮箱发码
            </van-button>
          </div>
          <van-field
            v-model="emailChange.old_code"
            inputmode="numeric"
            pattern="[0-9]{6}"
            label="当前邮箱验证码"
            placeholder="6 位数字验证码"
            autocomplete="one-time-code"
            :error-message="emailErrors.old_code"
            @blur="emailState.validateCodeField('old_code')"
          />
          <van-field
            v-model="emailChange.new_code"
            inputmode="numeric"
            pattern="[0-9]{6}"
            label="新邮箱验证码"
            placeholder="6 位数字验证码"
            autocomplete="one-time-code"
            :error-message="emailErrors.new_code"
            @blur="emailState.validateCodeField('new_code')"
          />
        </div>
        <div class="section-actions">
          <van-button
            size="small"
            type="primary"
            :loading="changingEmail"
            :disabled="sending !== '' || changingEmail"
            @click="changeEmail"
          >
            确认更换
          </van-button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import http from '../api/http'
import { uploadImage } from '../api/uploads'
import AvatarCropper from '../components/AvatarCropper.vue'
import {
  createEmailChangeState,
  requestEmailChange,
  requestNewEmailCode,
  requestOldEmailCode,
} from '../api/emailChangeValidation'
import { useSession } from '../stores/session'

const session = useSession()
const avatarUploading = ref(false)
const avatarFile = ref(null)
function submitAvatar(item) {
  const file = item.file
  if (!file) return
  if (file.size > 10 * 1024 * 1024) return showToast('图片不能超过 10 MiB')
  avatarFile.value = file
}
async function uploadAvatar(file) {
  avatarUploading.value = true
  try {
    const key = await uploadImage(file, 'avatar')
    await http.post('/auth/avatar', { key })
    await session.refreshUser()
    avatarFile.value = null
    showToast('头像已提交审核')
  } catch (error) {
    showToast(error.message || '头像提交失败')
  } finally {
    avatarUploading.value = false
  }
}
const displayName = ref(session.user?.display_name || '')
const pwd = reactive({ current: '', next: '' })
const emailState = createEmailChangeState(() => session.user?.email)
const { form: emailChange, errors: emailErrors } = emailState
const sending = ref('')
const changingEmail = ref(false)
const post = (url, payload) => http.post(url, payload)

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
  if (sending.value || changingEmail.value) return
  sending.value = target

  try {
    if (target === 'old') {
      const recipient = session.user?.email
      await requestOldEmailCode(post)
      if (!emailState.acceptOldCodeSend(recipient)) return
      showToast('验证码已发送，请查收当前邮箱')
      return
    }

    const request = emailState.beginNewCodeSend()
    const result = await requestNewEmailCode(post, {
      newEmail: emailChange.new_email,
      currentEmail: session.user?.email,
    })
    if (!result.ok) {
      if (!emailState.isCurrentNewCodeSend(request)) return
      emailErrors.new_email = result.error
      showToast(result.error)
      return
    }
    if (!emailState.acceptNewCodeSend(request)) return
    showToast('验证码已发送，请查收新邮箱')
  } catch {
    // 共享 http 拦截器已统一提示请求失败
  } finally {
    sending.value = ''
  }
}

async function changeEmail() {
  if (changingEmail.value || sending.value) return
  changingEmail.value = true

  try {
    const result = await requestEmailChange(post, {
      newEmail: emailChange.new_email,
      oldCode: emailChange.old_code,
      newCode: emailChange.new_code,
      currentEmail: session.user?.email,
    })
    if (!result.ok) {
      Object.assign(emailErrors, result.errors)
      showToast(Object.values(result.errors).find(Boolean) || '请检查填写内容')
      return
    }
    session.updateUser(result.data)
    emailState.reset()
    showToast('邮箱已更换，用户 ID 不变')
  } catch {
    // 共享 http 拦截器已统一提示请求失败
  } finally {
    changingEmail.value = false
  }
}
</script>

<style scoped>
.avatar-editor {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px 20px;
  margin: 0 16px;
  border-bottom: 1px solid var(--van-cell-border-color, #edf1ee);
}
.avatar-editor__preview {
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  border-radius: 20px;
  overflow: hidden;
  display: grid;
  place-items: center;
  background: #eaf3ee;
  color: #36765b;
  font-size: 26px;
  font-weight: 600;
}
.avatar-editor__preview img { width: 100%; height: 100%; object-fit: cover; }
.avatar-editor__info { flex: 1; min-width: 0; }
.avatar-editor__title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 16px; font-weight: 600; }
.avatar-editor__info p { margin: 7px 0 0; font-size: 12px; line-height: 1.6; color: #7b8982; overflow-wrap: anywhere; }
.avatar-editor__upload { flex-shrink: 0; }
.avatar-editor__button { padding: 0 16px; }
@media (max-width: 480px) {
  .avatar-editor { gap: 12px; margin: 0 12px; padding: 20px 4px; }
  .avatar-editor__preview { width: 52px; height: 52px; border-radius: 16px; }
  .avatar-editor__title { font-size: 15px; }
  .avatar-editor__button { padding: 0 12px; }
}
@media (max-width: 359px) {
  .avatar-editor { flex-wrap: wrap; }
  .avatar-editor__upload { margin-left: 64px; }
}

.settings-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.form-section {
  margin-bottom: 12px;
  overflow: hidden;
}

.form-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.form-section__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.form-section__head span {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.form-fields {
  border-top: 1px solid var(--line);
}

.form-fields :deep(.van-field) {
  padding: 12px 16px;
}

.form-fields :deep(.van-field::after) {
  left: 16px;
  right: 16px;
  border-color: var(--line);
}

.form-fields :deep(.van-field:last-child::after) {
  display: none;
}

.form-fields :deep(.van-field__label) {
  width: 88px;
  margin-right: 8px;
  color: var(--ink-soft);
  font-size: 12.5px;
}

.section-actions {
  display: flex;
  justify-content: flex-end;
  padding: 10px 16px 12px;
  border-top: 1px solid var(--line);
}

.code-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
}

@media (max-width: 359px) {
  .form-fields :deep(.van-field),
  .form-section__head,
  .section-actions,
  .code-buttons {
    padding-left: 12px;
    padding-right: 12px;
  }

  .form-fields :deep(.van-field__label) {
    width: 96px;
  }
}
</style>
