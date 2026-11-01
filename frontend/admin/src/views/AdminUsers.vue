<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">治理</p>
        <h1>账户管理</h1>
      </div>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">状态</span>
          <el-radio-group v-model="statusFilter" class="filter-seg" @change="load(1)">
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
            @change="load(1)"
            @keyup.enter="load(1)"
          />
          <el-button @click="load(1)">
            <el-icon><AppIcon name="search" /></el-icon>
            查询
          </el-button>
        </div>
        <div class="toolbar-actions">
          <span class="result-count">共 {{ total }} 个账户</span>
          <el-button :loading="loading" @click="load()">
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
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import AppIcon from '../components/AppIcon.vue'

const users = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const statusFilter = ref('all')
const keyword = ref('')
const loadError = ref('')
const actionError = ref('')
const actionBusyId = ref(null)

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

async function load(targetPage) {
  const target = Math.max(1, Number(targetPage) || page.value || 1)
  loading.value = true
  loadError.value = ''
  try {
    const data = await http.get('/admin/users', {
      params: {
        page: target,
        page_size: pageSize.value,
        status: statusFilter.value,
        keyword: keyword.value || undefined,
      },
    })
    users.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total) || 0
    page.value = target
  } catch (err) {
    loadError.value = `账户列表加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
}

function onSizeChange(size) {
  pageSize.value = size
  load(1)
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
.list-pagination {
  margin-top: 12px;
  justify-content: flex-end;
  padding: 0 18px 14px 0;
}
</style>
