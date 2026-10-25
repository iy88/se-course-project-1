<template>
  <div class="chat">
    <van-nav-bar :title="title" left-arrow @click-left="$router.back()" fixed placeholder>
      <template #right v-if="conversation?.archived">
        <van-button size="small" plain type="primary" @click="toNormal">转普通私聊</van-button>
      </template>
    </van-nav-bar>

    <div class="messages" ref="messagesEl">
      <div v-for="m in messages" :key="m.id" class="bubble-row" :class="{ mine: m.mine }">
        <div class="bubble" :class="{ system: m.kind === 'system', mine: m.mine && m.kind !== 'system' }">
          <div v-if="m.kind === 'system'" class="system-text">{{ m.content }}</div>
          <template v-else>{{ m.content }}</template>
        </div>
      </div>
      <div v-if="!messages.length" class="empty-tip">暂无消息</div>
    </div>

    <div class="input-bar" v-if="conversation && !conversation.archived">
      <van-field
        v-model="draft"
        placeholder="输入消息…"
        :disabled="conversation.archived"
        @keydown.enter.prevent="send"
      />
      <van-button type="primary" size="small" :loading="sending" @click="send">发送</van-button>
    </div>
    <div class="input-bar archived" v-else>该交易分支已归档，历史可查；可转普通私聊继续沟通</div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import http from '../api/http'
import { connectWS, closeWS } from '../api/ws'
import { tradeStatusLabels } from '../api/labels'

const route = useRoute()
const router = useRouter()
const conversation = ref(null)
const messages = ref([])
const draft = ref('')
const sending = ref(false)
const messagesEl = ref(null)
let readTimer = null

const title = ref('会话')

async function load() {
  conversation.value = await http.get(`/conversations/${route.params.id}`)
  messages.value = conversation.value.messages || []
  if (conversation.value.type === 'trade' && conversation.value.trade) {
    title.value = `交易沟通 · ${conversation.value.trade.product_title}`
  } else {
    title.value = conversation.value.peer_name
  }
  await nextTick()
  markRead()
  scrollToBottom()
}

function markRead() {
  // 打开并展示消息时推进该会话已读（BR-18）
  const last = messages.value[messages.value.length - 1]
  if (last) {
    http.post(`/conversations/${route.params.id}/read`, { last_displayed_message_id: last.id }).catch(() => {})
  }
}

function scrollToBottom() {
  messagesEl.value?.scrollTo({ top: messagesEl.value.scrollHeight })
}

async function send() {
  const content = draft.value.trim()
  if (!content) return
  sending.value = true
  try {
    await http.post(`/conversations/${route.params.id}/messages`, { content })
    draft.value = ''
    await load()
  } finally {
    sending.value = false
  }
}

async function toNormal() {
  const data = await http.post(`/conversations/${route.params.id}/to-normal`)
  showToast('已转入普通私聊（历史不迁移）')
  router.replace(`/conversations/${data.id}`)
}

function onWS(data) {
  if (data.type === 'message' && data.conversation_id === Number(route.params.id)) {
    load()
  }
}

onMounted(() => {
  load()
  connectWS(onWS)
  readTimer = setInterval(markRead, 8000)
})
onUnmounted(() => {
  closeWS()
  clearInterval(readTimer)
})
</script>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.messages {
  flex: 1;
  overflow: auto;
  padding: 12px;
}
.bubble-row {
  display: flex;
  margin-bottom: 10px;
}
.bubble-row.mine {
  justify-content: flex-end;
}
.bubble {
  background: #fff;
  border-radius: 10px;
  padding: 8px 12px;
  max-width: 76%;
  font-size: 14px;
  word-break: break-word;
}
.bubble.mine {
  background: #1989fa;
  color: #fff;
}
.bubble.system {
  background: transparent;
}
.system-text {
  text-align: center;
  color: #969799;
  font-size: 12px;
}
.bubble-row:has(.bubble.system) {
  justify-content: center;
}
.input-bar {
  display: flex;
  gap: 8px;
  padding: 8px 12px calc(8px + var(--safe-bottom));
  background: #fff;
  align-items: center;
}
.input-bar.archived {
  justify-content: center;
  color: #969799;
  font-size: 13px;
}
</style>
