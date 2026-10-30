<template>
  <el-card class="case-conversation">
    <template #header><div class="conversation-head"><strong>事项关联会话（只读）</strong><el-button :loading="loading" @click="load(false)">{{ opened ? '刷新会话' : '读取会话' }}</el-button></div></template>
    <p class="hint">仅查看本事项直接关联的会话；读取会留审计记录，不加入会话、不发送消息、不改变参与方已读。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="opened">
      <p v-if="conversation">会话 #{{ conversation.id }} · {{ conversation.type === 'trade' ? '交易分支' : '普通私聊' }} · {{ conversation.archived ? '已归档' : '未归档' }}</p>
      <el-button v-if="hasMore" :loading="loading" @click="load(true)">加载更早消息</el-button>
      <el-empty v-if="!messages.length && !loading && !error" description="暂无消息" />
      <ol class="conversation-messages" aria-label="事项关联会话消息">
        <li v-for="m in messages" :key="m.id" :class="{ target: m.id === targetMessageId }">
          <div class="message-meta">#{{ m.id }} · {{ m.kind === 'system' ? '系统消息' : `用户 #${m.sender_id}` }} · {{ fmt(m.created_at) }} <el-tag v-if="m.id === targetMessageId" size="small" type="warning">举报目标</el-tag></div>
          <p class="message-text">{{ m.content }}</p>
        </li>
      </ol>
    </template>
  </el-card>
</template>
<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
const props = defineProps({ caseId: { type: Number, required: true }, conversationId: { type: Number, required: true } })
const loading = ref(false), error = ref(''), opened = ref(false), messages = ref([]), conversation = ref(null), targetMessageId = ref(null), hasMore = ref(false), cursor = ref(null)
let version = 0
function clear() { ++version; loading.value = false; error.value = ''; opened.value = false; messages.value = []; conversation.value = null; targetMessageId.value = null; hasMore.value = false; cursor.value = null }
async function load(earlier) {
  if (loading.value) return
  const current = ++version
  loading.value = true; error.value = ''
  // 刷新或授权失败时不继续显示已失效的敏感历史。
  if (!earlier) { messages.value = []; conversation.value = null; opened.value = false }
  try {
    const params = { limit: 30 }
    if (earlier && cursor.value) params.before_id = cursor.value
    const data = await http.get(`/admin/cases/${props.caseId}/conversations/${props.conversationId}`, { params })
    if (current !== version) return
    const combined = earlier ? [...data.messages, ...messages.value] : data.messages
    messages.value = [...new Map(combined.map(m => [m.id, m])).values()].sort((a,b) => a.id-b.id)
    conversation.value = data.conversation; targetMessageId.value = data.scope.target_message_id; hasMore.value = data.has_more; cursor.value = data.next_before_id; opened.value = true
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
.hint,.message-meta { font-size: 13px; color: #63756b; } .hint { line-height: 1.7; }
.conversation-messages { padding: 0; margin: 16px 0 0; list-style: none; max-height: 560px; overflow-y: auto; }
.conversation-messages li { padding: 12px; border-bottom: 1px solid #e6ece8; } .conversation-messages .target { background: #fff7e8; }
.message-text { white-space: pre-wrap; overflow-wrap: anywhere; margin-bottom: 0; }
</style>
