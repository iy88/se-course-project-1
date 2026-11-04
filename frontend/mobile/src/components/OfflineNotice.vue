<template>
  <div v-if="offline" class="offline-notice" role="status" aria-live="polite">
    <AppIcon name="alert" :size="16" />
    <span>网络不可用：当前展示已缓存的页面，业务操作需恢复网络后重试。</span>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'

const offline = ref(false)

// 以 navigator.onLine 为准同步离线条状态；初始化即调用，避免首帧误报在线。
function sync() {
  offline.value = typeof navigator !== 'undefined' && navigator.onLine === false
}

sync()

onMounted(() => {
  sync()
  window.addEventListener('online', sync)
  window.addEventListener('offline', sync)
})

onUnmounted(() => {
  window.removeEventListener('online', sync)
  window.removeEventListener('offline', sync)
})
</script>

<style scoped>
/* 固定在底部导航上方，避免遮挡 van-tabbar；宽度与页面内容一致。 */
.offline-notice {
  position: fixed;
  left: 50%;
  bottom: calc(58px + var(--safe-bottom));
  transform: translateX(-50%);
  z-index: 30;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  box-sizing: border-box;
  width: 100%;
  max-width: var(--content);
  padding: 8px 14px;
  border-top: 1px solid var(--line);
  background: var(--danger-soft);
  box-shadow: 0 -2px 10px rgba(24, 36, 32, 0.06);
  color: var(--danger);
  font-size: 12.5px;
  line-height: 1.5;
}

.offline-notice .app-icon {
  flex: 0 0 auto;
  margin-top: 1px;
}
</style>
