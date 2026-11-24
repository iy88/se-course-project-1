<script setup lang="ts">
import { computed } from "vue";
import { initialOf } from "../app/format";

const props = withDefaults(
  defineProps<{
    displayName: string;
    url?: string | null;
    size?: "sm" | "md" | "lg";
  }>(),
  { url: null, size: "md" },
);

const initial = computed(() => initialOf(props.displayName));
</script>

<template>
  <span class="avatar" :class="`avatar--${size}`" :title="displayName">
    <img v-if="url" :src="url" :alt="`${displayName}的头像`" class="avatar__image" />
    <span v-else class="avatar__initial" aria-hidden="true">{{ initial }}</span>
    <span class="visually-hidden">{{ displayName }}</span>
  </span>
</template>

<style scoped>
.avatar {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  overflow: hidden;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-weight: 650;
  border: 1px solid var(--line);
}

.avatar--sm {
  inline-size: 1.75rem;
  block-size: 1.75rem;
  font-size: 0.75rem;
}

.avatar--md {
  inline-size: 2.5rem;
  block-size: 2.5rem;
  font-size: 1rem;
}

.avatar--lg {
  inline-size: 4rem;
  block-size: 4rem;
  font-size: 1.5rem;
}

.avatar__image {
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}
</style>
