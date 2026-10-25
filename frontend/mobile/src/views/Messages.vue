<template>
  <div>
    <van-nav-bar title="消息" fixed placeholder />
    <van-cell-group inset>
      <van-cell
        v-for="c in conversations"
        :key="c.id"
        is-link
        @click="open(c)"
      >
        <template #title>
          <div class="conv-title">
            <van-tag v-if="c.type === 'trade'" type="primary" plain style="margin-right: 6px">交易</van-tag>
            <span>{{ c.peer_name }}</span>
            <van-tag v-if="c.archived" type="default" style="margin-left: 6px">已归档</van-tag>
          </div>
          <div class="conv-sub">{{ subtitle(c) }}</div>
        </template>
        <template #label>
          <div class="conv-desc">{{ c.last_message?.content || '暂无消息' }}</div>
        </template>
        <template #value>
          <van-badge v-if="c.unread" :content="c.unread" />
        </template>
      </van-cell>
      <div v-if="!conversations.length" class="empty-tip">暂无会话</div>
    </van-cell-group>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '../api/http'
import { tradeStatusLabels, fmtTime } from '../api/labels'

const router = useRouter()
const conversations = ref([])

const subtitle = (c) =>
  c.type === 'trade' && c.trade
    ? `${c.trade.product_title} · ${tradeStatusLabels[c.trade.status] || c.trade.status}${c.trade.frozen ? ' · 冻结中' : ''}`
    : `普通私聊 · ${fmtTime(c.last_message?.created_at)}`

function open(c) {
  router.push(`/conversations/${c.id}`)
}

onMounted(async () => {
  conversations.value = await http.get('/conversations')
})
</script>

<style scoped>
.conv-title {
  display: flex;
  align-items: center;
}
.conv-sub {
  font-size: 12px;
  color: #969799;
  margin-top: 2px;
}
.conv-desc {
  font-size: 13px;
}
</style>
