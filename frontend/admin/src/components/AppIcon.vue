<script setup>
import { computed } from 'vue'

/**
 * Admin local SVG icon set.
 * A consistent 24-unit grid and linear strokes; color inherits from currentColor and
 * size is controlled by the size prop. Decorative icons default to aria-hidden;
 * icon-only buttons should add an aria-label on the outer element.
 */
const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 18 },
  strokeWidth: { type: [Number, String], default: 1.8 },
})

const ICONS = {
  brand: ['M4 8h15', 'M16 5l4 3-4 3', 'M20 16H5', 'M8 13l-4 3 4 3'],
  cases: ['M4 5h16v14H4z', 'M4 13h4l2 3h4l2-3h4'],
  reports: ['M5 21V4', 'M5 5h12l-2 4 2 4H5'],
  products: ['M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z', 'M4 7.5l8 4.5 8-4.5', 'M12 12v9'],
  trades: ['M3 12h7l2-2 2 2h7', 'M6 9l-3 3 3 3', 'M18 9l3 3-3 3'],
  users: [
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2',
    'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
    'M22 21v-2a4 4 0 0 0-3-3.87',
    'M16 3.13a4 4 0 0 1 0 7.75',
  ],
  user: ['M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2', 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8'],
  categories: ['M20.6 13.6L13 21.2a2 2 0 0 1-2.8 0L3 14V4h10l7.6 7.6a2 2 0 0 1 0 2z', 'M7.5 7.5h.01'],
  prohibited: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M5.6 5.6l12.8 12.8'],
  stats: ['M4 20V10', 'M10 20V4', 'M16 20v-6', 'M22 20H2'],
  logout: ['M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4', 'M16 17l5-5-5-5', 'M21 12H9'],
  search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14', 'M21 21l-4.3-4.3'],
  refresh: ['M21 12a9 9 0 1 1-3-6.7', 'M21 4v5h-5'],
  plus: ['M12 5v14', 'M5 12h14'],
  edit: ['M12 20h9', 'M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z'],
  trash: ['M3 6h18', 'M8 6V4h8v2', 'M19 6l-1 14H6L5 6', 'M10 11v5', 'M14 11v5'],
  back: ['M19 12H5', 'M12 19l-7-7 7-7'],
  next: ['M9 18l6-6-6-6'],
  send: ['M22 2L11 13', 'M22 2l-7 20-4-9-9-4 20-7z'],
  'ban-user': [
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2',
    'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
    'M18 8l4 4',
    'M22 8l-4 4',
  ],
  unlock: ['M5 11h14v10H5z', 'M8 11V7a4 4 0 0 1 7.5-2'],
  check: ['M20 6L9 17l-5-5'],
  close: ['M18 6L6 18', 'M6 6l12 12'],
  filter: ['M3 5h18', 'M6 12h12', 'M10 19h4'],
  calendar: ['M4 5h16v16H4z', 'M8 3v4', 'M16 3v4', 'M4 11h16'],
  chat: ['M21 15a4 4 0 0 1-4 4H8l-5 3V6a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z'],
  alert: ['M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z', 'M12 9v4', 'M12 17h.01'],
  info: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M12 11v5', 'M12 8h.01'],
  shield: ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z'],
  menu: ['M3 6h18', 'M3 12h18', 'M3 18h18'],
  restore: ['M3 12a9 9 0 1 0 3-6.7', 'M3 4v5h5'],
  clock: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M12 7v5l3 2'],
}

const paths = computed(() => ICONS[props.name] || [])
</script>

<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, index) in paths" :key="index" :d="d" />
  </svg>
</template>

<style scoped>
.app-icon {
  display: block;
  flex: 0 0 auto;
  overflow: visible;
}
</style>
