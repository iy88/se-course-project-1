<template>
  <el-card>
    <div class="toolbar">
      <el-radio-group v-model="statusFilter" @change="load">
        <el-radio-button value="pending">待认领</el-radio-button>
        <el-radio-button value="processing">处理中</el-radio-button>
        <el-radio-button value="disposed">已处置</el-radio-button>
        <el-radio-button value="all">全部</el-radio-button>
      </el-radio-group>
      <el-select v-model="typeFilter" clearable placeholder="事项类型" style="width: 160px" @change="load">
        <el-option label="商品审核" value="product_review" />
        <el-option label="举报事项" value="report" />
        <el-option label="交易争议" value="trade_dispute" />
        <el-option label="异常交易" value="abnormal_trade" />
        <el-option label="账户封禁" value="account_ban" />
      </el-select>
    </div>
    <el-table :data="cases" v-loading="loading">
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">{{ typeLabel(row.case_type) }}</template>
      </el-table-column>
      <el-table-column prop="title" label="事项" min-width="240" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'pending' ? 'warning' : row.status === 'processing' ? 'primary' : 'success'">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="claimed_by_id" label="认领人" width="90" />
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ fmt(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/cases/${row.id}`)">详情</el-button>
          <el-button v-if="row.status === 'pending'" size="small" type="primary" @click="claim(row)">认领</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/http'

const cases = ref([])
const loading = ref(false)
const statusFilter = ref('pending')
const typeFilter = ref('')

async function load() {
  loading.value = true
  try {
    const params = { status: statusFilter.value }
    if (typeFilter.value) params.case_type = typeFilter.value
    cases.value = await http.get('/admin/cases', { params })
  } finally {
    loading.value = false
  }
}

async function claim(row) {
  await http.post(`/admin/cases/${row.id}/claim`)
  ElMessage.success('认领成功')
  load()
}

const typeLabels = {
  product_review: '商品审核',
  report: '举报事项',
  trade_dispute: '交易争议',
  abnormal_trade: '异常交易',
  account_ban: '账户封禁',
}
const typeLabel = (t) => typeLabels[t] || t
const statusLabel = (s) => ({ pending: '待认领', processing: '处理中', disposed: '已处置' }[s] || s)
const fmt = (v) => (v ? new Date(v).toLocaleString('zh-CN') : '')

onMounted(load)
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
