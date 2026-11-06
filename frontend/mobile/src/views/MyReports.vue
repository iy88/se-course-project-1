<template>
  <div class="reports-page">
    <AppNavBar title="举报记录" />

    <van-tabs v-model:active="tab">
      <van-tab title="我的举报" name="mine" />
      <van-tab title="我收到的" name="received" />
    </van-tabs>

    <div class="view">
      <template v-if="tab === 'mine'">
        <div v-if="mineError" class="error-banner">
          <AppIcon name="alert" :size="18" />
          <span class="error-banner__text">{{ mineError }}</span>
          <van-button size="small" plain type="primary" :loading="mineLoading" @click="loadMine">重试</van-button>
        </div>

        <div v-if="mine.length" class="report-list">
          <article v-for="r in mine" :key="r.id" class="surface report-card">
            <div class="report-card__head">
              <span class="pill" :class="statusTone(r.status)">{{ reportStatusLabels[r.status] }}</span>
              <span class="report-card__target">{{ r.target_title || `${r.target_type} #${r.target_id}` }}<template v-if="r.target_status">（{{ r.target_status }}）</template></span>
              <span class="report-card__time">{{ fmtTime(r.created_at) }}</span>
            </div>

            <p class="report-card__reason"><span class="report-card__label">原因</span>{{ r.reason }}</p>
            <p v-if="r.detail" class="report-card__reason"><span class="report-card__label">说明</span>{{ r.detail }}</p>

            <div v-if="r.evidence_urls?.length" class="report-card__media">
              <van-image
                v-for="(url, index) in r.evidence_urls"
                :key="url"
                :src="url"
                fit="cover"
                class="report-card__media-item"
                @click="previewEvidence(r.evidence_urls, index)"
              />
            </div>

            <div v-if="r.result_confirmed" class="report-card__result">
              <span class="report-card__label">处理结论</span>
              <p>{{ r.status === 'unfounded' ? '不予处理' : (r.public_result || '已处置') }}</p>
              <p v-if="r.result_reason">原因：{{ r.result_reason }}</p>
            </div>

            <div v-for="s in r.supplements" :key="s.id" class="report-card__supplement">
              <span>补充：{{ s.content }}</span>
              <div v-if="s.evidence_urls?.length" class="report-card__media">
                <van-image
                  v-for="(url, index) in s.evidence_urls"
                  :key="url"
                  :src="url"
                  fit="cover"
                  class="report-card__media-item"
                  @click="previewEvidence(s.evidence_urls, index)"
                />
              </div>
            </div>

            <div v-if="supplement.reportId === r.id" class="report-card__editor">
              <TextField :limit="2000"
                v-model="supplement.content"
                type="textarea"
                label="补充内容"
                :rows="3"
                :disabled="supplement.submitting"
                placeholder="补充说明或证据（必填，最多 2000 个字符）"
               />
              <div class="report-card__evidence">
                <span class="report-card__label">截图证据（可选，最多 3 张）</span>
                <van-uploader
                  v-model="supplementFiles"
                  :max-count="3"
                  accept="image/jpeg,image/png,image/webp,image/gif"
                  :max-size="10 * 1024 * 1024"
                  :disabled="supplement.submitting"
                  @oversize="showToast('图片不能超过 10 MiB')"
                />
              </div>
              <p v-if="supplement.error" class="report-card__error">{{ supplement.error }}</p>
              <div class="report-card__editor-actions">
                <van-button size="small" :disabled="supplement.submitting" @click="closeSupplement">取消</van-button>
                <van-button
                  size="small"
                  type="primary"
                  :loading="supplement.submitting"
                  :disabled="supplement.submitting || supplement.outcomeUnknown || !supplement.content.trim()"
                  @click="submitSupplement"
                >
                  提交
                </van-button>
              </div>
            </div>
            <van-button
              v-else-if="canSupplement(r)"
              size="small"
              plain
              type="primary"
              class="report-card__supplement-btn"
              @click="openSupplement(r)"
            >
              补充说明
            </van-button>
          </article>
        </div>

        <div v-else-if="mineLoading" class="tab-loading">
          <van-loading size="18" />
        </div>

        <EmptyState
          v-else-if="mineLoaded && !mineError"
          icon="shield"
          title="暂无举报记录"
        />
      </template>

      <template v-else-if="tab === 'received'">
        <div v-if="receivedError" class="error-banner">
          <AppIcon name="alert" :size="18" />
          <span class="error-banner__text">{{ receivedError }}</span>
          <van-button size="small" plain type="primary" :loading="receivedLoading" @click="loadReceived">
            重试
          </van-button>
        </div>

        <div v-if="received.length" class="report-list">
          <template v-for="r in received" :key="r.id">
            <router-link v-if="r.case_id" :to="`/cases/${r.case_id}`" class="surface report-card report-card--link">
              <div class="report-card__head">
                <span class="report-card__target">{{ r.target_title || `${r.target_type} #${r.target_id}` }}<template v-if="r.target_status">（{{ r.target_status }}）</template></span>
                <span class="report-card__time">{{ fmtTime(r.created_at) }}</span>
              </div>
              <p class="report-card__reason">{{ r.public_result || '已处置' }}</p>
              <div class="report-card__foot">
                <span class="report-card__label">查看处置沟通</span>
                <AppIcon name="chevron-right" :size="16" class="report-card__arrow" />
              </div>
            </router-link>

            <div v-else class="surface report-card">
              <div class="report-card__head">
                <span class="report-card__target">{{ r.target_title || `${r.target_type} #${r.target_id}` }}<template v-if="r.target_status">（{{ r.target_status }}）</template></span>
                <span class="report-card__time">{{ fmtTime(r.created_at) }}</span>
              </div>
              <p class="report-card__reason">{{ r.public_result || '已处置' }}</p>
            </div>
          </template>
        </div>

        <div v-else-if="receivedLoading" class="tab-loading">
          <van-loading size="18" />
        </div>

        <EmptyState
          v-else-if="receivedLoaded && !receivedError"
          icon="info"
          title="暂无我收到的举报"
        />
      </template>
    </div>
  </div>
</template>

<script setup>
import { textError } from '../api/text'
import TextField from '../components/TextField.vue'
import { onMounted, reactive, ref, watch } from 'vue'
import { showImagePreview, showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { uploadImage } from '../api/uploads'
import { createEvidenceUploads } from '../api/evidenceUploads'
import { fmtTime, reportStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'

const PAGE_SIZE = 20

const session = useSession()
const tab = ref('mine')
const mine = ref([])
const received = ref([])
const supplement = reactive({ reportId: null, content: '', error: '', submitting: false, outcomeUnknown: false })

function previewEvidence(urls, index) {
  if (!urls?.length) return
  showImagePreview({ images: urls, startPosition: index || 0, closeable: true })
}
const supplementFiles = ref([])
const evidenceUploads = createEvidenceUploads(uploadImage)
watch(supplementFiles, (items) => evidenceUploads.retain(items), { deep: true, flush: 'sync' })

const mineLoading = ref(false)
const receivedLoading = ref(false)

const mineLoaded = ref(false)
const receivedLoaded = ref(false)

const mineError = ref('')
const receivedError = ref('')


const statusTone = (s) =>
  ({
    pending: 'pill--warn',
    processing: 'pill--info',
    unfounded: '',
    handled: 'pill--ok',
  }[s] || '')

const targetTypeLabels = {
  product: '商品',
  comment: '评论',
  message: '消息',
  review: '评价',
  user: '用户',
}
const targetTypeLabel = (type) => targetTypeLabels[type] || type

function errorText(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (!item || typeof item !== 'object') return ''
        const message = item.msg || item.message
        if (typeof message !== 'string' || !message.trim()) return ''
        const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
        return field ? `${field}：${message}` : message
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
    return fallback
  }
  if (detail && typeof detail === 'object') {
    const message = detail.msg || detail.message
    if (typeof message === 'string' && message.trim()) return message
  }
  return fallback
}

async function loadMine() {
  if (mineLoading.value) return
  mineLoading.value = true
  mineError.value = ''
  try {
    mine.value = await http.get('/reports/mine')
    mineLoaded.value = true
  } catch {
    mineError.value = '我的举报加载失败，请稍后重试。'
  } finally {
    mineLoading.value = false
  }
}

async function loadReceived() {
  if (receivedLoading.value) return
  receivedLoading.value = true
  receivedError.value = ''
  try {
    received.value = await http.get('/reports/received')
    receivedLoaded.value = true
  } catch {
    receivedError.value = '我收到的举报加载失败，请稍后重试。'
  } finally {
    receivedLoading.value = false
  }
}

function canSupplement(report) {
  return ['pending', 'processing'].includes(report.status) && session.user?.status !== 'banned'
}

function openSupplement(report) {
  if (supplement.submitting) return
  evidenceUploads.clear()
  supplement.outcomeUnknown = false
  supplement.reportId = report.id
  supplement.content = ''
  supplement.error = ''
  supplementFiles.value = []
}

function closeSupplement() {
  if (supplement.submitting) return
  evidenceUploads.clear()
  supplement.outcomeUnknown = false
  supplement.reportId = null
  supplement.content = ''
  supplement.error = ''
  supplementFiles.value = []
}

async function submitSupplement() {
  if (!supplement.reportId || supplement.submitting || supplement.outcomeUnknown) return
  const content = supplement.content.trim()
  if (!content) {
    supplement.error = '请填写补充内容后再提交。'
    return
  }
  if (textError(content, 2000)) {
    supplement.error = textError(content, 2000)
    return
  }
  const reportId = supplement.reportId
  supplement.submitting = true
  supplement.error = ''
  try {
    const evidenceKeys = await evidenceUploads.upload(supplementFiles.value)
    try {
      await http.post(`/reports/${reportId}/supplements`, { content, evidence_keys: evidenceKeys })
    } catch (err) {
      if (!err?.response) {
        supplement.outcomeUnknown = true
        throw new Error('提交结果未知，请先查看举报记录，确认未提交后再重新填写。')
      }
      throw err
    }
    evidenceUploads.clear()
    showToast('补充已提交')
    supplement.reportId = null
    supplement.content = ''
    supplementFiles.value = []
    await loadMine()
  } catch (err) {
    supplement.error = errorText(err, err?.message || '补充提交失败，请稍后重试。')
  } finally {
    supplement.submitting = false
  }
}

watch(tab, (value) => {
  if (value === 'mine' && !mineLoaded.value && !mineLoading.value) loadMine()
  if (value === 'received' && !receivedLoaded.value && !receivedLoading.value) loadReceived()
})

onMounted(loadMine)
</script>

<style scoped>
.reports-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.report-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.report-card {
  padding: 13px 14px;
}

.report-card--link {
  display: block;
  color: var(--ink);
  text-decoration: none;
}

.report-card--link:active {
  border-color: var(--line-strong);
}

.report-card__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.report-card__target {
  color: var(--ink-soft);
  font-size: 12.5px;
  font-weight: 600;
}

.report-card__time {
  margin-left: auto;
  color: var(--ink-meta);
  font-size: 11px;
}

.report-card__reason {
  margin: 7px 0 0;
  color: var(--ink);
  font-size: 13.5px;
  line-height: 1.6;
  word-break: break-word;
}

.report-card__label {
  display: inline-block;
  margin-right: 6px;
  color: var(--ink-meta);
  font-size: 11px;
  font-weight: 600;
}

.report-card__result {
  margin-top: 9px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #f7f9f7;
  font-size: 12.5px;
  line-height: 1.55;
}

.report-card__result p {
  margin: 2px 0 6px;
  color: var(--ink-soft);
}

.report-card__supplement {
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px dashed var(--line);
  color: var(--ink-meta);
  font-size: 12px;
  line-height: 1.55;
}

.report-card__supplement-btn {
  margin-top: 9px;
}

.report-card__editor {
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
}

.report-card__editor :deep(.van-field) {
  padding: 7px 0;
}

.report-card__error {
  margin: 4px 0 0;
  color: var(--danger, #b3261e);
  font-size: 12px;
  line-height: 1.5;
}

.report-card__editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.report-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}

.report-card__arrow {
  color: var(--ink-faint);
}

.tab-loading {
  display: flex;
  justify-content: center;
  padding: 26px 0;
}

.public-more {
  margin-top: 12px;
}

.report-card__evidence {
  padding: 4px 0 8px;
}

.report-card__evidence :deep(.van-uploader__upload),
.report-card__evidence :deep(.van-uploader__preview-image) {
  width: 56px;
  height: 56px;
  border-radius: 8px;
}

.report-card__media {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 7px;
}

.report-card__media-item {
  width: 56px;
  height: 56px;
  border-radius: 8px;
  overflow: hidden;
  cursor: zoom-in;
}
</style>
