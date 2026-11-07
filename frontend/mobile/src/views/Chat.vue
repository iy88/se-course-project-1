<template>
  <div class="chat-shell">
    <AppNavBar :title="title">
      <template v-if="conversation?.archived" #right>
        <van-button size="small" plain type="primary" @click="toNormal">转私聊</van-button>
      </template>
    </AppNavBar>

    <ReportDialog
      v-model:show="reportOpen"
      :target-type="reportTarget.type"
      :target-id="reportTarget.id"
      :title="reportTarget.title"
    />

    <div v-if="loadError" class="chat-error">
      <div class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ loadError }}</span>
        <van-button size="small" plain type="primary" @click="load">重试</van-button>
      </div>
    </div>

    <template v-else>
      <div ref="messagesEl" class="chat-scroll">
        <div v-if="loading" class="chat-skeletons" aria-hidden="true">
          <div class="skeleton chat-skeleton chat-skeleton--left" />
          <div class="skeleton chat-skeleton chat-skeleton--right" />
          <div class="skeleton chat-skeleton chat-skeleton--left chat-skeleton--short" />
        </div>

        <template v-else>
        <div
          v-for="m in messages"
          :key="m.id"
          class="bubble-row"
          :class="{ 'bubble-row--mine': m.mine && m.kind !== 'system', 'bubble-row--system': m.kind === 'system' }"
        >
          <div
            class="bubble-stack"
            :class="{ 'bubble-stack--mine': m.mine && m.kind !== 'system', 'bubble-stack--system': m.kind === 'system' }"
          >
            <div v-if="m.kind === 'system'" class="bubble bubble--system">{{ m.content }}</div>
            <div v-else class="bubble" :class="{ 'bubble--mine': m.mine }">{{ m.content }}</div>
            <time
              v-if="messageTime(m.created_at)"
              class="bubble-time"
              :datetime="m.created_at"
            >{{ messageTime(m.created_at) }}</time>
            <button
              v-if="!m.mine && m.kind !== 'system'"
              type="button"
              class="bubble-report"
              @click="reportMessage(m)"
            >
              举报
            </button>
          </div>
        </div>

        <EmptyState
          v-if="!messages.length"
          icon="chat"
          title="暂无消息"
        />
        </template>
      </div>

      <div v-if="sendBlockReason" class="alert alert--warn chat-block">
        <AppIcon name="alert" :size="16" />
        <span>{{ sendBlockReason }}</span>
      </div>

      <div v-if="conversation && !conversation.archived" class="chat-input-bar">
        <TextField :limit="2000"
          v-model="draft"
          :placeholder="sendBlockReason || '输入消息…'"
          :disabled="!!sendBlockReason"
          @keydown.enter="onEnter"
         />
        <van-button
          type="primary"
          size="small"
          :loading="sending"
          :disabled="!!sendBlockReason || !!textError(draft, 2000)"
          aria-label="发送消息"
          @click="send"
        >
          发送
        </van-button>
      </div>
      <div v-else-if="!loading && conversation" class="chat-archived">该交易分支已归档，历史可查；可转私聊继续沟通</div>
    </template>
  </div>
</template>

<script setup>
import { textError } from '../api/text'
import TextField from '../components/TextField.vue'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import ReportDialog from '../components/ReportDialog.vue'
import http from '../api/http'
import { fmtTime } from '../api/labels'
import { connectWS } from '../api/ws'
import { useSession } from '../stores/session'

const route = useRoute()
const conversationId = route.params.id
const router = useRouter()
const session = useSession()
const conversation = ref(null)
const messages = ref([])
const draft = ref('')
const sending = ref(false)
const messagesEl = ref(null)
const loadError = ref('')
const loading = ref(true)
const reportOpen = ref(false)
const reportTarget = ref({ type: 'message', id: null, title: '举报' })

function reportMessage(message) {
  reportTarget.value = { type: 'message', id: message.id, title: '举报消息' }
  reportOpen.value = true
}
let readTimer = null
let pendingSend = null
let unwireWS = null
let active = true

const title = ref('会话')

function messageTime(value) {
  return fmtTime(value)
}

const sendBlockReason = computed(() => {
  if (session.user?.status === 'banned') return '账户封禁中，暂停双方私聊；请通过处置沟通单联系管理员'
  if (conversation.value?.trade?.frozen) return '本笔交易已冻结，双方消息暂停；历史只读，管理沟通保留'
  return ''
})

async function load() {
  loadError.value = ''
  try {
    conversation.value = await http.get(`/conversations/${conversationId}`)
  } catch {
    loadError.value = '会话加载失败，请稍后重试。'
    return false
  } finally {
    loading.value = false
  }
  messages.value = conversation.value.messages || []
  if (conversation.value.type === 'trade' && conversation.value.trade) {
    title.value = `交易沟通 · ${conversation.value.trade.product_title}`
  } else {
    title.value = conversation.value.peer_name
  }
  await nextTick()
  markRead()
  scrollToBottom()
  return true
}

function markRead() {
  if (!active) return
  // Mark the conversation read when messages are opened and displayed (BR-18)
  const last = messages.value[messages.value.length - 1]
  if (last) {
    http.post(`/conversations/${conversationId}/read`, { last_displayed_message_id: last.id }).catch(() => {})
  }
}

function scrollToBottom() {
  messagesEl.value?.scrollTo({ top: messagesEl.value.scrollHeight })
}

function onEnter(event) {
  if (event.isComposing) return
  event.preventDefault()
  send()
}

async function send() {
  const content = draft.value.trim()
  if (!content || sendBlockReason.value || textError(content, 2000)) return
  // Reuse the key across retries of the same draft: a committed message whose
  // response was lost must not be inserted twice.
  if (!pendingSend || pendingSend.content !== content) {
    pendingSend = {
      content,
      key: (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    }
  }
  sending.value = true
  try {
    await http.post(`/conversations/${conversationId}/messages`, { content }, {
      headers: { 'Idempotency-Key': pendingSend.key },
    })
    pendingSend = null
    draft.value = ''
    await load()
  } finally {
    sending.value = false
  }
}

async function toNormal() {
  const data = await http.post(`/conversations/${conversationId}/to-normal`)
  showToast('已转入私聊（历史不迁移）')
  router.replace(`/conversations/${data.id}`)
}

async function onWS(data) {
  if (data.type === 'resync_required' ||
      (data.type === 'message' && data.conversation_id === Number(conversationId))) {
    if (!await load()) throw new Error('Unable to refresh conversation')
  }
}

onMounted(() => {
  load()
  unwireWS = connectWS(onWS)
  readTimer = setInterval(markRead, 8000)
})
onUnmounted(() => {
  active = false
  unwireWS?.()
  clearInterval(readTimer)
})
</script>

<style scoped>
.bubble-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
  max-width: min(78%, 460px);
}

.bubble-stack--mine {
  align-items: flex-end;
}

.bubble-stack--system {
  align-items: center;
  max-width: 90%;
}

.bubble-stack > .bubble {
  max-width: 100%;
}

.bubble-time {
  max-width: 100%;
  margin-top: 2px;
  color: var(--ink-meta);
  font-size: 11px;
  line-height: 1.35;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.bubble-stack--system .bubble-time {
  text-align: center;
}

.chat-shell {
  background: var(--bg);
}

.chat-error {
  padding: 0 12px;
}

.chat-scroll {
  background: var(--bg);
}

.chat-skeletons {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 4px;
}

.chat-skeleton {
  width: 62%;
  height: 38px;
  border-radius: 12px;
}

.chat-skeleton--right {
  align-self: flex-end;
  width: 52%;
}

.chat-skeleton--short {
  width: 44%;
}

.chat-block {
  margin: 0 12px 8px;
}

.chat-input-bar {
  padding-bottom: calc(8px + var(--safe-bottom));
}

.chat-input-bar :deep(.van-field__control) {
  font-size: 14px;
}

.chat-input-bar :deep(.van-button) {
  flex: 0 0 auto;
  height: 36px;
  padding: 0 16px;
}

.chat-archived {
  padding-bottom: calc(12px + var(--safe-bottom));
}

.bubble-report {
  margin-top: 2px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--ink-faint);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.bubble-report:hover {
  color: var(--brand);
}
</style>
