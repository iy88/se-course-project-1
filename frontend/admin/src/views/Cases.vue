<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">工作台</p>
        <h1>待处理池</h1>
      </div>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">状态</span>
          <el-radio-group v-model="statusFilter" class="filter-seg" @change="load(1)">
            <el-radio-button value="pending">待认领</el-radio-button>
            <el-radio-button value="processing">处理中</el-radio-button>
            <el-radio-button value="disposed">已处置</el-radio-button>
            <el-radio-button value="all">全部</el-radio-button>
          </el-radio-group>
          <span class="filter-label">类型</span>
          <el-select
            v-model="typeFilter"
            clearable
            placeholder="全部事项类型"
            class="filter-select"
            @change="load(1)"
          >
            <el-option label="头像审核" value="avatar_review" />
            <el-option label="商品审核" value="product_review" />
            <el-option label="举报事项" value="report" />
            <el-option label="交易争议" value="trade_dispute" />
            <el-option label="异常交易" value="abnormal_trade" />
            <el-option label="账户封禁" value="account_ban" />
          </el-select>
        </div>
        <div class="toolbar-actions">
          <span class="result-count">共 {{ total }} 条</span>
          <el-button :loading="loading" @click="load()">
            <el-icon><AppIcon name="refresh" /></el-icon><span>刷新</span>
          </el-button>
        </div>
      </div>
    </el-card>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
      <template #default>
        <el-button size="small" @click="load()">重新加载</el-button>
      </template>
    </el-alert>
    <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon />

    <el-card class="data-card">
      <div class="table-scroll">
        <el-table :data="cases" v-loading="loading" class="data-table" row-key="id">
          <el-table-column prop="id" label="编号" width="72" />
          <el-table-column label="类型" width="112">
            <template #default="{ row }">{{ typeLabel(row.case_type) }}</template>
          </el-table-column>
          <el-table-column prop="title" label="事项" min-width="240">
            <template #default="{ row }">
              <span class="case-title">{{ row.title }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="102">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="认领人" width="96">
            <template #default="{ row }">
              <span v-if="row.claimed_by_id">#{{ row.claimed_by_id }}</span>
              <span v-else class="muted-text">未认领</span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="172">
            <template #default="{ row }">{{ fmt(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="224" fixed="right">
            <template #default="{ row }">
              <el-button v-if="canOpen(row)" size="small" @click="$router.push(`/cases/${row.id}`)">
                详情
              </el-button>
              <el-button v-else size="small" disabled>
                {{ row.status === 'pending' ? '认领后查看' : '仅认领人查看' }}
              </el-button>
              <el-button v-if="row.status === 'pending'" size="small" type="primary" @click="claim(row)">
                认领
              </el-button>
            </template>
          </el-table-column>

          <template #empty>
            <div class="state-block">
              <span class="state-icon"><AppIcon name="cases" :size="24" /></span>
              <p class="state-title">当前筛选下暂无事项</p>
            </div>
          </template>
        </el-table>
      </div>

      <el-pagination
        class="list-pagination"
        layout="total, sizes, prev, pager, next"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :disabled="loading"
        @current-change="load"
        @size-change="onSizeChange"
      />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ensureAdminUser } from '../api/session'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import AppIcon from '../components/AppIcon.vue'

const cases = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const statusFilter = ref('pending')
const typeFilter = ref('')
const adminId = ref(null)
const loadError = ref('')
const actionError = ref('')

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

async function load(targetPage) {
  const target = Math.max(1, Number(targetPage) || page.value || 1)
  loading.value = true
  loadError.value = ''
  try {
    const params = { page: target, page_size: pageSize.value, status: statusFilter.value }
    if (typeFilter.value) params.case_type = typeFilter.value
    const data = await http.get('/admin/cases', { params })
    cases.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total) || 0
    page.value = target
  } catch (err) {
    loadError.value = `事项列表加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
}

function onSizeChange(size) {
  pageSize.value = size
  load(1)
}

async function claim(row) {
  actionError.value = ''
  try {
    await http.post(`/admin/cases/${row.id}/claim`)
    ElMessage.success('认领成功')
    load()
  } catch (err) {
    actionError.value = `认领失败：${serverDetail(err)}`
  }
}

const canOpen = (row) => row.status !== 'pending' && !!adminId.value && row.claimed_by_id === adminId.value

const typeLabels = {
  avatar_review: '头像审核',
  product_review: '商品审核',
  report: '举报事项',
  trade_dispute: '交易争议',
  abnormal_trade: '异常交易',
  account_ban: '账户封禁',
}
const typeLabel = (t) => typeLabels[t] || t
const statusLabel = (s) => ({ pending: '待认领', processing: '处理中', disposed: '已处置' }[s] || s)
const statusTagType = (s) => {
  if (s === 'pending') return 'warning'
  if (s === 'processing') return 'primary'
  if (s === 'disposed') return 'success'
  return 'info'
}

onMounted(async () => {
  adminId.value = (await ensureAdminUser())?.id || null
  load()
})
</script>

<style scoped>
.case-title {
  color: var(--ink);
  font-weight: 550;
}
.list-pagination {
  margin-top: 12px;
  justify-content: flex-end;
  padding: 0 18px 14px 0;
}
</style>
