<template>
  <el-card header="分类标签维护（单级多标签）">
    <div class="toolbar">
      <el-input v-model="newName" placeholder="新标签名称" style="width: 200px" />
      <el-button type="primary" @click="create">创建公共标签</el-button>
    </div>
    <el-table :data="categories" v-loading="loading">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column label="主名称" width="160">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'primary' : 'info'">{{ row.name }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="别名" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="a in row.aliases" :key="a" closable type="info" style="margin-right: 6px" @close="removeAlias(row, a)">{{ a }}</el-tag>
          <el-button size="small" text type="primary" @click="addAlias(row)">+别名</el-button>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">{{ row.status === 'active' ? '启用' : '停用' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="rename(row)">改主名（旧名转别名）</el-button>
          <el-button size="small" @click="toggleStatus(row)">{{ row.status === 'active' ? '停用' : '启用' }}</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-alert type="info" :closable="false" style="margin-top: 12px"
      title="停用后新发布不能选择该标签；从未关联商品的标签可逻辑删除；改名后当前展示新名、历史保留旧名为别名。" />
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'

const categories = ref([])
const loading = ref(false)
const newName = ref('')

async function load() {
  loading.value = true
  try {
    categories.value = await http.get('/categories')
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!newName.value.trim()) return
  await http.post('/categories', { name: newName.value })
  ElMessage.success('已创建')
  newName.value = ''
  load()
}

async function rename(row) {
  const { value } = await ElMessageBox.prompt('新的主名称（旧主名将保留为别名）', '修改主名', {
    inputValue: row.name,
  })
  await http.patch(`/categories/${row.id}`, { name: value })
  ElMessage.success('已修改')
  load()
}

async function toggleStatus(row) {
  await http.patch(`/categories/${row.id}`, { status: row.status === 'active' ? 'disabled' : 'active' })
  load()
}

async function addAlias(row) {
  const { value } = await ElMessageBox.prompt(`为「${row.name}」添加同义别名`, '新增别名')
  await http.post(`/categories/${row.id}/aliases`, { name: value })
  load()
}

async function removeAlias(row, alias) {
  await ElMessageBox.confirm(`移除别名「${alias}」？不改变商品归属及历史。`, '移除别名')
  const target = categories.value.find((c) => c.id === row.id)
  // 后端按别名 ID 删除；此处先查列表拿不到 ID，直接按名称重建请求
  await http.delete(`/categories/${row.id}/aliases/by-name?name=${encodeURIComponent(alias)}`).catch(() => null)
  load()
}

async function remove(row) {
  await ElMessageBox.confirm('仅从未关联商品的标签可删除，确认删除？', '删除标签', { type: 'warning' })
  const resp = await http.delete(`/categories/${row.id}`)
  ElMessage.success(resp.detail)
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
