<script setup lang="ts">
/*
 * Product image strip and thumbnails.
 *
 * The page owns the active index so a product switch resets it together with
 * the detail load. This component turns track scrolling and thumbnail
 * selection into index updates and keeps the track on the selected slide.
 */
import { computed, onBeforeUnmount, ref } from "vue";
import UiIcon from "../../../../shared/UiIcon.vue";
import type { SignedImage } from "../../api/contracts";

const props = defineProps<{
  images: SignedImage[];
  title: string;
  activeIndex: number;
}>();

const emit = defineEmits<{ "update:activeIndex": [value: number] }>();

const galleryTrack = ref<HTMLDivElement | null>(null);
const activeImage = computed(() => props.images[props.activeIndex] ?? null);
let galleryFrame = 0;

function onGalleryScroll(): void {
  if (galleryFrame) return;
  galleryFrame = requestAnimationFrame(() => {
    galleryFrame = 0;
    const track = galleryTrack.value;
    if (!track || track.clientWidth === 0) return;
    const index = Math.round(track.scrollLeft / track.clientWidth);
    if (index >= 0 && index < props.images.length) {
      emit("update:activeIndex", index);
    }
  });
}

function selectImage(index: number): void {
  emit("update:activeIndex", index);
  const track = galleryTrack.value;
  if (!track) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  track.scrollTo({
    left: index * track.clientWidth,
    behavior: reduceMotion ? "auto" : "smooth",
  });
}

function scrollToStart(): void {
  galleryTrack.value?.scrollTo({ left: 0 });
}

onBeforeUnmount(() => {
  if (galleryFrame) cancelAnimationFrame(galleryFrame);
});

defineExpose({ scrollToStart });
</script>

<template>
  <div class="gallery">
    <div class="gallery__main">
      <div
        v-if="images.length"
        ref="galleryTrack"
        class="gallery__track"
        role="group"
        aria-roledescription="carousel"
        :aria-label="`${title} 商品图片`"
        tabindex="0"
        @scroll.passive="onGalleryScroll"
      >
        <div
          v-for="(image, index) in images"
          :key="image.file_id"
          class="gallery__slide"
          role="group"
          aria-roledescription="slide"
          :aria-label="`第 ${index + 1} 张，共 ${images.length} 张`"
        >
          <img
            :src="image.url"
            :alt="`${title}，第 ${index + 1} 张`"
            class="gallery__image"
            :fetchpriority="index === 0 ? 'high' : 'auto'"
            :loading="index === 0 ? 'eager' : 'lazy'"
            decoding="async"
          />
        </div>
      </div>
      <span v-if="images.length > 1" class="gallery__count">
        {{ activeIndex + 1 }} / {{ images.length }}
      </span>
      <span v-else-if="!activeImage" class="gallery__placeholder">
        <UiIcon name="box" />
        <span>卖家未上传商品图片</span>
      </span>
      <p class="visually-hidden" role="status" aria-live="polite">
        {{ images.length ? `正在查看第 ${activeIndex + 1} 张，共 ${images.length} 张` : "" }}
      </p>
    </div>
    <div v-if="images.length > 1" class="gallery__thumbs">
      <button
        v-for="(image, index) in images"
        :key="image.file_id"
        type="button"
        class="gallery__thumb"
        :class="{ 'gallery__thumb--active': index === activeIndex }"
        :aria-label="`查看第 ${index + 1} 张商品图片`"
        :aria-pressed="index === activeIndex"
        @click="selectImage(index)"
      >
        <img :src="image.url" :alt="`商品图片 ${index + 1}`" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.gallery {
  min-inline-size: 0;
  padding: clamp(0.75rem, 2cqi, 1.25rem);
  background:
    radial-gradient(circle at 15% 10%, rgb(255 255 255 / 80%), transparent 38%), var(--panel-soft);
}

.gallery__main {
  position: relative;
  aspect-ratio: 4 / 3;
  min-block-size: 0;
  border-radius: var(--radius-sm);
  overflow: clip;
  background: rgb(255 255 255 / 72%);
}

.gallery__track {
  display: flex;
  align-items: stretch;
  inline-size: 100%;
  block-size: 100%;
  min-block-size: 0;
  overflow-x: auto;
  overflow-y: clip;
  overscroll-behavior-x: contain;
  scroll-snap-type: x mandatory;
  scrollbar-width: none;
  touch-action: manipulation;
}

.gallery__track::-webkit-scrollbar {
  display: none;
}

.gallery__track:focus-visible {
  outline-offset: -3px;
}

.gallery__slide {
  display: grid;
  flex: 0 0 100%;
  place-items: center;
  min-inline-size: 0;
  min-block-size: 0;
  block-size: 100%;
  overflow: clip;
  scroll-snap-align: start;
  scroll-snap-stop: always;
}

.gallery__image {
  display: block;
  inline-size: 100%;
  block-size: 100%;
  min-block-size: 0;
  max-block-size: 100%;
  object-fit: contain;
}

.gallery__placeholder {
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  font-size: 0.875rem;
  color: var(--ink-faint);
}

.gallery__placeholder svg {
  inline-size: 2rem;
  block-size: 2rem;
}

.gallery__count {
  position: absolute;
  inset-inline-end: var(--space-3);
  inset-block-end: var(--space-3);
  padding: 0.1875rem var(--space-2);
  border-radius: 999px;
  background: rgb(24 36 32 / 72%);
  color: #fff;
  font-size: 0.6875rem;
  font-variant-numeric: tabular-nums;
}

.gallery__thumbs {
  display: flex;
  gap: var(--space-2);
  margin-block-start: var(--space-3);
  padding-block-end: 0.125rem;
  overflow-x: auto;
  overflow-y: clip;
  overscroll-behavior-x: contain;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
}

.gallery__thumbs::-webkit-scrollbar {
  display: none;
}

.gallery__thumb {
  flex: 0 0 auto;
  inline-size: 3.75rem;
  block-size: 3.75rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
  padding: 0;
  background: var(--panel);
  cursor: pointer;
  scroll-snap-align: start;
  transition:
    border-color 150ms ease-out,
    scale 150ms ease-out;
}

.gallery__thumb--active {
  border-color: var(--brand);
  box-shadow: 0 0 0 2px var(--brand-soft);
}

.gallery__thumb img {
  display: block;
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}

@media (hover: hover) {
  .gallery__thumb:hover {
    border-color: var(--brand);
    scale: 1.03;
  }
}

@media (prefers-reduced-motion: no-preference) {
  .gallery__track {
    scroll-behavior: smooth;
  }
}

@media (prefers-reduced-motion: reduce) {
  .gallery__thumb {
    transition: none;
  }

  .gallery__thumb:hover {
    scale: 1;
  }
}
</style>
