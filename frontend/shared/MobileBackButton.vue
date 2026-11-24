<script setup lang="ts">
import UiIcon from "./UiIcon.vue";

withDefaults(
  defineProps<{
    label?: string;
  }>(),
  {
    label: "返回上一页",
  },
);

defineEmits<{ back: [] }>();
</script>

<template>
  <button
    type="button"
    class="mobile-back"
    :aria-label="label"
    :title="label"
    @click="$emit('back')"
  >
    <UiIcon name="chevron-right" />
  </button>
</template>

<style scoped>
.mobile-back {
  display: none;
  align-items: center;
  justify-content: center;
  inline-size: var(--control-min-block);
  min-block-size: var(--control-min-block);
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
  color: var(--brand-ink);
  font-size: 0.8125rem;
  font-weight: 650;
  cursor: pointer;
  transition:
    background-color 150ms ease-out,
    border-color 150ms ease-out,
    scale 150ms ease-out;
}

.mobile-back svg {
  inline-size: 1rem;
  block-size: 1rem;
  rotate: 180deg;
}

.mobile-back:active {
  scale: 0.97;
}

@media (width < 48rem) {
  .mobile-back {
    display: inline-flex;
  }
}

@media (hover: hover) {
  .mobile-back:hover {
    border-color: var(--line-strong);
    background: var(--brand-soft);
  }
}

@media (prefers-reduced-motion: reduce) {
  .mobile-back {
    transition: none;
  }

  .mobile-back:active {
    scale: 1;
  }
}
</style>
