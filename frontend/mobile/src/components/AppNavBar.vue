<template>
  <van-nav-bar
    class="app-navbar"
    :title="title"
    :fixed="fixed"
    :placeholder="fixed"
    :border="false"
  >
    <template v-if="back" #left>
      <button type="button" class="nav-icon-btn" aria-label="返回上一页" @click="goBack">
        <AppIcon name="chevron-left" :size="22" />
      </button>
    </template>
    <template v-if="$slots.right" #right>
      <slot name="right" />
    </template>
  </van-nav-bar>
</template>

<script setup>
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'

defineProps({
  title: { type: String, default: '' },
  back: { type: Boolean, default: true },
  fixed: { type: Boolean, default: true },
})

const router = useRouter()

function goBack() {
  if (window.history.length > 1) router.back()
  else router.replace('/home')
}
</script>
