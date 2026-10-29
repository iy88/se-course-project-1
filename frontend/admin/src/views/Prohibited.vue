<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">配置</p>
        <h1>禁发范围</h1>
        <p class="sub">维护登录用户发布前可查看的禁发条目；类别与细目会直接展示给用户。</p>
      </div>
      <div class="page-head-actions">
        <el-button type="primary" @click="openCreate">
          <el-icon><AppIcon name="plus" /></el-icon>
          新增条目
        </el-button>
      </div>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">条目</span>
          <span class="inline-note">按类别分组展示，排序值越小越靠前。</span>
        </div>
        <span class="result-count">共 {{ items.length }} 条</span>
      </div>
    </el-card>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
      <template #default>
        <el-button size="small" @click="load">重新加载</el-button>
      </template>
    </el-alert>

    <el-card class="data-card">
      <div class="table-scroll table-narrow">
        <el-table :data="items" v-loading="loading" class="data-table" row-key="id">
          <el-table-column prop="group_name" label="类别" width="240">
            <template #default="{ row }">
              <span class="group-name">{{ row.group_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="content" label="细目" min-width="320" />
          <el-table-column prop="sort" label="排序" width="80" />
          <el-table-column label="操作" width="156" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>

          <template #empty>
            <div class="state-block">
              <span class="state-icon"><AppIcon name="prohibited" :size="24" /></span>
              <p class="state-title">暂无禁发条目</p>
              <el-button size="small" type="primary" @click="openCreate">新增条目</el-button>
            </div>
          </template>
        </el-table>
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? '编辑条目' : '新增条目'"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="类别（如：危险品与管制物品）" class="span-2">
            <el-input v-model="form.group_name" placeholder="按类别归组展示" />
          </el-form-item>
          <el-form-item label="细目" class="span-2">
            <el-input v-model="form.content" type="textarea" :rows="3" placeholder="具体禁发内容说明" />
          </el-form-item>
          <el-form-item label="排序">
            <el-input-number v-model="form.sort" :min="0" :controls="false" class="sort-input" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import AppIcon from '../components/AppIcon.vue'

const items = ref([])
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const dialogVisible = ref(false)
const form = reactive({ id: null, group_name: '', content: '', sort: 0 })

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    items.value = await http.get('/prohibited-items')
  } catch (err) {
    loadError.value = `禁发条目加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { id: null, group_name: '', content: '', sort: 0 })
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, row)
  dialogVisible.value = true
}

async function save() {
  if (!form.group_name.trim() || !form.content.trim()) return ElMessage.warning('类别与细目不能为空')
  const payload = { group_name: form.group_name, content: form.content, sort: form.sort }
  saving.value = true
  try {
    if (form.id) await http.put(`/prohibited-items/${form.id}`, payload)
    else await http.post('/prohibited-items', payload)
    ElMessage.success('已保存，登录用户可查看最新范围')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm('确认删除该禁发条目？', '删除', { type: 'warning' })
  } catch {
    return
  }
  await http.delete(`/prohibited-items/${row.id}`)
  load()
}

onMounted(load)
</script>

<style scoped>
.group-name {
  color: var(--ink);
  font-weight: 550;
}

.sort-input {
  width: 120px;
}
</style>
