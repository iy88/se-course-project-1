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
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{ file: File | null; busy?: boolean }>();
const emit = defineEmits<{ confirm: [file: File]; cancel: [] }>();

/** Internal output resolution; matches the repository-wide avatar size. */
const OUTPUT = 256;
const PREVIEW = 360;
const CROP_INSET = (PREVIEW - OUTPUT) / 2;
const frameInset = `${(CROP_INSET / PREVIEW) * 100}%`;
const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const PINCH_SENSITIVITY = 1.8;

const canvas = ref<HTMLCanvasElement | null>(null);
const dialog = ref<HTMLDialogElement | null>(null);
const zoom = ref(MIN_ZOOM);
const dragging = ref(false);
const ready = ref(false);
const encoding = ref(false);
const error = ref("");

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
  context.fillStyle = "#e1e8e3";
  context.fillRect(0, 0, PREVIEW, PREVIEW);
  context.drawImage(
    image,
    (PREVIEW - width) / 2 + offsetX,
    (PREVIEW - height) / 2 + offsetY,
    width,
    height,
  );
}

watch(
  () => props.file,
  async (file) => {
    const current = ++generation;
    image = null;
    ready.value = false;
    error.value = "";
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
      ready.value = true;
      await nextTick();
      draw();
    } catch {
      if (current === generation) error.value = "图片无法读取，请重新选择。";
    } finally {
      URL.revokeObjectURL(url);
    }
  },
  // The component is created only when a file is already picked, so load it at once.
  { immediate: true },
);

onMounted(() => {
  dialog.value?.showModal();
});

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
  if (props.busy || encoding.value || !image || pointers.size >= 2) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  dragging.value = true;
  pinch = pointers.size === 2 ? { distance: pinchDistance(), zoom: zoom.value } : null;
  (event.target as Element).setPointerCapture?.(event.pointerId);
}

function pointerScale(): number {
  const width = canvas.value?.getBoundingClientRect().width;
  return width ? PREVIEW / width : 1;
}

function pinchDistance(): number {
  const points = [...pointers.values()];
  if (points.length < 2) return 0;
  return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
}

function onPointerMove(event: PointerEvent): void {
  const previous = pointers.get(event.pointerId);
  if (!previous || props.busy || encoding.value) return;
  const others = [...pointers.entries()].filter(([id]) => id !== event.pointerId);
  if (others.length > 0) {
    const other = others[0][1];
    const distance = Math.hypot(event.clientX - other.x, event.clientY - other.y);
    if (pinch && pinch.distance > 0) {
      applyZoom(pinch.zoom * (distance / pinch.distance) ** PINCH_SENSITIVITY);
    }
  } else {
    // Pointer deltas are CSS pixels; the canvas works in output pixels.
    const factor = pointerScale();
    offsetX += (event.clientX - previous.x) * factor;
    offsetY += (event.clientY - previous.y) * factor;
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
  if (props.busy || encoding.value || !image) return;
  applyZoom(zoom.value * (event.deltaY < 0 ? 1.1 : 1 / 1.1));
}

function resetTransform(): void {
  zoom.value = MIN_ZOOM;
  offsetX = 0;
  offsetY = 0;
  draw();
}

function moveWithKeys(event: KeyboardEvent): void {
  if (props.busy || encoding.value || !image) return;
  const directions: Record<string, [number, number]> = {
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
  };
  const direction = directions[event.key];
  if (!direction) return;
  event.preventDefault();
  offsetX += direction[0] * 4;
  offsetY += direction[1] * 4;
  draw();
}

async function confirm(): Promise<void> {
  const target = canvas.value;
  if (!target || !image || props.busy || encoding.value) return;
  encoding.value = true;
  error.value = "";
  const output = document.createElement("canvas");
  output.width = OUTPUT;
  output.height = OUTPUT;
  output
    .getContext("2d")
    ?.drawImage(target, CROP_INSET, CROP_INSET, OUTPUT, OUTPUT, 0, 0, OUTPUT, OUTPUT);
  const blob = await new Promise<Blob | null>((resolve) =>
    output.toBlob(resolve, "image/jpeg", 0.9),
  );
  encoding.value = false;
  if (!blob) {
    error.value = "无法导出裁剪后的图片，请重试。";
    return;
  }
  const name = (props.file?.name ?? "avatar").replace(/\.[^.]+$/, "") || "avatar";
  dialog.value?.close("confirm");
  emit("confirm", new File([blob], `${name}.jpg`, { type: "image/jpeg" }));
}
</script>

<template>
  <dialog
    ref="dialog"
    class="cropper"
    aria-labelledby="avatar-crop-title"
    @close="dialog?.returnValue !== 'confirm' && emit('cancel')"
    @cancel="(busy || encoding) && $event.preventDefault()"
  >
    <h2 id="avatar-crop-title">裁剪头像</h2>
    <p id="avatar-crop-instructions" class="muted">
      拖动图片或按方向键移动。使用滑块、滚轮或双指捏合缩放。
    </p>
    <div
      class="cropper__stage"
      :class="{ 'cropper__stage--dragging': dragging }"
      :style="{ '--crop-inset': frameInset }"
    >
      <canvas
        ref="canvas"
        :width="PREVIEW"
        :height="PREVIEW"
        aria-label="头像裁剪预览"
        aria-describedby="avatar-crop-instructions"
        tabindex="0"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @lostpointercapture="onPointerUp"
        @wheel.prevent="onWheel"
        @keydown="moveWithKeys"
      />
      <div class="cropper__frame" aria-hidden="true" />
    </div>
    <div class="cropper__zoom">
      <label for="avatar-zoom" class="field__label">缩放</label>
      <input
        id="avatar-zoom"
        type="range"
        :min="MIN_ZOOM"
        :max="MAX_ZOOM"
        step="0.01"
        :value="zoom"
        :aria-valuetext="`${Math.round(zoom * 100)}%`"
        :disabled="!ready || busy || encoding"
        @input="applyZoom(($event.target as HTMLInputElement).valueAsNumber)"
      />
      <output for="avatar-zoom" aria-hidden="true">{{ Math.round(zoom * 100) }}%</output>
      <button
        type="button"
        class="btn btn--link"
        :disabled="!ready || busy || encoding"
        @click="resetTransform"
      >
        重置
      </button>
    </div>
    <p class="muted">虚线框内为最终头像，输出 256 × 256。</p>
    <p v-if="error" class="field__error" role="alert">{{ error }}</p>
    <form method="dialog" class="inline cropper__actions">
      <button class="btn btn--ghost" autofocus :disabled="busy || encoding">取消</button>
      <button
        type="button"
        class="btn btn--primary"
        :disabled="!ready || busy || encoding"
        @click="confirm"
      >
        {{ busy || encoding ? "处理中…" : "使用这张头像" }}
      </button>
    </form>
  </dialog>
</template>

<style scoped>
.cropper {
  inline-size: min(26rem, calc(100% - 1.5rem));
  max-block-size: calc(100dvh - 1.5rem);
  padding: clamp(1rem, 4vw, 1.5rem);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  color: var(--ink);
  box-shadow: var(--shadow);
  overscroll-behavior: contain;
}

.cropper::backdrop {
  background: rgb(20 28 24 / 52%);
  overflow: hidden;
  overscroll-behavior: contain;
}

.cropper h2 {
  margin-block-end: var(--space-2);
  font-size: 1.125rem;
}

.cropper__stage {
  position: relative;
  inline-size: min(100%, 22.5rem);
  aspect-ratio: 1;
  margin: var(--space-3) auto;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
}

.cropper__stage canvas {
  display: block;
  inline-size: 100%;
  block-size: 100%;
  cursor: grab;
  touch-action: none;
}

.cropper__stage canvas:focus-visible {
  outline-offset: -3px;
}

.cropper__stage--dragging canvas {
  cursor: grabbing;
}

.cropper__frame {
  position: absolute;
  inset: var(--crop-inset);
  border: 2px dashed white;
  outline: 1px solid rgb(0 0 0 / 45%);
  box-shadow: 0 0 0 25rem rgb(15 29 23 / 56%);
  pointer-events: none;
}

.cropper__frame::before {
  --grid-line: rgb(255 255 255 / 78%);
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(var(--grid-line), var(--grid-line)) 33.333% 0 / 1px 100%,
    linear-gradient(var(--grid-line), var(--grid-line)) 66.667% 0 / 1px 100%,
    linear-gradient(var(--grid-line), var(--grid-line)) 0 33.333% / 100% 1px,
    linear-gradient(var(--grid-line), var(--grid-line)) 0 66.667% / 100% 1px;
  background-repeat: no-repeat;
  filter: drop-shadow(0 0 1px rgb(0 0 0 / 85%));
}

.cropper__zoom {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) 4ch auto;
  align-items: center;
  gap: var(--space-3);
  margin-block: var(--space-3);
  font-size: 0.8125rem;
}

.cropper__zoom input {
  min-inline-size: 0;
  margin: 0;
  accent-color: var(--brand);
}

.cropper__zoom output {
  font-variant-numeric: tabular-nums;
  text-align: end;
}

.cropper__actions {
  justify-content: flex-end;
  margin-block-start: var(--space-4);
}
</style>
