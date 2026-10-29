<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">治理</p>
        <h1>账户管理</h1>
        <p class="sub">按状态与关键词检索账户，封禁或解除封禁；管理员账户不在此处处置。</p>
      </div>
      <div class="page-head-actions">
        <el-button :loading="loading" @click="load">
          <el-icon><AppIcon name="refresh" /></el-icon>
          刷新列表
        </el-button>
      </div>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">状态</span>
          <el-radio-group v-model="statusFilter" class="filter-seg" @change="load">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="normal">正常</el-radio-button>
            <el-radio-button value="banned">已封禁</el-radio-button>
          </el-radio-group>
          <span class="filter-label">关键词</span>
          <el-input
            v-model="keyword"
            placeholder="邮箱 / 显示名称"
            clearable
            class="filter-input"
            @change="load"
            @keyup.enter="load"
          />
          <el-button @click="load">
            <el-icon><AppIcon name="search" /></el-icon>
            查询
          </el-button>
        </div>
        <span class="result-count">共 {{ users.length }} 个账户</span>
      </div>
    </el-card>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
      <template #default>
        <el-button size="small" @click="load">重新加载</el-button>
      </template>
    </el-alert>
    <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon />

    <el-card class="data-card">
      <div class="table-scroll">
        <el-table :data="users" v-loading="loading" class="data-table" row-key="id">
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column prop="email" label="邮箱" width="210" show-overflow-tooltip />
          <el-table-column prop="display_name" label="显示名称" width="130" show-overflow-tooltip />
          <el-table-column label="角色" width="100">
            <template #default="{ row }">
              <span :class="row.role === 'admin' ? 'role-admin' : 'muted-text'">
                {{ row.role === 'admin' ? '管理员' : '用户' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'banned' ? 'danger' : 'success'" effect="light">
                {{ row.status === 'banned' ? '已封禁' : '正常' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="ban_reason" label="封禁理由" min-width="180" show-overflow-tooltip />
          <el-table-column label="封禁时间" width="172">
            <template #default="{ row }">{{ fmt(row.ban_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="188" fixed="right">
            <template #default="{ row }">
              <template v-if="row.role !== 'admin'">
                <el-button
                  v-if="row.status === 'normal'"
                  size="small"
                  type="danger"
                  :loading="actionBusyId === row.id"
                  @click="ban(row)"
                >
                  封禁
                </el-button>
                <el-button
                  v-else
                  size="small"
                  type="success"
                  :loading="actionBusyId === row.id"
                  @click="unban(row)"
                >
                  解除封禁
                </el-button>
              </template>
              <span v-else class="muted-text">管理员账户不可封禁</span>
            </template>
          </el-table-column>

          <template #empty>
            <div class="state-block">
              <span class="state-icon"><AppIcon name="users" :size="24" /></span>
              <p class="state-title">当前筛选下暂无账户</p>
              <el-button size="small" @click="load">刷新列表</el-button>
            </div>
          </template>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import AppIcon from '../components/AppIcon.vue'

const users = ref([])
const loading = ref(false)
const statusFilter = ref('all')
const keyword = ref('')
const loadError = ref('')
const actionError = ref('')
const actionBusyId = ref(null)

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    users.value = await http.get('/admin/users', {
      params: { status: statusFilter.value, keyword: keyword.value || undefined },
    })
  } catch (err) {
    loadError.value = `账户列表加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
}

async function ban(row) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt(`封禁 ${row.display_name}（${row.email}）的理由`, '封禁账户', {
      inputType: 'textarea',
      inputValidator: (v) => (v && v.trim() ? true : '须填写封禁理由'),
    }))
  } catch {
    return
  }
  actionBusyId.value = row.id
  actionError.value = ''
  try {
    const resp = await http.post(`/admin/users/${row.id}/ban`, { reason: value })
    ElMessage.success(`已封禁并开通处置沟通（事项#${resp.case_id}）`)
    load()
  } catch (err) {
    actionError.value = `封禁失败：${serverDetail(err)}`
  } finally {
    actionBusyId.value = null
  }
}

async function unban(row) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt('解除封禁的依据/说明', '解除封禁', {
      inputType: 'textarea',
      inputValidator: (v) => (v && v.trim() ? true : '须填写解除依据'),
    }))
  } catch {
    return
  }
  actionBusyId.value = row.id
  actionError.value = ''
  try {
    await http.post(`/admin/users/${row.id}/unban`, { lift_reason: value })
    ElMessage.success('已解除封禁，原权限与展示资格恢复')
    load()
  } catch (err) {
    actionError.value = `解除封禁失败：${serverDetail(err)}`
  } finally {
    actionBusyId.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.role-admin {
  color: var(--brand-ink);
  font-weight: 600;
  font-size: 12.5px;
}
</style>
