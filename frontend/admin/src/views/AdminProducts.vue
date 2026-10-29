<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">治理</p>
        <h1>商品管理</h1>
        <p class="sub">
          管理端不提供全量商品浏览；商品内容通过认领的审核或举报事项查看，分类纠正针对具体商品执行。
        </p>
      </div>
    </header>

    <el-card class="filter-card">
      <template #header>
        <div class="card-head-row">
          <div>
            <span class="card-title">商品检索范围</span>
          </div>
        </div>
      </template>
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">检索</span>
          <el-input
            v-model="keyword"
            placeholder="管理端不提供按商品内容检索"
            disabled
            class="filter-input product-search"
          />
        </div>
        <span class="result-count">仅通过事项查看商品</span>
      </div>
    </el-card>

    <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon />

    <el-card class="form-card">
      <template #header>
        <div class="card-head-row">
          <div>
            <span class="card-title">分类纠正</span>
          </div>
        </div>
      </template>

      <el-alert
        v-if="categoriesError"
        :title="categoriesError"
        type="error"
        :closable="false"
        show-icon
        class="category-alert"
      >
        <template #default>
          <el-button size="small" :loading="categoriesLoading" @click="loadCategories">重新加载分类</el-button>
        </template>
      </el-alert>

      <el-form label-position="top" class="correction-form">
        <div class="form-grid">
          <el-form-item label="商品 ID">
            <el-input-number v-model="correctForm.product_id" :min="1" :controls="false" class="full-control" />
          </el-form-item>
          <el-form-item label="选择分类（可多选）">
            <el-select
              v-model="correctForm.category_ids"
              multiple
              filterable
              placeholder="选择纠正后的分类"
              :loading="categoriesLoading"
              class="full-control"
            >
              <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="依据说明" class="span-2">
            <el-input
              v-model="correctForm.reason"
              type="textarea"
              :rows="2"
              placeholder="纠正原因（必填，将通知卖方）"
            />
          </el-form-item>
          <el-form-item class="span-2 submit-row">
            <el-button type="primary" :loading="submitting" @click="submitCorrection">
              执行纠正
            </el-button>
            <span class="inline-note">纠正会记录依据并通知卖方；不改变商品其他状态。</span>
          </el-form-item>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/http'

const keyword = ref('')
const categories = ref([])
const categoriesLoading = ref(false)
const categoriesError = ref('')
const actionError = ref('')
const submitting = ref(false)
const correctForm = reactive({ product_id: null, category_ids: [], reason: '' })

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

async function loadCategories() {
  categoriesLoading.value = true
  categoriesError.value = ''
  try {
    categories.value = await http.get('/categories')
  } catch (err) {
    categoriesError.value = `分类列表加载失败：${serverDetail(err)}；仍可提交已选分类，请刷新后重试。`
  } finally {
    categoriesLoading.value = false
  }
}

async function submitCorrection() {
  if (!correctForm.product_id || !correctForm.category_ids.length || !correctForm.reason.trim()) {
    return ElMessage.warning('请完整填写商品 ID、分类与纠正原因')
  }
  submitting.value = true
  actionError.value = ''
  try {
    await http.post(`/admin/products/${correctForm.product_id}/correct-category`, {
      category_ids: correctForm.category_ids,
      reason: correctForm.reason,
    })
    ElMessage.success('分类纠正完成并通知卖方')
    correctForm.reason = ''
  } catch (err) {
    actionError.value = `分类纠正失败：${serverDetail(err)}；已保留当前输入。`
  } finally {
    submitting.value = false
  }
}

onMounted(loadCategories)
</script>

<style scoped>
.product-search {
  width: 420px;
}

.category-alert {
  margin-bottom: 14px;
}

.full-control {
  width: 100%;
}

.full-control :deep(.el-input__wrapper) {
  width: 100%;
}

.submit-row :deep(.el-form-item__content) {
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.correction-form {
  max-width: 860px;
}
</style>
