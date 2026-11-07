<template>
  <div class="page">
    <router-view v-slot="{ Component }">
      <component :is="Component" />
    </router-view>

    <van-tabbar
      route
      safe-area-inset-bottom
      :border="false"
      class="app-tabbar"
      active-color="#2f6b4f"
      inactive-color="#5f7168"
    >
      <van-tabbar-item to="/home">
        <template #icon="{ active }">
          <span class="tab-icon" :class="{ 'tab-icon--active': active }">
            <AppIcon name="home" :size="22" :stroke-width="active ? 2.1 : 1.8" />
          </span>
        </template>
        首页
      </van-tabbar-item>
      <van-tabbar-item to="/publish">
        <template #icon="{ active }">
          <span class="tab-icon" :class="{ 'tab-icon--active': active }">
            <AppIcon name="plus" :size="22" :stroke-width="active ? 2.2 : 1.9" />
          </span>
        </template>
        发布
      </van-tabbar-item>
      <van-tabbar-item to="/messages" :badge="badge(messagesBadge)">
        <template #icon="{ active }">
          <span class="tab-icon" :class="{ 'tab-icon--active': active }">
            <AppIcon name="chat" :size="22" :stroke-width="active ? 2.1 : 1.8" />
          </span>
        </template>
        消息
      </van-tabbar-item>
      <van-tabbar-item to="/notifications" :badge="badge(notificationsBadge)">
        <template #icon="{ active }">
          <span class="tab-icon" :class="{ 'tab-icon--active': active }">
            <AppIcon name="bell" :size="22" :stroke-width="active ? 2.1 : 1.8" />
          </span>
        </template>
        通知
      </van-tabbar-item>
      <van-tabbar-item to="/me">
        <template #icon="{ active }">
          <span class="tab-icon" :class="{ 'tab-icon--active': active }">
            <AppIcon name="user" :size="22" :stroke-width="active ? 2.1 : 1.8" />
          </span>
        </template>
        我的
      </van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { useSession } from '../stores/session'
import { connectWS } from '../api/ws'
import http from '../api/http'

const session = useSession()
const messagesBadge = computed(() => session.unreadMessages)
const notificationsBadge = computed(() => session.unreadNotifications)
const badge = (n) => (n > 0 ? (n > 99 ? '99+' : String(n)) : '')

let badgeRefreshVersion = 0
let badgeRefreshTimer = null

async function refreshBadges() {
  const token = localStorage.getItem('token')
  if (!token) return false
  const version = ++badgeRefreshVersion
  try {
    const [msg, notif] = await Promise.all([
      http.get('/conversations/unread-summary'),
      http.get('/notifications/unread-count'),
    ])
    if (version !== badgeRefreshVersion || localStorage.getItem('token') !== token) return false
    session.unreadMessages = msg.unread
    session.unreadNotifications = notif.unread
    return true
  } catch {
    return false
  }
}

async function onWSMessage(data) {
  if (data.type === 'resync_required') {
    if (!await refreshBadges()) throw new Error('Unable to resync unread counts')
    return
  }
  if (data.type === 'notification' || (data.type === 'message' && data.sender_id !== session.user?.id)) {
    // Replay can include events already reflected in the server's unread counts.
    if (badgeRefreshTimer !== null) return
    badgeRefreshTimer = setTimeout(() => {
      badgeRefreshTimer = null
      refreshBadges()
    }, 100)
  }
}

let unwireWS = null

onMounted(() => {
  refreshBadges()
  unwireWS = connectWS(onWSMessage)
})
onUnmounted(() => {
  unwireWS?.()
  clearTimeout(badgeRefreshTimer)
  badgeRefreshVersion += 1
})

defineExpose({ refreshBadges })
</script>
