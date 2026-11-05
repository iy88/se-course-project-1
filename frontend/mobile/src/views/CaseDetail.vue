<template>
  <div class="case-page">
    <AppNavBar :title="c?.title || '事项详情'" />

    <div v-if="c" class="view">
      <section class="surface case-meta">
        <van-cell title="类型" :value="caseTypeLabels[c.case_type]" />
        <van-cell title="状态" :value="caseStatusLabels[c.status]" />
        <van-cell v-if="c.conclusion" title="结论" :label="c.conclusion_reason || c.conclusion" />
      </section>

      <section class="surface case-chat">
        <header class="case-chat__head">
          <h2>沟通记录</h2>
          <span>说明 / 申辩与管理员回复</span>
        </header>

        <div v-if="c.messages?.length" class="case-messages">
          <article v-for="m in c.messages" :key="m.id" class="case-msg" :class="`case-msg--${m.role || 'user'}`">
            <div class="case-msg__meta">
              <span class="pill" :class="roleTone(m)">
                {{ roleLabel(m) }}
              </span>
              <span class="case-msg__kind">{{ kindLabels[m.kind] || m.kind }}</span>
              <span class="case-msg__time">{{ fmtTime(m.created_at) }}</span>
            </div>
            <p class="case-msg__body">{{ m.content }}</p>
          </article>
        </div>

        <EmptyState v-else icon="chat" title="暂无沟通记录" />
      </section>

      <div v-if="c.can_submit_statement || c.can_submit_appeal" class="case-actions">
        <van-button
          v-if="c.can_submit_statement"
          block
          type="primary"
          plain
          @click="openEditor('statement')"
        >
          提交说明
        </van-button>
        <van-button v-if="c.can_submit_appeal" block type="warning" plain @click="openEditor('appeal')">
          提交申辩
        </van-button>
      </div>

      <section v-if="editor.kind" class="surface case-editor">
        <header class="case-editor__head">
          <h2>{{ editor.kind === 'statement' ? '提交说明' : '提交申辩' }}</h2>
        </header>

        <TextField :limit="2000"
          v-model="editor.content"
          type="textarea"
          :label="editor.kind === 'statement' ? '说明内容' : '申辩内容'"
          :rows="4"
          :disabled="editor.submitting"
          placeholder="请填写内容（必填，最多 2000 个字符）"
          class="case-editor__field"
         />

        <p v-if="editor.error" class="case-editor__error">{{ editor.error }}</p>

        <div class="case-editor__actions">
          <van-button size="small" :disabled="editor.submitting" @click="closeEditor">取消</van-button>
          <van-button
            size="small"
            type="primary"
            :loading="editor.submitting"
            :disabled="editor.submitting || !editor.content.trim() || !!textError(editor.content, 2000)"
            @click="submitEditor"
          >
            提交
          </van-button>
        </div>
      </section>
    </div>

    <div v-else-if="loadError" class="view">
      <div class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ loadError }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { textError } from '../api/text'
import TextField from '../components/TextField.vue'
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { caseTypeLabels, caseStatusLabels, fmtTime } from '../api/labels'

const route = useRoute()
const c = ref(null)
const loadError = ref('')
const kindLabels = { inquiry: '问询', statement: '说明', appeal: '申辩', reply: '回复', notice: '留痕' }
const editor = reactive({ kind: '', content: '', error: '', submitting: false })

const roleTone = (m) => {
  if (m.role === 'admin') return 'pill--brand'
  if (m.role === 'system') return ''
  return m.mine ? 'pill--ok' : ''
}

function roleLabel(m) {
  if (m.role === 'admin') return '管理员'
  if (m.role === 'system') return '系统'
  if (m.role === 'user') {
    if (m.mine) return '我'
    return c.value?.trade_id ? '交易参与方' : '对方'
  }
  return m.role || '用户'
}

function errorText(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (!item || typeof item !== 'object') return ''
        const message = item.msg || item.message
        if (typeof message !== 'string' || !message.trim()) return ''
        const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
        return field ? `${field}：${message}` : message
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
    return fallback
  }
  if (detail && typeof detail === 'object') {
    const message = detail.msg || detail.message
    if (typeof message === 'string' && message.trim()) return message
  }
  return fallback
}

async function load() {
  loadError.value = ''
  try {
    c.value = await http.get(`/me/cases/${route.params.id}`)
  } catch {
    loadError.value = '事项加载失败，请稍后重试。'
  }
}

function openEditor(kind) {
  if (editor.submitting) return
  if (editor.kind === kind) return
  editor.kind = kind
  editor.content = ''
  editor.error = ''
}

function closeEditor() {
  if (editor.submitting) return
  editor.kind = ''
  editor.content = ''
  editor.error = ''
}

async function submitEditor() {
  if (!editor.kind || editor.submitting) return
  const content = editor.content.trim()
  if (!content) {
    editor.error = '请填写内容后再提交。'
    return
  }
  if (textError(content, 2000)) {
    editor.error = textError(content, 2000)
    return
  }
  const kind = editor.kind
  editor.submitting = true
  editor.error = ''
  try {
    const data = await http.post(`/me/cases/${route.params.id}/${kind}`, { content })
    showToast(data?.detail || '已提交')
    editor.kind = ''
    editor.content = ''
    await load()
  } catch (err) {
    editor.error = errorText(err, '提交失败，请稍后重试。')
  } finally {
    editor.submitting = false
  }
}

onMounted(load)
</script>

<style scoped>
.case-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.case-meta {
  overflow: hidden;
}

.case-chat {
  margin-top: 12px;
  overflow: hidden;
}

.case-chat__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.case-chat__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.case-chat__head span {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.case-messages {
  padding: 2px 0;
}

.case-msg {
  padding: 12px 16px;
}

.case-msg + .case-msg {
  border-top: 1px solid var(--line);
}

.case-msg--admin {
  background: #fbfdfb;
}

.case-msg--system {
  background: #f7f9f7;
}

.case-msg__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.case-msg__kind {
  color: var(--ink-meta);
  font-size: 11px;
}

.case-msg__time {
  margin-left: auto;
  color: var(--ink-meta);
  font-size: 11px;
}

.case-msg__body {
  margin: 6px 0 0;
  color: var(--ink);
  font-size: 13.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.case-msg--system .case-msg__body {
  color: var(--ink-soft);
}

.case-actions {
  margin-top: 14px;
}

.case-actions :deep(.van-button + .van-button) {
  margin-top: 8px;
}

.case-editor {
  margin-top: 14px;
  overflow: hidden;
}

.case-editor__head {
  padding: 13px 16px 10px;
  border-bottom: 1px solid var(--line);
}

.case-editor__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.case-editor__field {
  padding: 8px 12px;
}

.case-editor__error {
  margin: 0;
  padding: 0 16px 8px;
  color: var(--danger, #b3261e);
  font-size: 12px;
  line-height: 1.5;
}

.case-editor__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 16px 14px;
}
</style>
