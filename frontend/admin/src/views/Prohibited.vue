<template>
  <el-card header="禁发范围维护（登录用户发布前可查看）">
    <div class="toolbar">
      <el-button type="primary" @click="openCreate">新增条目</el-button>
    </div>
    <el-table :data="items" v-loading="loading">
      <el-table-column prop="group_name" label="类别" width="220" />
      <el-table-column prop="content" label="细目" min-width="300" />
      <el-table-column prop="sort" label="排序" width="70" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑条目' : '新增条目'" width="480px">
      <el-form label-position="top">
        <el-form-item label="类别（如：危险品与管制物品）">
          <el-input v-model="form.group_name" />
        </el-form-item>
        <el-form-item label="细目">
          <el-input v-model="form.content" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'

const items = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = reactive({ id: null, group_name: '', content: '', sort: 0 })

async function load() {
  loading.value = true
  try {
    items.value = await http.get('/prohibited-items')
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
  if (form.id) await http.put(`/prohibited-items/${form.id}`, payload)
  else await http.post('/prohibited-items', payload)
  ElMessage.success('已保存，登录用户可查看最新范围')
  dialogVisible.value = false
  load()
}

async function remove(row) {
  await ElMessageBox.confirm('确认删除该禁发条目？', '删除', { type: 'warning' })
  await http.delete(`/prohibited-items/${row.id}`)
  load()
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  margin-bottom: 12px;
}
</style>
