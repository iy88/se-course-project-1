<script setup lang="ts">
/*
 * Square avatar cropper.
 *
 * The picked image is previewed inside a square stage: drag to move it, use the
 * wheel or two-finger pinch to zoom. Confirming exports the visible square as a
 * 256×256 JPEG so the upload carries exactly what the user approved; cancelling
 * skips the upload entirely. The upload itself stays outside this component so the
 * caller keeps owning the file-purpose and profile call sequence.
 */
import { nextTick, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{ file: File | null; busy?: boolean }>();
const emit = defineEmits<{ confirm: [file: File]; cancel: [] }>();

/** Internal output resolution; matches the repository-wide avatar size. */
const OUTPUT = 256;
const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const PINCH_SENSITIVITY = 1.8;

const canvas = ref<HTMLCanvasElement | null>(null);
const zoom = ref(MIN_ZOOM);
const dragging = ref(false);
const loadFailed = ref(false);

let image: HTMLImageElement | null = null;
let offsetX = 0;
let offsetY = 0;
let generation = 0;
const pointers = new Map<number, { x: number; y: number }>();
let pinch: { distance: number; zoom: number } | null = null;

function clampOffsets(): void {
  if (!image) return;
  const scale = Math.max(OUTPUT / image.naturalWidth, OUTPUT / image.naturalHeight) * zoom.value;
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  offsetX = Math.max(-(width - OUTPUT) / 2, Math.min((width - OUTPUT) / 2, offsetX));
  offsetY = Math.max(-(height - OUTPUT) / 2, Math.min((height - OUTPUT) / 2, offsetY));
}

function draw(): void {
  const target = canvas.value;
  if (!target || !image) return;
  clampOffsets();
  const scale = Math.max(OUTPUT / image.naturalWidth, OUTPUT / image.naturalHeight) * zoom.value;
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  const context = target.getContext("2d");
  if (!context) return;
  context.fillStyle = "#edf1ee";
  context.fillRect(0, 0, OUTPUT, OUTPUT);
  context.drawImage(
    image,
    (OUTPUT - width) / 2 + offsetX,
    (OUTPUT - height) / 2 + offsetY,
    width,
    height,
  );
}

watch(
  () => props.file,
  async (file) => {
    const current = ++generation;
    image = null;
    loadFailed.value = false;
    if (!file) return;
    const url = URL.createObjectURL(file);
    try {
      const loaded = new Image();
      loaded.src = url;
      await loaded.decode();
      if (current !== generation) return;
      image = loaded;
      zoom.value = MIN_ZOOM;
      offsetX = 0;
      offsetY = 0;
      pointers.clear();
      pinch = null;
      dragging.value = false;
      await nextTick();
      draw();
    } catch {
      if (current === generation) loadFailed.value = true;
    } finally {
      URL.revokeObjectURL(url);
    }
  },
);

onBeforeUnmount(() => {
  generation += 1;
});

function applyZoom(requested: number): void {
  const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, requested));
  const ratio = next / zoom.value;
  offsetX *= ratio;
  offsetY *= ratio;
  zoom.value = next;
  draw();
}

function onPointerDown(event: PointerEvent): void {
  if (props.busy || !image || pointers.size >= 2) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  dragging.value = true;
  pinch = pointers.size === 2 ? { distance: pinchDistance(), zoom: zoom.value } : null;
  (event.target as Element).setPointerCapture?.(event.pointerId);
}

function pinchDistance(): number {
  const points = [...pointers.values()];
  if (points.length < 2) return 0;
  return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
}

function onPointerMove(event: PointerEvent): void {
  const previous = pointers.get(event.pointerId);
  if (!previous || props.busy) return;
  const others = [...pointers.entries()].filter(([id]) => id !== event.pointerId);
  if (others.length > 0) {
    const other = others[0][1];
    const distance = Math.hypot(event.clientX - other.x, event.clientY - other.y);
    if (pinch && pinch.distance > 0) {
      applyZoom(pinch.zoom * (distance / pinch.distance) ** PINCH_SENSITIVITY);
    }
  } else {
    offsetX += event.clientX - previous.x;
    offsetY += event.clientY - previous.y;
    draw();
  }
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
}

function onPointerUp(event: PointerEvent): void {
  pointers.delete(event.pointerId);
  pinch = pointers.size === 2 ? { distance: pinchDistance(), zoom: zoom.value } : null;
  if (pointers.size === 0) dragging.value = false;
}

function onWheel(event: WheelEvent): void {
  if (props.busy) return;
  event.preventDefault();
  applyZoom(zoom.value * (event.deltaY < 0 ? 1.1 : 1 / 1.1));
}

function reset(): void {
  generation += 1;
  image = null;
  zoom.value = MIN_ZOOM;
  offsetX = 0;
  offsetY = 0;
  pointers.clear();
  pinch = null;
  dragging.value = false;
  loadFailed.value = false;
}

function cancel(): void {
  reset();
  emit("cancel");
}

async function confirm(): Promise<void> {
  const target = canvas.value;
  if (!target || !image) return;
  const blob = await new Promise<Blob | null>((resolve) =>
    target.toBlob(resolve, "image/jpeg", 0.9),
  );
  if (!blob) return;
  const name = (props.file?.name ?? "avatar").replace(/\.[^.]+$/, "") || "avatar";
  reset();
  emit("confirm", new File([blob], `${name}.jpg`, { type: "image/jpeg" }));
}
</script>

<template>
  <div class="cropper" role="dialog" aria-modal="true" aria-label="裁剪头像">
    <section class="cropper__panel">
      <h2>裁剪头像</h2>
      <p class="muted">拖动图片调整位置，滚轮或双指捏合缩放。</p>
      <div class="cropper__stage" :class="{ 'cropper__stage--dragging': dragging }">
        <canvas
          ref="canvas"
          :width="OUTPUT"
          :height="OUTPUT"
          aria-label="头像裁剪预览"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
          @lostpointercapture="onPointerUp"
          @wheel.prevent="onWheel"
        />
      </div>
      <p class="muted">方框内为最终头像，输出 256 × 256。</p>
      <p v-if="loadFailed" class="field__error" role="alert">图片无法读取，请重新选择。</p>
      <div class="inline cropper__actions">
        <button type="button" class="btn btn--ghost" :disabled="busy" @click="cancel">取消</button>
        <button
          type="button"
          class="btn btn--primary"
          :disabled="busy || loadFailed || !file"
          @click="confirm"
        >
          {{ busy ? "处理中…" : "使用这张头像" }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.cropper {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: rgb(20 28 24 / 55%);
}

.cropper__panel {
  inline-size: min(22rem, 100%);
  padding: var(--space-5);
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.cropper__panel h2 {
  margin: 0 0 var(--space-2);
  font-size: 1.05rem;
}

.cropper__stage {
  display: grid;
  place-items: center;
  margin-block: var(--space-3);
  aspect-ratio: 1;
  overflow: hidden;
  background: var(--surface-sunken);
  border-radius: var(--radius-md);
  cursor: grab;
  touch-action: none;
}

.cropper__stage--dragging {
  cursor: grabbing;
}

.cropper__stage canvas {
  inline-size: 100%;
  block-size: 100%;
  display: block;
}

.cropper__actions {
  justify-content: flex-end;
  margin-block-start: var(--space-3);
}
</style>
