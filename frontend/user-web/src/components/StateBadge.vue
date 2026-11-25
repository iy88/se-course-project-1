<script setup lang="ts">
import type { Tone } from "../app/labels";

withDefaults(defineProps<{ label: string; tone?: Tone }>(), { tone: "neutral" });
</script>

<template>
  <span class="state" :class="`state--${tone}`">{{ label }}</span>
</template>
