<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">概览</p>
        <h1>数据统计</h1>
        <p class="sub">按查询时点查看用户、待处理事项与商品/交易状态分布；可指定范围统计完成交易。</p>
      </div>
      <div class="page-head-actions">
        <el-button :loading="loading" @click="load">
          <el-icon><AppIcon name="refresh" /></el-icon>
          刷新
        </el-button>
      </div>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">统计范围</span>
          <el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            class="range-picker"
          />
          <el-button @click="clearRange">全部</el-button>
        </div>
        <el-button type="primary" :loading="loading" @click="load">
          <el-icon><AppIcon name="search" /></el-icon>
          查询
        </el-button>
      </div>
    </el-card>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
      <template #default>
        <el-button size="small" @click="load">重新加载</el-button>
      </template>
    </el-alert>

    <section class="stat-grid" v-loading="loading">
      <div class="stat-card">
        <el-statistic title="用户总数" :value="stats.users?.total ?? 0" />
      </div>
      <div class="stat-card">
        <el-statistic title="封禁账户" :value="stats.users?.banned ?? 0" />
      </div>
      <div class="stat-card">
        <el-statistic title="待处理审核" :value="stats.pending?.review_cases ?? 0" />
      </div>
      <div class="stat-card">
        <el-statistic title="待处理举报" :value="stats.pending?.report_cases ?? 0" />
      </div>
      <div v-if="stats.range?.completed_trades != null" class="stat-card is-range">
        <el-statistic
          :title="`范围完成交易（${stats.range.from || '…'} ~ ${stats.range.to || '…'}）`"
          :value="stats.range.completed_trades"
        />
      </div>
    </section>

    <div class="split-grid">
      <el-card>
        <template #header>
          <div class="card-head-row">
            <div>
              <span class="card-title">商品状态分布</span>
              <span class="card-sub">按商品当前状态统计</span>
            </div>
            <span class="result-count">{{ productEntries.length }} 项</span>
          </div>
        </template>
        <div v-if="productEntries.length" class="dist-grid">
          <div v-for="[key, value] in productEntries" :key="key" class="dist-item">
            <span class="dist-label">{{ productLabel(key) }}</span>
            <span class="dist-value">{{ value }}</span>
          </div>
        </div>
        <div v-else class="state-block">
          <span class="state-icon"><AppIcon name="products" :size="24" /></span>
          <p class="state-title">暂无商品状态数据</p>
        </div>
      </el-card>

      <el-card>
        <template #header>
          <div class="card-head-row">
            <div>
              <span class="card-title">交易状态分布</span>
              <span class="card-sub">按交易当前状态统计</span>
            </div>
            <span class="result-count">{{ tradeEntries.length }} 项</span>
          </div>
        </template>
        <div v-if="tradeEntries.length" class="dist-grid">
          <div
            v-for="[key, value] in tradeEntries"
            :key="key"
            class="dist-item"
            :class="{ 'is-danger': key === 'terminated' }"
          >
            <span class="dist-label">{{ tradeLabel(key) }}</span>
            <span class="dist-value">{{ value }}</span>
          </div>
        </div>
        <div v-else class="state-block">
          <span class="state-icon"><AppIcon name="trades" :size="24" /></span>
          <p class="state-title">暂无交易状态数据</p>
        </div>
      </el-card>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="统计不包含真实付款金额或流水；状态数量按查询时点，范围统计按结果确认时间。"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import http from '../api/http'
import AppIcon from '../components/AppIcon.vue'

const stats = ref({ users: {}, products: {}, pending: {}, trades: {}, range: {} })
const range = ref(null)
const loading = ref(false)
const loadError = ref('')

const productEntries = computed(() => Object.entries(stats.value.products || {}))
const tradeEntries = computed(() => Object.entries(stats.value.trades || {}))

const productLabels = {
  pending_review: '待审核',
  rejected: '审核未通过',
  listed: '公开可交易',
  in_transaction: '交易中',
  delisted: '已下架',
  display_restricted: '停止公开',
}
const tradeLabels = {
  pending_acceptance: '待接受',
  rejected: '已拒绝',
  withdrawn: '已撤回',
  closed: '已关闭',
  in_progress: '进行中',
  disputed: '有争议',
  abnormal: '异常交易',
  terminated: '已终止（失败）',
  completed: '已完成',
  frozen_current: '冻结中',
}
const productLabel = (k) => productLabels[k] || k
const tradeLabel = (k) => tradeLabels[k] || k

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

function clearRange() {
  range.value = null
  load()
}

async function load() {
  loading.value = true
  loadError.value = ''
  const params = {}
  if (range.value && range.value.length === 2) {
    params.from = range.value[0]
    params.to = range.value[1]
  }
  try {
    stats.value = await http.get('/admin/stats', { params })
  } catch (err) {
    loadError.value = `统计数据加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.range-picker {
  width: 300px;
  max-width: 100%;
}

@media (max-width: 900px) {
  .range-picker {
    width: 100%;
  }
}
</style>
