<template>
  <div class="page">
    <router-view v-slot="{ Component }">
      <component :is="Component" />
    </router-view>
    <van-tabbar route safe-area-inset-bottom>
      <van-tabbar-item to="/home" icon="home-o">首页</van-tabbar-item>
      <van-tabbar-item to="/publish" icon="add-o">发布</van-tabbar-item>
      <van-tabbar-item to="/messages" icon="chat-o" :badge="badge(messagesBadge)">消息</van-tabbar-item>
      <van-tabbar-item to="/notifications" icon="bell" :badge="badge(notificationsBadge)">通知</van-tabbar-item>
      <van-tabbar-item to="/me" icon="user-o">我的</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useSession } from '../stores/session'
import { connectWS, closeWS } from '../api/ws'
import http from '../api/http'

const session = useSession()
const messagesBadge = computed(() => session.unreadMessages)
const notificationsBadge = computed(() => session.unreadNotifications)
const badge = (n) => (n > 0 ? (n > 99 ? '99+' : String(n)) : '')

async function refreshBadges() {
  if (!localStorage.getItem('token')) return
  try {
    const [msg, notif] = await Promise.all([
      http.get('/conversations/unread-summary'),
      http.get('/notifications/unread-count'),
    ])
    session.unreadMessages = msg.unread
    session.unreadNotifications = notif.unread
  } catch {
    /* 静默失败，稍后随 WS/重试刷新 */
  }
}

function onWSMessage(data) {
  if (data.type === 'notification') {
    session.unreadNotifications += 1
  } else if (data.type === 'message') {
    session.unreadMessages += 1
  }
}

onMounted(() => {
  refreshBadges()
  connectWS(onWSMessage)
})
onUnmounted(() => closeWS())

defineExpose({ refreshBadges })
</script>
