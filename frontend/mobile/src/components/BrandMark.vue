<template>
  <svg
    class="brand-mark"
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    role="img"
    :aria-label="label"
  >
    <rect width="64" height="64" rx="14" fill="#2f6b4f" />
    <g fill="none" stroke="#ffffff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
      <path d="M17 23h30M39 15l8 8-8 8" />
      <path d="M47 41H17M25 33l-8 8 8 8" />
    </g>
  </svg>
</template>

<script setup>
defineProps({
  size: { type: [Number, String], default: 36 },
  label: { type: String, default: '校园二手交易平台' },
})
</script>
