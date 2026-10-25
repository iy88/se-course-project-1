<template>
  <div>
    <van-nav-bar title="通知中心" left-arrow @click-left="$router.back()" fixed placeholder />
    <van-pull-refresh v-model="refreshing" @refresh="load">
      <van-cell-group inset>
        <van-cell
          v-for="n in items"
          :key="n.id"
          :title="n.title"
          :label="n.content"
          :value="fmtTime(n.created_at)"
          @click="open(n)"
        >
          <template #icon>
            <van-badge dot :show="!n.is_read" style="margin-right: 10px">
              <van-icon :name="iconOf(n.type)" size="20" />
            </van-badge>
          </template>
        </van-cell>
        <div v-if="!items.length" class="empty-tip">暂无通知</div>
      </van-cell-group>
    </van-pull-refresh>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '../api/http'
import { fmtTime } from '../api/labels'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const items = ref([])
const refreshing = ref(false)

const iconOf = (type) =>
  ({
    review_result: 'checked',
    request_created: 'cart-o',
    request_accepted: 'success',
    request_rejected: 'close',
    request_closed: 'close',
    request_withdrawn: 'revoke',
    agreement_proposed: 'edit',
    agreement_decided: 'checked',
    confirm_progress: 'clock-o',
    trade_completed: 'passed',
    trade_terminated: 'stop-circle-o',
    product_edited: 'edit',
    trade_frozen: 'warning-o',
    trade_dispute: 'warning-o',
    trade_abnormal: 'warning-o',
    report_result: 'shield-o',
    inquiry: 'question-o',
    disposal: 'warning-o',
    appeal_result: 'chat-o',
  }[type] || 'bell')

async function load() {
  try {
    const data = await http.get('/notifications', { params: { page_size: 50 } })
    items.value = data.items
    const unread = await http.get('/notifications/unread-count')
    session.unreadNotifications = unread.unread
  } finally {
    refreshing.value = false
  }
}

async function open(n) {
  // 仅打开具体通知才已读（4.17）
  if (!n.is_read) {
    await http.post(`/notifications/${n.id}/read`).catch(() => {})
    n.is_read = true
  }
  if (n.link_type === 'product') router.push(`/products/${n.link_id}`)
  else if (n.link_type === 'trade') router.push(`/trades/${n.link_id}`)
  else if (n.link_type === 'conversation') router.push(`/conversations/${n.link_id}`)
  else if (n.link_type === 'case') router.push(`/cases/${n.link_id}`)
  else if (n.link_type === 'report') router.push('/me/reports')
}

onMounted(load)
</script>
