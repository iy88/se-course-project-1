<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">治理</p>
        <h1>商品管理</h1>
      </div>
    </header>

    <el-card class="filter-card">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">状态</span>
          <el-select v-model="statusFilter" class="filter-select" @change="load(1)">
            <el-option label="全部状态" value="all" />
            <el-option label="待审核" value="pending_review" />
            <el-option label="审核未通过" value="rejected" />
            <el-option label="公开可交易" value="listed" />
            <el-option label="交易中" value="in_transaction" />
            <el-option label="已下架" value="delisted" />
          </el-select>
          <span class="filter-label">分类</span>
          <el-select
            v-model="categoryFilter"
            clearable
            filterable
            placeholder="全部分类"
            class="filter-select"
            :loading="categoriesLoading"
            @change="load(1)"
          >
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <span class="filter-label">展示限制</span>
          <el-select v-model="restrictedFilter" class="filter-select filter-narrow" @change="load(1)">
            <el-option label="全部" value="all" />
            <el-option label="受限" value="yes" />
            <el-option label="正常" value="no" />
          </el-select>
          <span class="filter-label">搜索</span>
          <el-input
            v-model="keyword"
            placeholder="名称、描述、标签或商品 ID"
            clearable
            maxlength="100"
            class="filter-input product-search"
            @keyup.enter="submitSearch"
            @clear="submitSearch"
          />
          <el-button type="primary" @click="submitSearch">搜索</el-button>
        </div>
        <div class="toolbar-actions">
          <span class="result-count">共 {{ total }} 件</span>
          <el-button :loading="loading" @click="load()">
            <el-icon><AppIcon name="refresh" /></el-icon><span>刷新</span>
          </el-button>
        </div>
      </div>
    </el-card>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
      <template #default>
        <el-button size="small" @click="load()">重新加载</el-button>
      </template>
    </el-alert>

    <el-card class="data-card">
      <div class="table-scroll">
        <el-table :data="products" v-loading="loading" class="data-table" row-key="id">
          <el-table-column prop="id" label="编号" width="72" />
          <el-table-column label="商品" min-width="220">
            <template #default="{ row }">
              <button type="button" class="product-link" @click="$router.push(`/products/${row.id}`)">
                {{ row.title }}
              </button>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="112">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="展示" width="96">
            <template #default="{ row }">
              <el-tag v-if="row.display_restricted" type="danger" effect="light">受限</el-tag>
              <span v-else class="muted-text">正常</span>
            </template>
          </el-table-column>
          <el-table-column label="价格" width="104">
            <template #default="{ row }">{{ fmtPrice(row.price_cents) }}</template>
          </el-table-column>
          <el-table-column label="卖方" width="132">
            <template #default="{ row }">
              <span v-if="row.seller_name">{{ row.seller_name }} <span class="muted-text">#{{ row.seller_id }}</span></span>
              <span v-else class="muted-text">#{{ row.seller_id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="分类标签" min-width="150">
            <template #default="{ row }">{{ row.tag_names?.join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="172">
            <template #default="{ row }">{{ fmt(row.created_at) || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="112" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="$router.push(`/products/${row.id}`)">分类纠正</el-button>
            </template>
          </el-table-column>

          <template #empty>
            <div class="state-block">
              <span class="state-icon"><AppIcon name="products" :size="24" /></span>
              <p class="state-title">当前筛选下暂无商品</p>
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
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import AppIcon from '../components/AppIcon.vue'

const products = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const loadError = ref('')

const statusFilter = ref('all')
const categoryFilter = ref(null)
const restrictedFilter = ref('all')
const keyword = ref('')
const committedKeyword = ref('')

const categories = ref([])
const categoriesLoading = ref(false)

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')
const fmtPrice = (cents) => `￥${(Number(cents || 0) / 100).toFixed(2)}`

let requestSeq = 0

async function load(targetPage) {
  const target = Math.max(1, Number(targetPage) || page.value || 1)
  const seq = ++requestSeq
  loading.value = true
  loadError.value = ''
  try {
    const params = { page: target, page_size: pageSize.value, status: statusFilter.value, display_restricted: restrictedFilter.value }
    if (categoryFilter.value) params.category_id = categoryFilter.value
    if (committedKeyword.value) params.keyword = committedKeyword.value
    const data = await http.get('/admin/products', { params })
    if (seq !== requestSeq) return
    products.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total) || 0
    page.value = target
  } catch (err) {
    if (seq !== requestSeq) return
    loadError.value = `商品列表加载失败：${serverDetail(err)}`
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function submitSearch() {
  committedKeyword.value = keyword.value.trim()
  load(1)
}

function onSizeChange(size) {
  pageSize.value = size
  load(1)
}

const statusLabels = {
  pending_review: '待审核',
  rejected: '审核未通过',
  listed: '公开可交易',
  in_transaction: '交易中',
  delisted: '已下架',
}
const statusLabel = (s) => statusLabels[s] || s
const statusTagType = (s) => {
  if (s === 'pending_review') return 'warning'
  if (s === 'rejected') return 'danger'
  if (s === 'listed') return 'success'
  if (s === 'in_transaction') return 'primary'
  return 'info'
}

async function loadCategories() {
  categoriesLoading.value = true
  try {
    categories.value = await http.get('/categories')
  } catch {
    categories.value = []
  } finally {
    categoriesLoading.value = false
  }
}

onMounted(() => {
  loadCategories()
  load(1)
})
</script>

<style scoped>
.sub {
  margin: 4px 0 0;
  color: var(--ink-soft);
  font-size: 13px;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-select {
  width: 148px;
}
.filter-narrow {
  width: 96px;
}
.product-search {
  width: min(300px, 100%);
}
.result-count {
  color: var(--ink-meta);
  font-size: 12px;
}
.product-link {
  border: none;
  background: none;
  padding: 0;
  color: var(--ink);
  font-weight: 550;
  cursor: pointer;
  text-align: left;
}
.product-link:hover {
  color: var(--brand);
  text-decoration: underline;
}
.muted-text {
  color: var(--ink-meta);
  font-size: 12px;
}
.list-pagination {
  margin-top: 12px;
  justify-content: flex-end;
  padding: 0 18px 14px 0;
}
</style>
