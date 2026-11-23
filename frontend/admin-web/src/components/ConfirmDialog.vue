<script setup lang="ts">
defineProps<{
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  tone?: "default" | "danger";
}>();

defineEmits<{ cancel: []; confirm: [] }>();

function stop(event: Event): void {
  event.stopPropagation();
}
</script>

<template>
  <div v-if="open" class="overlay" role="presentation" @click="$emit('cancel')">
    <div class="dialog" role="dialog" aria-modal="true" :aria-label="title" @click="stop">
      <h2>{{ title }}</h2>
      <p v-if="description" class="muted">{{ description }}</p>
      <div class="dialog__actions">
        <button type="button" class="btn btn--ghost" @click="$emit('cancel')">取消</button>
        <button
          type="button"
          class="btn"
          :class="tone === 'danger' ? 'btn--danger' : 'btn--primary'"
          @click="$emit('confirm')"
        >
          {{ confirmLabel ?? "确认" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: rgb(24 36 32 / 45%);
}

.dialog {
  inline-size: min(28rem, 100%);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  background: var(--panel);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.dialog h2 {
  font-size: 1.0625rem;
}

.dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-block-start: var(--space-2);
}
</style>
