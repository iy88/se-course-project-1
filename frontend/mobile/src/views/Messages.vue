<template>
  <div class="messages-view">
    <AppNavBar title="消息" :back="false" />

    <div class="view">
      <div v-if="loading && !loaded" class="conv-skeletons" aria-hidden="true">
        <div v-for="n in 4" :key="n" class="surface conv-skeleton">
          <div class="skeleton conv-skeleton__avatar" />
          <div class="conv-skeleton__body">
            <div class="skeleton conv-skeleton__line" />
            <div class="skeleton conv-skeleton__line conv-skeleton__line--short" />
          </div>
        </div>
      </div>

      <div v-else-if="error" class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" @click="load">重试</van-button>
      </div>

      <div v-else-if="conversations.length" class="conv-list">
        <router-link
          v-for="c in conversations"
          :key="c.id"
          :to="`/conversations/${c.id}`"
          class="surface conv-card"
        >
          <span class="avatar-text conv-card__avatar">{{ initialOf(c.peer_name) }}</span>

          <span class="conv-card__body">
            <span class="conv-card__top">
              <span class="conv-card__name">{{ c.peer_name }}</span>
              <span v-if="c.type === 'trade'" class="pill pill--brand">交易</span>
              <span v-if="c.archived" class="pill">已归档</span>
            </span>
            <span class="conv-card__sub">{{ subtitle(c) }}</span>
            <span class="conv-card__preview">{{ c.last_message?.content || '暂无消息' }}</span>
          </span>

          <span v-if="c.unread" class="conv-card__badge">{{ c.unread > 99 ? '99+' : c.unread }}</span>
        </router-link>
      </div>

      <EmptyState
        v-else
        icon="chat"
        title="暂无会话"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { tradeStatusLabels, fmtTime } from '../api/labels'

const conversations = ref([])
const loading = ref(false)
const loaded = ref(false)
const error = ref('')

const subtitle = (c) =>
  c.type === 'trade' && c.trade
    ? `${c.trade.product_title} · ${tradeStatusLabels[c.trade.status] || c.trade.status}${c.trade.frozen ? ' · 冻结中' : ''}`
    : `私聊 · ${fmtTime(c.last_message?.created_at)}`

function initialOf(name) {
  return name ? Array.from(name)[0] : '聊'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    conversations.value = await http.get('/conversations')
    loaded.value = true
  } catch {
    error.value = '会话加载失败，请检查网络后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.messages-view {
  padding-bottom: 8px;
}

.conv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conv-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 13px 14px;
  color: var(--ink);
  text-decoration: none;
  transition: border-color 0.15s ease;
}

.conv-card:active {
  border-color: var(--line-strong);
}

.conv-card__avatar {
  width: 42px;
  height: 42px;
  font-size: 16px;
}

.conv-card__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
  padding-right: 18px;
}

.conv-card__top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.conv-card__name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 650;
}

.conv-card__sub {
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-card__preview {
  margin-top: 2px;
  color: var(--ink-soft);
  font-size: 12.5px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-card__badge {
  position: absolute;
  top: 13px;
  right: 12px;
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--danger);
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
}

.conv-skeletons {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conv-skeleton {
  display: flex;
  gap: 11px;
  padding: 13px 14px;
}

.conv-skeleton__avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
}

.conv-skeleton__body {
  flex: 1;
  padding-top: 3px;
}

.conv-skeleton__line {
  height: 12px;
  border-radius: 5px;
}

.conv-skeleton__line + .conv-skeleton__line {
  margin-top: 8px;
}

.conv-skeleton__line--short {
  width: 62%;
}
</style>
