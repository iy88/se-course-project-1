<template>
  <div class="records-page">
    <AppNavBar title="审核记录" />

    <div class="view">
      <div v-if="error" class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" :loading="loading" @click="load">重新加载</van-button>
      </div>

      <div v-else-if="records.length" class="record-list">
        <article v-for="(record, index) in records" :key="record.id" class="surface record-card">
          <div class="record-card__head">
            <span class="record-card__round">第 {{ index + 1 }} 次审核</span>
            <span class="pill" :class="reviewResultTone(record.result)">
              {{ reviewResultLabels[record.result] || '未知结论' }}
            </span>
          </div>

          <p class="record-card__reason" :class="{ 'record-card__reason--muted': !record.reason }">
            <span v-if="record.reason" class="record-card__label">原因</span>{{ reasonText(record) }}
          </p>

          <div class="record-card__meta">
            <span>提交时间：{{ fmtTime(record.created_at) || '时间未知' }}</span>
            <span v-if="fmtTime(record.reviewed_at)">结论时间：{{ fmtTime(record.reviewed_at) }}</span>
          </div>
        </article>
      </div>

      <div v-else-if="!loaded" class="records-loading">
        <van-loading size="18" />
      </div>

      <EmptyState v-else icon="comment" title="暂无审核记录" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fmtTime, reviewResultLabels, reviewResultTone } from '../api/labels'

const route = useRoute()
const records = ref([])
const loaded = ref(false)
const loading = ref(false)
const error = ref('')

function reasonText(record) {
  if (record.reason) return record.reason
  if (record.result === 'pending') return '审核中，尚未给出结论'
  return '本次审核未记录原因'
}

async function load() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await http.get(`/products/${route.params.id}/review-records`)
    records.value = Array.isArray(data) ? data : []
    loaded.value = true
  } catch {
    error.value = '审核记录加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => route.params.id, load)
</script>

<style scoped>
.records-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.record-card {
  padding: 13px 14px;
}

.record-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.record-card__round {
  color: var(--ink);
  font-size: 13.5px;
  font-weight: 650;
}

.record-card__reason {
  margin: 7px 0 0;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.record-card__reason--muted {
  color: var(--ink-meta);
}

.record-card__label {
  display: inline-block;
  margin-right: 6px;
  color: var(--ink-meta);
  font-size: 11px;
  font-weight: 600;
}

.record-card__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 9px;
  padding-top: 9px;
  border-top: 1px solid var(--line);
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.5;
}

.records-loading {
  display: flex;
  justify-content: center;
  padding: 26px 0;
}
</style>
