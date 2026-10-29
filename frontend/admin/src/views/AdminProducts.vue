<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">治理</p>
        <h1>商品管理</h1>
      </div>
    </header>

    <el-card class="filter-card">
      <template #header>
        <div class="card-head-row">
          <div>
            <span class="card-title">公开商品搜索</span>
          </div>
        </div>
      </template>
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">搜索</span>
          <el-input
            v-model="keyword"
            placeholder="搜索商品名称、描述或标签"
            clearable
            maxlength="100"
            class="filter-input product-search"
            @keyup.enter="submitSearch"
            @clear="clearSearch"
          />
        </div>
        <el-button type="primary" :loading="searchLoading" :disabled="searchLoading" @click="submitSearch">
          搜索
        </el-button>
        <el-button :disabled="!keyword && !hasSearched" @click="clearSearch">清空</el-button>
        <span v-if="hasSearched && !searchError" class="result-count">共 {{ searchTotal }} 件</span>
      </div>

      <el-alert
        v-if="searchError"
        :title="searchError"
        type="error"
        :closable="false"
        show-icon
        class="search-alert"
      >
        <template #default>
          <el-button size="small" :loading="searchLoading" @click="searchProducts(searchPage)">重试</el-button>
        </template>
      </el-alert>

      <div v-if="hasSearched && !searchError" v-loading="searchLoading" class="search-results">
        <el-table v-if="searchItems.length" :data="searchItems" row-key="id" size="small" border>
          <el-table-column label="商品" min-width="220">
            <template #default="{ row }">
              <div class="product-title">{{ row.title }}</div>
              <span class="product-id">#{{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="价格" width="100">
            <template #default="{ row }">{{ fmtPrice(row.price_cents) }}</template>
          </el-table-column>
          <el-table-column label="标签" min-width="150">
            <template #default="{ row }">{{ row.tag_names?.join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="发布者" width="120">
            <template #default="{ row }">{{ row.seller_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="发布时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.created_at) || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain :disabled="searchLoading" @click="pickProduct(row)">
                填入 ID
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty
          v-else-if="!searchLoading && !searchError"
          :description="searchMessage || '未找到公开可交易商品'"
        />

        <el-pagination
          v-if="searchTotal > searchPageSize"
          class="search-pagination"
          layout="total, prev, pager, next"
          :current-page="searchPage"
          :page-size="searchPageSize"
          :total="searchTotal"
          :disabled="searchLoading"
          @current-change="searchProducts"
        />
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
          <el-form-item class="span-2">
            <el-button type="primary" :loading="submitting" @click="submitCorrection">
              执行纠正
            </el-button>
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
import { fmtTime } from '../api/time'

const PAGE_SIZE = 10

const keyword = ref('')
const committedKeyword = ref('')
const categories = ref([])
const categoriesLoading = ref(false)
const categoriesError = ref('')
const actionError = ref('')
const submitting = ref(false)
const correctForm = reactive({ product_id: null, category_ids: [], reason: '' })

const searchItems = ref([])
const searchTotal = ref(0)
const searchPage = ref(1)
const searchPageSize = ref(PAGE_SIZE)
const searchLoading = ref(false)
const searchError = ref('')
const searchMessage = ref('')
const hasSearched = ref(false)
let searchRequestId = 0

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')
const fmtPrice = (cents) => `￥${(Number(cents || 0) / 100).toFixed(2)}`

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

async function searchProducts(page = 1) {
  const targetPage = Math.max(1, Number(page) || 1)
  const requestId = ++searchRequestId
  hasSearched.value = true
  searchLoading.value = true
  searchError.value = ''
  try {
    const params = { page: targetPage, page_size: searchPageSize.value }
    if (committedKeyword.value) params.keyword = committedKeyword.value
    const data = await http.get('/products/search', { params })
    // 只接收最后一次请求的结果，避免较慢的旧响应覆盖新搜索结果。
    if (requestId !== searchRequestId) return
    searchItems.value = Array.isArray(data?.items) ? data.items : []
    searchTotal.value = Number(data?.total) || 0
    searchPage.value = targetPage
    searchMessage.value = data?.message || ''
  } catch (err) {
    if (requestId !== searchRequestId) return
    searchItems.value = []
    searchTotal.value = 0
    searchPage.value = targetPage
    searchMessage.value = ''
    searchError.value = `公开商品搜索失败：${serverDetail(err)}`
  } finally {
    if (requestId === searchRequestId) searchLoading.value = false
  }
}

function submitSearch() {
  committedKeyword.value = keyword.value.trim()
  searchProducts(1)
}

function clearSearch() {
  searchRequestId += 1
  keyword.value = ''
  committedKeyword.value = ''
  searchItems.value = []
  searchTotal.value = 0
  searchPage.value = 1
  searchMessage.value = ''
  searchError.value = ''
  hasSearched.value = false
  searchLoading.value = false
}

function pickProduct(row) {
  correctForm.product_id = row.id
  ElMessage.success(`已选择商品 #${row.id}`)
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
      reason: correctForm.reason.trim(),
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
  width: min(420px, 100%);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search-results {
  margin-top: 14px;
  min-height: 72px;
}

.search-alert {
  margin-top: 12px;
}

.search-pagination {
  margin-top: 12px;
  justify-content: flex-end;
}

.result-count {
  color: var(--ink-meta);
  font-size: 12px;
}

.product-title {
  color: var(--ink);
  font-weight: 600;
}

.product-id {
  color: var(--ink-meta);
  font-size: 11.5px;
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

.correction-form {
  max-width: 860px;
}
</style>
