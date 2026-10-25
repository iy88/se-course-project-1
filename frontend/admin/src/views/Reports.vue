<template>
  <el-card header="举报核查（处置动作在事项详情内执行）">
    <el-radio-group v-model="statusFilter" style="margin-bottom: 12px" @change="load">
      <el-radio-button value="all">全部</el-radio-button>
      <el-radio-button value="pending">待处理</el-radio-button>
      <el-radio-button value="processing">处理中</el-radio-button>
      <el-radio-button value="unfounded">不予处理</el-radio-button>
      <el-radio-button value="handled">已处置</el-radio-button>
    </el-radio-group>
    <el-table :data="reports" v-loading="loading">
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column label="对象" width="120">
        <template #default="{ row }">{{ row.target_type }}#{{ row.target_id }}</template>
      </el-table-column>
      <el-table-column prop="reason" label="举报原因" min-width="180" show-overflow-tooltip />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">{{ row.status }}</template>
      </el-table-column>
      <el-table-column label="公开结果" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.result_confirmed ? row.public_result : '（确认前不可见）' }}</template>
      </el-table-column>
      <el-table-column label="提交时间" width="170">
        <template #default="{ row }">{{ fmt(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.case_id" size="small" @click="$router.push(`/cases/${row.case_id}`)">处理</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import http from '../api/http'

const reports = ref([])
const loading = ref(false)
const statusFilter = ref('all')
const fmt = (v) => (v ? new Date(v).toLocaleString('zh-CN') : '')

async function load() {
  loading.value = true
  try {
    reports.value = await http.get('/admin/reports', { params: { status: statusFilter.value } })
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>
