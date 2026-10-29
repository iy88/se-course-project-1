<template>
  <div class="reports-page">
    <AppNavBar title="我的举报 / 我收到的举报" />

    <van-tabs v-model:active="tab">
      <van-tab title="我的举报" name="mine" />
      <van-tab title="我收到的" name="received" />
    </van-tabs>

    <div class="view">
      <div v-if="error" class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>

      <template v-else-if="tab === 'mine'">
        <div v-if="mine.length" class="report-list">
          <article v-for="r in mine" :key="r.id" class="surface report-card">
            <div class="report-card__head">
              <span class="pill" :class="statusTone(r.status)">{{ reportStatusLabels[r.status] }}</span>
              <span class="report-card__target">{{ r.target_type }} #{{ r.target_id }}</span>
              <span class="report-card__time">{{ fmtTime(r.created_at) }}</span>
            </div>

            <p class="report-card__reason"><span class="report-card__label">原因</span>{{ r.reason }}</p>

            <div v-if="r.result_confirmed" class="report-card__result">
              <span class="report-card__label">处理结论</span>
              <p>{{ r.public_result || '—' }}</p>
              <van-button
                v-if="r.case_id && r.status === 'processing' && session.user?.status !== 'banned'"
                size="small"
                plain
                type="primary"
                @click="supplement(r)"
              >
                补充说明
              </van-button>
            </div>

            <div v-for="s in r.supplements" :key="s.id" class="report-card__supplement">
              补充：{{ s.content }}
            </div>
          </article>
        </div>

        <EmptyState
          v-else-if="loaded"
          icon="shield"
          title="暂无举报记录"
        />
      </template>

      <template v-else>
        <div v-if="received.length" class="report-list">
          <template v-for="r in received" :key="r.id">
            <router-link v-if="r.case_id" :to="`/cases/${r.case_id}`" class="surface report-card report-card--link">
              <div class="report-card__head">
                <span class="report-card__target">{{ r.target_type }} #{{ r.target_id }}</span>
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
                <span class="report-card__target">{{ r.target_type }} #{{ r.target_id }}</span>
                <span class="report-card__time">{{ fmtTime(r.created_at) }}</span>
              </div>
              <p class="report-card__reason">{{ r.public_result || '已处置' }}</p>
            </div>
          </template>
        </div>

        <EmptyState
          v-else-if="loaded"
          icon="info"
          title="暂无我收到的举报"
          hint="仅显示已实际处置的事项；问询阶段请从问询通知进入。"
        />
      </template>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { showDialog } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fmtTime, reportStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'

const tab = ref('mine')
const mine = ref([])
const received = ref([])
const session = useSession()
const error = ref('')
const loaded = ref(false)

const statusTone = (s) =>
  ({
    pending: 'pill--warn',
    processing: 'pill--info',
    unfounded: '',
    handled: 'pill--ok',
  }[s] || '')

async function load() {
  error.value = ''
  try {
    mine.value = await http.get('/reports/mine')
    received.value = await http.get('/reports/received')
    loaded.value = true
  } catch {
    error.value = '举报记录加载失败，请稍后重试。'
  }
}

async function supplement(r) {
  const { value } = await showDialog({
    title: '补充说明或证据',
    message: '同一事项内补充，结案后不再接受。',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (!value) return
  await http.post(`/reports/${r.id}/supplements`, { content: value })
  load()
}

onMounted(load)
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
</style>
