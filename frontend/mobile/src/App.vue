<template>
  <router-view v-slot="{ Component, route }">
    <component :is="Component" :key="route.name === 'chat' ? route.params.id : undefined" />
  </router-view>
  <OfflineNotice />
</template>

<script setup>
import OfflineNotice from './components/OfflineNotice.vue'
</script>
