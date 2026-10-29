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
              <span class="pill" :class="roleTone(m.role)">
                {{ { admin: '管理员', user: '我', system: '系统' }[m.role] || m.role }}
              </span>
              <span class="case-msg__kind">{{ kindLabels[m.kind] || m.kind }}</span>
              <span class="case-msg__time">{{ fmtTime(m.created_at) }}</span>
            </div>
            <p class="case-msg__body">{{ m.content }}</p>
          </article>
        </div>

        <EmptyState v-else icon="chat" title="暂无沟通记录" />
      </section>

      <div v-if="c.status !== 'pending'" class="case-actions">
        <van-button
          v-if="c.has_inquiry && c.status !== 'disposed'"
          block
          type="primary"
          plain
          @click="submit('statement')"
        >
          提交说明（问询阶段）
        </van-button>
        <van-button v-if="c.status === 'disposed'" block type="warning" plain @click="submit('appeal')">提交申辩</van-button>
      </div>

      <p class="case-hint">说明与申辩由认领管理员在原事项回复；提交不自动撤销处置。</p>
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
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showDialog, showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { caseTypeLabels, caseStatusLabels, fmtTime } from '../api/labels'

const route = useRoute()
const c = ref(null)
const loadError = ref('')
const kindLabels = { inquiry: '问询', statement: '说明', appeal: '申辩', reply: '回复', notice: '留痕' }

const roleTone = (role) => ({ admin: 'pill--brand', system: '', user: 'pill--ok' }[role] || '')

async function load() {
  loadError.value = ''
  try {
    c.value = await http.get(`/me/cases/${route.params.id}`)
  } catch {
    loadError.value = '事项加载失败，请稍后重试。'
  }
}

async function submit(kind) {
  const title = kind === 'statement' ? '提交说明' : '提交申辩'
  const { value } = await showDialog({
    title,
    message: kind === 'statement' ? '针对问询内容进行说明' : '对处置结论提出申辩',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (!value) return
  const data = await http.post(`/me/cases/${route.params.id}/${kind}`, { content: value })
  showToast(data.detail)
  load()
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

.case-hint {
  margin: 10px 0 0;
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.55;
  text-align: center;
}
</style>
