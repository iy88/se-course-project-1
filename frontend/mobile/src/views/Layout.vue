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
