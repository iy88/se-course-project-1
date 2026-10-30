<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">治理</p>
        <h1>举报核查</h1>
        <p class="sub">查看举报对象、原因与公开结果；处置动作在已认领的事项详情内执行。</p>
      </div>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">状态</span>
          <el-radio-group v-model="statusFilter" class="filter-seg" @change="load">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="pending">待处理</el-radio-button>
            <el-radio-button value="processing">处理中</el-radio-button>
            <el-radio-button value="unfounded">不予处理</el-radio-button>
            <el-radio-button value="handled">已处置</el-radio-button>
          </el-radio-group>
        </div>
        <div class="toolbar-actions">
          <span class="result-count">共 {{ reports.length }} 条</span>
          <el-button :loading="loading" @click="load">
            <el-icon><AppIcon name="refresh" /></el-icon><span>刷新</span>
          </el-button>
        </div>
      </div>
    </el-card>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
      <template #default>
        <el-button size="small" @click="load">重新加载</el-button>
      </template>
    </el-alert>

    <el-card class="data-card">
      <div class="table-scroll">
        <el-table :data="reports" v-loading="loading" class="data-table" row-key="id">
          <el-table-column prop="id" label="编号" width="72" />
          <el-table-column label="对象" width="128">
            <template #default="{ row }">
              <span class="mono">{{ row.target_type }}#{{ row.target_id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="举报原因" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="108">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="公开结果" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.result_confirmed">{{ row.public_result }}</span>
              <span v-else class="muted-text">（确认前不可见）</span>
            </template>
          </el-table-column>
          <el-table-column label="提交时间" width="172">
            <template #default="{ row }">{{ fmt(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="126" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="canOpen(row)"
                size="small"
                @click="$router.push(`/cases/${row.case_id}`)"
              >
                查看/处理
              </el-button>
              <el-tooltip v-else-if="row.case_id && row.case_status === 'pending'" content="请先在待处理池认领该事项">
                <span><el-button size="small" disabled>认领后处理</el-button></span>
              </el-tooltip>
              <span v-else-if="row.case_id" class="muted-text">由其他管理员处理</span>
              <span v-else class="muted-text">无关联事项</span>
            </template>
          </el-table-column>

          <template #empty>
            <div class="state-block">
              <span class="state-icon"><AppIcon name="reports" :size="24" /></span>
              <p class="state-title">当前筛选下暂无举报记录</p>
            </div>
          </template>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import http from '../api/http'
import { ensureAdminUser } from '../api/session'
import { fmtTime as fmt } from '../api/time'
import AppIcon from '../components/AppIcon.vue'

const reports = ref([])
const adminId = ref(null)
const canOpen = (row) => row.case_id && row.case_status !== 'pending' && !!adminId.value && row.claimed_by_id === adminId.value
const loading = ref(false)
const statusFilter = ref('all')
const loadError = ref('')

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

const statusLabels = {
  pending: '待处理',
  processing: '处理中',
  unfounded: '不予处理',
  handled: '已处置',
}
const statusLabel = (s) => statusLabels[s] || s
const statusTagType = (s) => {
  if (s === 'pending') return 'warning'
  if (s === 'processing') return 'primary'
  if (s === 'unfounded') return 'info'
  if (s === 'handled') return 'success'
  return 'info'
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    reports.value = await http.get('/admin/reports', { params: { status: statusFilter.value } })
  } catch (err) {
    loadError.value = `举报列表加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  adminId.value = (await ensureAdminUser())?.id || null
  load()
})
</script>
