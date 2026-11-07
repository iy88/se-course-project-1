<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">配置</p>
        <h1>分类标签</h1>
      </div>
      <span class="result-count">共 {{ categories.length }} 个标签</span>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">新标签</span>
          <TextInput :limit="64"
            v-model="newName"
            placeholder="输入新标签名称"
            class="filter-input"
            @keyup.enter="create"
           />
          <el-button type="primary" :loading="creating" @click="create">
            <el-icon><AppIcon name="plus" /></el-icon>
            创建公共标签
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
        <el-table :data="categories" v-loading="loading" class="data-table" row-key="id">
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column label="主名称" min-width="260">
            <template #default="{ row }">
              <el-tag
                class="name-tag"
                :type="row.status === 'active' ? 'primary' : 'info'"
                effect="light"
                :title="row.name"
              >{{ row.name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="别名" min-width="240">
            <template #default="{ row }">
              <div class="alias-row">
                <span v-for="a in row.aliases" :key="a" class="alias-chip">
                  {{ a }}
                  <button
                    type="button"
                    class="alias-remove"
                    :aria-label="`移除别名 ${a}`"
                    @click="removeAlias(row, a)"
                  >
                    <AppIcon name="close" :size="12" />
                  </button>
                </span>
                <el-button size="small" text type="primary" @click="addAlias(row)">+ 别名</el-button>
                <span v-if="!row.aliases?.length" class="muted-text">暂无别名</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="96">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
                {{ row.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="268" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="rename(row)">改主名</el-button>
              <el-button size="small" @click="toggleStatus(row)">
                {{ row.status === 'active' ? '停用' : '启用' }}
              </el-button>
              <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>

          <template #empty>
            <div class="state-block">
              <span class="state-icon"><AppIcon name="categories" :size="24" /></span>
              <p class="state-title">暂无分类标签</p>
              <el-button size="small" @click="load">刷新列表</el-button>
            </div>
          </template>
        </el-table>
      </div>
    </el-card>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="停用后新发布不能选择该标签；从未关联商品的标签可逻辑删除；改名后当前展示新名、历史保留旧名为别名。"
    />
  </div>
</template>

<script setup>
import TextInput from '../components/TextInput.vue'
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import AppIcon from '../components/AppIcon.vue'

const categories = ref([])
const loading = ref(false)
const creating = ref(false)
const newName = ref('')
const loadError = ref('')

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    categories.value = await http.get('/categories')
  } catch (err) {
    loadError.value = `分类列表加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!newName.value.trim()) return
  creating.value = true
  try {
    await http.post('/categories', { name: newName.value })
    ElMessage.success('已创建')
    newName.value = ''
    load()
  } finally {
    creating.value = false
  }
}

async function rename(row) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt('新的主名称（旧主名将保留为别名）', '修改主名', {
      inputValue: row.name,
    }))
  } catch {
    return
  }
  await http.patch(`/categories/${row.id}`, { name: value })
  ElMessage.success('已修改')
  load()
}

async function toggleStatus(row) {
  const disabling = row.status === 'active'
  try {
    if (disabling) {
      await ElMessageBox.confirm(
        `停用分类「${row.name}」？停用后新发布不能选择该标签，已有商品归属与历史保留。`,
        '停用分类',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
      )
    } else {
      await ElMessageBox.confirm(
        `启用分类「${row.name}」？启用后发布与筛选恢复可用。`,
        '启用分类',
        { type: 'info', confirmButtonText: '启用', cancelButtonText: '取消' },
      )
    }
  } catch {
    return
  }
  await http.patch(`/categories/${row.id}`, {
    status: disabling ? 'disabled' : 'active',
  })
  ElMessage.success(disabling ? '已停用' : '已启用')
  load()
}

async function addAlias(row) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt(`为「${row.name}」添加同义别名`, '新增别名'))
  } catch {
    return
  }
  await http.post(`/categories/${row.id}/aliases`, { name: value })
  load()
}

async function removeAlias(row, alias) {
  try {
    await ElMessageBox.confirm(
      `移除别名「${alias}」？不改变商品归属及历史；移除后不再按该别名识别。`,
      '移除别名',
    )
  } catch {
    return
  }
  // The list returns alias names only; after removing by name we must reload so removed aliases no longer display or resolve.
  try {
    await http.delete(`/categories/${row.id}/aliases/by-name?name=${encodeURIComponent(alias)}`)
    ElMessage.success('别名已移除')
  } finally {
    await load()
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm('仅从未关联商品的标签可删除，确认删除？', '删除标签', { type: 'warning' })
  } catch {
    return
  }
  const resp = await http.delete(`/categories/${row.id}`)
  ElMessage.success(resp.detail)
  load()
}

onMounted(load)
</script>

<style scoped>
/* Fallback for extremely long tag names: constrain to the column width; el-tag truncates overflow and title provides the full name. */
.name-tag {
  max-width: 100%;
}

.alias-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.alias-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink-soft);
  padding: 2px 4px 2px 8px;
  font-size: 12px;
}

.alias-remove {
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 4px;
  padding: 2px;
  background: none;
  color: var(--ink-faint);
  cursor: pointer;
}

.alias-remove:hover {
  color: var(--danger);
  background: var(--danger-soft);
}

.alias-remove:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 1px;
}
</style>
