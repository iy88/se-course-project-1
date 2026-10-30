<template>
  <van-popup class="avatar-crop-dialog" :show="!!image" position="center" round :close-on-click-overlay="!busy" @click-overlay="cancel">
    <section class="avatar-cropper">
      <h2>裁切头像</h2><p>拖动图片调整位置，双指捏合或滚轮缩放</p>
      <div class="crop-stage" :class="{ 'is-dragging': isDragging }">
        <canvas ref="canvas" width="360" height="360" aria-label="头像裁切预览" @pointerdown="startDrag" @pointermove="drag" @pointerup="endDrag" @pointercancel="endDrag" @lostpointercapture="endDrag" @wheel.prevent="wheel" />
        <div class="crop-frame" aria-hidden="true"><i class="grid-v first" /><i class="grid-v second" /><i class="grid-h first" /><i class="grid-h second" /></div>
      </div>
      <p class="crop-hint">虚线框内为最终头像 · 256 × 256</p>
      <div class="crop-actions"><van-button round :disabled="busy" @click="cancel">取消</van-button><van-button round type="primary" :loading="busy" @click="confirm">保存并提交审核</van-button></div>
    </section>
  </van-popup>
</template>
<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { showToast } from 'vant'
const props = defineProps({ file: File, busy: Boolean })
const emit = defineEmits(['confirm', 'cancel'])
const canvas = ref(null)
const image = ref(null)
const zoom = ref(1)
const isDragging = ref(false)
let offsetX = 0, offsetY = 0, generation = 0
const pointers = new Map()
const PINCH_SENSITIVITY = 1.8
let pinchStart = null
function resetPinch() {
  const points = [...pointers.values()]
  pinchStart = points.length === 2
    ? { distance: Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y), zoom: zoom.value }
    : null
}
watch(() => props.file, async file => {
  const current = ++generation
  image.value = null
  if (!file) return
  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    img.src = url
    await img.decode()
    if (current !== generation) return
    image.value = img
    zoom.value = 1
    offsetX = offsetY = 0
    pointers.clear()
    pinchStart = null
    isDragging.value = false
    await nextTick()
    draw()
  } catch { showToast('图片无法读取，请重新选择'); emit('cancel') }
  finally { URL.revokeObjectURL(url) }
})
onBeforeUnmount(() => { generation++ })
function draw() {
  if (!canvas.value || !image.value) return
  const img = image.value
  const scale = Math.max(256 / img.naturalWidth, 256 / img.naturalHeight) * zoom.value
  const width = img.naturalWidth * scale, height = img.naturalHeight * scale
  offsetX = Math.max(-(width - 256) / 2, Math.min((width - 256) / 2, offsetX))
  offsetY = Math.max(-(height - 256) / 2, Math.min((height - 256) / 2, offsetY))
  const ctx = canvas.value.getContext('2d')
  ctx.fillStyle = '#edf1ee'
  ctx.fillRect(0, 0, 360, 360)
  ctx.drawImage(img, (360 - width) / 2 + offsetX, (360 - height) / 2 + offsetY, width, height)
}
function startDrag(event) {
  if (props.busy || pointers.size >= 2) return
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  isDragging.value = true
  resetPinch()
  event.target.setPointerCapture(event.pointerId)
}
function drag(event) {
  const previous = pointers.get(event.pointerId)
  if (!previous || props.busy) return
  const others = [...pointers.entries()].filter(([id]) => id !== event.pointerId)
  if (others.length) {
    const other = others[0][1]
    const distance = Math.hypot(event.clientX - other.x, event.clientY - other.y)
    if (pinchStart?.distance > 0) {
      const requested = pinchStart.zoom * (distance / pinchStart.distance) ** PINCH_SENSITIVITY
      const nextZoom = Math.max(1, Math.min(4, requested))
      const ratio = nextZoom / zoom.value
      offsetX *= ratio
      offsetY *= ratio
      zoom.value = nextZoom
      // 到达边界时重设基准，反向捏合立即响应。
      if (requested !== nextZoom) pinchStart = { distance, zoom: nextZoom }
    }
  } else {
    const ratio = 360 / canvas.value.getBoundingClientRect().width
    offsetX += (event.clientX - previous.x) * ratio
    offsetY += (event.clientY - previous.y) * ratio
  }
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  draw()
}
function endDrag(event) {
  pointers.delete(event.pointerId)
  resetPinch()
  isDragging.value = pointers.size > 0
}
function wheel(event) {
  if (props.busy) return
  zoom.value = Math.max(1, Math.min(4, zoom.value * Math.exp(-event.deltaY * (event.ctrlKey ? 0.008 : 0.003))))
  draw()
}
function cancel() { if (!props.busy) emit('cancel') }
function confirm() {
  if (props.busy || !canvas.value) return
  const output = document.createElement('canvas')
  output.width = output.height = 256
  output.getContext('2d').drawImage(canvas.value, 52, 52, 256, 256, 0, 0, 256, 256)
  output.toBlob(blob => {
    if (blob) emit('confirm', new File([blob], 'avatar.jpg', { type: 'image/jpeg' }))
    else showToast('裁切失败，请重新选择图片')
  }, 'image/jpeg', 0.9)
}
</script>
<style scoped>
.avatar-crop-dialog { width: min(calc(100vw - 24px), var(--content, 760px)); max-height: calc(100dvh - 32px); overflow-y: auto; }
.avatar-cropper { padding: 28px 24px; text-align: center; }
h2 { margin: 0 0 8px; font-size: 21px; }
p { margin: 0 0 20px; color: #718078; font-size: 13px; line-height: 1.6; }
.crop-stage { position: relative; width: min(360px, 100%); aspect-ratio: 1; margin: 0 auto; overflow: hidden; border-radius: 16px; background: #edf1ee; }
canvas { display: block; width: 100%; height: 100%; touch-action: none; cursor: grab; }
canvas:active { cursor: grabbing; }
.crop-frame { position: absolute; box-sizing: border-box; inset: 14.444444%; border: 2px dashed rgba(255,255,255,.96); box-shadow: 0 0 0 180px rgba(12,25,20,.48); pointer-events: none; transition: box-shadow .18s ease; }
.is-dragging .crop-frame { box-shadow: 0 0 0 180px rgba(12,25,20,.2); }
.crop-frame i { position: absolute; display: block; background: rgba(255,255,255,.5); }
.grid-v { top: 0; bottom: 0; width: 1px; }
.grid-h { left: 0; right: 0; height: 1px; }
.grid-v.first { left: 33.333%; } .grid-v.second { left: 66.667%; }
.grid-h.first { top: 33.333%; } .grid-h.second { top: 66.667%; }
.crop-hint { margin: 12px 0 0; font-size: 12px; }
.crop-actions { margin-top: 24px; display: flex; justify-content: center; gap: 12px; }
.crop-actions .van-button { min-width: 96px; }
@media (max-width: 359px) { .avatar-cropper { padding: 22px 16px; } }
</style>
