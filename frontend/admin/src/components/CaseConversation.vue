<template>
  <el-card class="case-conversation">
    <template #header><div class="conversation-head"><strong>事项关联会话（只读）</strong><el-button :loading="loading" @click="load(false)">{{ opened ? '刷新会话' : '读取会话' }}</el-button></div></template>
    <p class="hint">仅查看本事项直接关联的会话；读取会留审计记录，不加入会话、不发送消息、不改变参与方已读。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="opened">
      <div v-if="conversation" class="conversation-chips">
        <el-tag effect="plain" size="small">会话 #{{ conversation.id }}</el-tag>
        <el-tag effect="plain" size="small" type="info">{{ conversation.type === 'trade' ? '交易分支' : '普通私聊' }}</el-tag>
        <el-tag effect="plain" size="small" :type="conversation.archived ? 'warning' : 'success'">{{ conversation.archived ? '已归档' : '进行中' }}</el-tag>
      </div>
      <div class="messages-scroll" ref="scrollEl">
        <div class="load-more">
          <el-button v-if="hasMore" size="small" :loading="loading" @click="load(true)">加载更早消息</el-button>
        </div>
        <el-empty v-if="!messages.length && !loading && !error" description="暂无消息" />
        <ol class="conversation-messages" aria-label="事项关联会话消息">
          <li
            v-for="m in messages"
            :key="m.id"
            :class="{ system: m.kind === 'system', target: m.id === targetMessageId }"
          >
            <div class="message-meta">
              <span class="message-sender">{{ m.kind === 'system' ? '系统消息' : `用户 #${m.sender_id}` }}</span>
              <span>{{ fmt(m.created_at) }}</span>
              <el-tag v-if="m.id === targetMessageId" size="small" type="warning">举报目标</el-tag>
            </div>
            <div class="bubble">{{ m.content }}</div>
          </li>
        </ol>
      </div>
    </template>
  </el-card>
</template>
<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
const props = defineProps({ caseId: { type: Number, required: true }, conversationId: { type: Number, required: true } })
const loading = ref(false), error = ref(''), opened = ref(false), messages = ref([]), conversation = ref(null), targetMessageId = ref(null), hasMore = ref(false), cursor = ref(null)
const scrollEl = ref(null)
let version = 0
function clear() { ++version; loading.value = false; error.value = ''; opened.value = false; messages.value = []; conversation.value = null; targetMessageId.value = null; hasMore.value = false; cursor.value = null }
async function scrollToBottom() {
  await nextTick()
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}
async function load(earlier) {
  if (loading.value) return
  const current = ++version
  loading.value = true; error.value = ''
  // 刷新或授权失败时不继续显示已失效的敏感历史。
  if (!earlier) { messages.value = []; conversation.value = null; opened.value = false }
  const prevHeight = earlier ? scrollEl.value?.scrollHeight || 0 : 0
  try {
    const params = { limit: 30 }
    if (earlier && cursor.value) params.before_id = cursor.value
    const data = await http.get(`/admin/cases/${props.caseId}/conversations/${props.conversationId}`, { params })
    if (current !== version) return
    const combined = earlier ? [...data.messages, ...messages.value] : data.messages
    messages.value = [...new Map(combined.map(m => [m.id, m])).values()].sort((a,b) => a.id-b.id)
    conversation.value = data.conversation; targetMessageId.value = data.scope.target_message_id; hasMore.value = data.has_more; cursor.value = data.next_before_id; opened.value = true
    if (earlier) {
      // 前置加载后保持视口停留在原消息位置。
      await nextTick()
      const el = scrollEl.value
      if (el) el.scrollTop = el.scrollHeight - prevHeight
    } else {
      // 首次读取定位到最新消息。
      await scrollToBottom()
    }
  } catch (e) {
    if (current !== version) return
    if ([401,403,404].includes(e?.response?.status)) { messages.value = []; conversation.value = null; opened.value = false; hasMore.value = false; cursor.value = null }
    error.value = typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : '会话读取失败，请重试'
  } finally { if (current === version) loading.value = false }
}
watch(() => [props.caseId, props.conversationId], clear)
onBeforeUnmount(() => ++version)
</script>
<style scoped>
.conversation-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.hint { font-size: 12.5px; color: #63756b; line-height: 1.7; }
.conversation-chips { display: flex; gap: 8px; margin-top: 12px; }
.messages-scroll {
  max-height: 480px;
  overflow-y: auto;
  margin-top: 12px;
  padding: 14px 12px 6px;
  background: var(--brand-soft);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
}
.load-more { text-align: center; padding-bottom: 12px; }
.conversation-messages { padding: 0; margin: 0; list-style: none; display: flex; flex-direction: column; gap: 14px; }
.conversation-messages li { display: flex; flex-direction: column; max-width: 78%; }
.conversation-messages li.system { align-self: center; max-width: 92%; text-align: center; }
.message-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #63756b; margin-bottom: 4px; }
li.system .message-meta { justify-content: center; }
.message-sender { font-weight: 600; color: var(--ink-soft); }
.bubble {
  background: #fff;
  border: 1px solid #e6ece8;
  border-radius: 10px;
  border-top-left-radius: 4px;
  padding: 8px 12px;
  font-size: 13.5px;
  color: var(--ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
li.system .bubble { border-radius: 10px; color: var(--ink-soft); }
li.target .bubble { background: #fff7e8; border-color: #f3d9a4; }
</style>
