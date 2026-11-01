<template>
  <van-popup
    :show="show"
    position="bottom"
    round
    class="app-bottom-popup"
    :close-on-click-overlay="!busy"
    @update:show="(value) => emit('update:show', value)"
    @closed="reset"
  >
    <div class="popup-panel report-dialog">
      <h3>{{ title }}</h3>
      <p class="report-dialog__hint">填写举报原因；补充说明与截图证据可选，证据仅管理员可见。</p>
      <van-field
        v-model="reason"
        label="原因"
        type="textarea"
        rows="2"
        maxlength="500"
        show-word-limit
        required
        placeholder="请填写举报原因（必填）"
        :disabled="busy"
      />
      <van-field
        v-model="detail"
        label="补充说明"
        type="textarea"
        rows="3"
        maxlength="2000"
        show-word-limit
        placeholder="补充说明（可选，最多 2000 字）"
        :disabled="busy"
      />
      <div class="report-dialog__evidence">
        <span class="report-dialog__label">截图证据（可选，最多 3 张）</span>
        <van-uploader
          v-model="files"
          :max-count="3"
          accept="image/jpeg,image/png,image/webp,image/gif"
          :max-size="10 * 1024 * 1024"
          :disabled="busy"
          @oversize="showToast('图片不能超过 10 MiB')"
        />
      </div>
      <p v-if="error" class="report-dialog__error">{{ error }}</p>
      <div class="report-dialog__actions">
        <van-button block :disabled="busy" @click="close">取消</van-button>
        <van-button block type="primary" :loading="busy" :disabled="busy || outcomeUnknown" @click="submit">提交举报</van-button>
      </div>
    </div>
  </van-popup>
</template>

<script setup>
import { ref, watch } from 'vue'
import { showToast } from 'vant'
import http from '../api/http'
import { uploadImage } from '../api/uploads'
import { createEvidenceUploads } from '../api/evidenceUploads'

const props = defineProps({
  show: { type: Boolean, default: false },
  targetType: { type: String, required: true },
  // 弹窗关闭时父级传入 null；提交前有 targetId 有效性校验兜底
  targetId: { type: [Number, String], default: null },
  title: { type: String, default: '举报' },
})
const emit = defineEmits(['update:show', 'submitted'])

const reason = ref('')
const detail = ref('')
const files = ref([])
const error = ref('')
const busy = ref(false)
const outcomeUnknown = ref(false)
const evidenceUploads = createEvidenceUploads(uploadImage)
watch(files, (items) => evidenceUploads.retain(items), { deep: true, flush: 'sync' })

watch(() => props.show, (open) => {
  if (open) reset()
})

function reset() {
  evidenceUploads.clear()
  outcomeUnknown.value = false
  reason.value = ''
  detail.value = ''
  files.value = []
  error.value = ''
}

function close() {
  if (!busy.value) emit('update:show', false)
}

async function submit() {
  if (busy.value || outcomeUnknown.value) return
  const targetId = Number(props.targetId)
  if (!Number.isInteger(targetId) || targetId <= 0) {
    error.value = '举报对象无效，请刷新后重试。'
    return
  }
  const trimmed = reason.value.trim()
  if (!trimmed) {
    error.value = '请填写举报原因。'
    return
  }
  if (trimmed.length > 500) {
    error.value = '举报原因最多 500 字。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const evidenceKeys = await evidenceUploads.upload(files.value)
    let data
    try {
      data = await http.post('/reports', {
        target_type: props.targetType,
        target_id: targetId,
        reason: trimmed,
        detail: detail.value.trim() || null,
        evidence_keys: evidenceKeys,
      })
    } catch (err) {
      if (!err?.response) {
        outcomeUnknown.value = true
        throw new Error('提交结果未知，请先查看举报记录，确认未提交后再重新填写。')
      }
      throw err
    }
    emit('update:show', false)
    showToast(data.detail || '举报已提交')
    emit('submitted', data)
  } catch (err) {
    error.value = err?.response?.data?.detail || err?.message || '举报提交失败，请稍后重试。'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.report-dialog__hint {
  margin: 0 0 8px;
  color: var(--ink-faint);
  font-size: 12px;
  line-height: 1.6;
}

.report-dialog__evidence {
  padding: 10px 0 4px;
}

.report-dialog__label {
  display: block;
  margin-bottom: 8px;
  color: var(--ink-soft);
  font-size: 12.5px;
  font-weight: 600;
}

.report-dialog__error {
  margin: 6px 0 0;
  color: var(--danger, #b3261e);
  font-size: 12px;
  line-height: 1.5;
}

.report-dialog__actions {
  display: flex;
  gap: 10px;
  padding: 4px 0 0;
}
</style>
