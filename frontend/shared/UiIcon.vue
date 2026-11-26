<script setup lang="ts">
const paths = {
  bell: "M18 8a6 6 0 0 0-12 0c0 5-2 6-2 8h16c0-2-2-3-2-8 M10 20a2 2 0 0 0 4 0",
  user: "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21v-2a6 6 0 0 1 6-5h4a6 6 0 0 1 6 5v2",
  box: "M4 8h16v12H4z M6 4h12l2 4H4z M9 12h6",
  inbox: "M3 13 6 5h12l3 8v6H3z M3 13h6l1 3h4l1-3h6",
  info: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z M12 11v5 M12 8h.01",
  alert: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z M12 8v5 M12 16h.01",
  close: "m6 6 12 12 M18 6 6 18",
  "chevron-right": "m9 18 6-6-6-6",
  bookmark: "M5 4h14v16l-7-4-7 4z",
  file: "M5 3h10l4 4v14H5z M15 3v5h4 M9 12h6 M9 16h6",
  search: "M15.5 15.5 21 21 M17.5 10.5a7 7 0 1 1-14 0 7 7 0 0 1 14 0z",
  filter: "M4 5h16l-6 7v6l-4 2v-8z",
  plus: "M12 5v14 M5 12h14",
  edit: "M14 6l4 4 M4 20l4-1 12-12a2.8 2.8 0 0 0-4-4L4 15z",
  check: "m5 12 5 5 9-10",
  mail: "M6 5h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z M4 8l6.8 5a2 2 0 0 0 2.4 0L20 8",
  settings: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  menu: "M4 7h16 M4 12h16 M4 17h16",
  login: "M14 4h5v16h-5 M4 12h11 M11 8l4 4-4 4",
  logout: "M10 4H5v16h5 M9 12h11 M16 8l4 4-4 4",
  reset: "M4 6v5h5 M4 11a8 8 0 1 1 2 7",
} as const;

const gridTiles = [
  [4, 4],
  [14, 4],
  [4, 14],
  [14, 14],
];

defineProps<{ name: keyof typeof paths | "grid" }>();
</script>

<template>
  <svg
    class="ui-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <template v-if="name === 'grid'">
      <rect
        v-for="([x, y], index) in gridTiles"
        :key="index"
        :x="x"
        :y="y"
        width="6"
        height="6"
        rx="1.4"
      />
    </template>
    <path v-else :d="paths[name]" />
  </svg>
</template>

<style scoped>
.ui-icon {
  display: block;
  flex: 0 0 auto;
  inline-size: 1.125rem;
  block-size: 1.125rem;
}
</style>
