<template>
  <el-card header="账户管理（封禁/解除）">
    <div class="toolbar">
      <el-radio-group v-model="statusFilter" @change="load">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="normal">正常</el-radio-button>
        <el-radio-button value="banned">已封禁</el-radio-button>
      </el-radio-group>
      <el-input v-model="keyword" placeholder="邮箱/名称" style="width: 220px" clearable @change="load" />
      <el-button @click="load">查询</el-button>
    </div>
    <el-table :data="users" v-loading="loading">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="email" label="邮箱" width="200" />
      <el-table-column prop="display_name" label="显示名称" width="120" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'banned' ? 'danger' : 'success'">{{ row.status === 'banned' ? '已封禁' : '正常' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ban_reason" label="封禁理由" min-width="180" show-overflow-tooltip />
      <el-table-column label="封禁时间" width="170">
        <template #default="{ row }">{{ fmt(row.ban_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <template v-if="row.role !== 'admin'">
            <el-button v-if="row.status === 'normal'" size="small" type="danger" @click="ban(row)">封禁</el-button>
            <el-button v-else size="small" type="success" @click="unban(row)">解除封禁</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'

const users = ref([])
const loading = ref(false)
const statusFilter = ref('all')
const keyword = ref('')
const fmt = (v) => (v ? new Date(v).toLocaleString('zh-CN') : '')

async function load() {
  loading.value = true
  try {
    users.value = await http.get('/admin/users', {
      params: { status: statusFilter.value, keyword: keyword.value || undefined },
    })
  } finally {
    loading.value = false
  }
}

async function ban(row) {
  const { value } = await ElMessageBox.prompt(`封禁 ${row.display_name}（${row.email}）的理由`, '封禁账户', {
    inputType: 'textarea',
    inputValidator: (v) => (v && v.trim() ? true : '须填写封禁理由'),
  })
  const resp = await http.post(`/admin/users/${row.id}/ban`, { reason: value })
  ElMessage.success(`已封禁并开通处置沟通（事项#${resp.case_id}）`)
  load()
}

async function unban(row) {
  const { value } = await ElMessageBox.prompt('解除封禁的依据/说明', '解除封禁', {
    inputType: 'textarea',
    inputValidator: (v) => (v && v.trim() ? true : '须填写解除依据'),
  })
  await http.post(`/admin/users/${row.id}/unban`, { lift_reason: value })
  ElMessage.success('已解除封禁，原权限与展示资格恢复')
  load()
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
</style>
