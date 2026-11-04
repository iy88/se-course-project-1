<template>
  <main class="offline-page">
    <section class="offline-card" role="status">
      <AppIcon name="alert" :size="32" />
      <h1>暂时无法连接</h1>
      <p>网络或服务器暂时不可用，且此设备没有可验证的本地账户缓存。为保护账户内容，当前不会显示需要登录的业务页面。</p>
      <van-button block type="primary" @click="retry">重新连接</van-button>
    </section>
  </main>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'

const router = useRouter()
const route = useRoute()

function retry() {
  const redirect = route.query.redirect
  const target = typeof redirect === 'string' && redirect.startsWith('/') &&
    !redirect.startsWith('//') && !redirect.startsWith('/offline')
    ? redirect
    : '/home'
  router.replace(target)
}
</script>

<style scoped>
.offline-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--bg);
}
.offline-card {
  width: 100%;
  max-width: 420px;
  padding: 28px 22px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  color: var(--ink);
  text-align: center;
}
.offline-card h1 { margin: 12px 0 8px; font-size: 20px; }
.offline-card p { margin: 0 0 20px; line-height: 1.7; color: var(--ink-meta); }
</style>
