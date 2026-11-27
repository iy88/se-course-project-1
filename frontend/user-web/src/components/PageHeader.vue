<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
  /** Small text above the title, e.g. the current section. */
  eyebrow?: string;
}>();
</script>

<template>
  <header class="page-header">
    <p v-if="eyebrow" class="page-header__eyebrow">{{ eyebrow }}</p>
    <div class="page-header__row">
      <div>
        <h1>{{ title }}</h1>
        <p v-if="description" class="page-header__description">{{ description }}</p>
      </div>
      <div class="page-header__actions">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>

<style scoped src="../../../shared/notification-page-header.css"></style>
