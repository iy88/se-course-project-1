<template>
  <div class="empty-state">
    <span class="empty-state__icon">
      <AppIcon :name="icon" :size="24" />
    </span>
    <p class="empty-state__title">{{ title }}</p>
    <p v-if="hint" class="empty-state__hint">{{ hint }}</p>
    <div v-if="$slots.default" class="empty-state__action">
      <slot />
    </div>
  </div>
</template>

<script setup>
import AppIcon from './AppIcon.vue'

defineProps({
  icon: { type: String, default: 'box' },
  title: { type: String, default: '暂无内容' },
  hint: { type: String, default: '' },
})
</script>
