<template>
  <div class="page">
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
      <template #default>
        <el-button size="small" @click="$router.push('/products')">返回商品管理</el-button>
      </template>
    </el-alert>

    <template v-else>
      <header class="page-head">
        <div class="head-main">
          <button type="button" class="back-link" @click="$router.back()">
            <el-icon><AppIcon name="back" /></el-icon>
            返回
          </button>
          <div>
            <p class="eyebrow">商品管理 · #{{ productId }}</p>
            <h1>商品详情预览</h1>
          </div>
        </div>
      </header>

      <div class="detail-grid" v-loading="loading">
        <el-card class="preview-card">
          <template #header><span class="card-title">用户视角预览</span></template>
          <template v-if="product">
            <el-alert
              v-if="product.display_restricted"
              type="warning"
              :closable="false"
              show-icon
              class="state-alert"
              title="该商品已被撤销公开，普通用户无法查看详情"
              :description="product.display_restricted_reason || ''"
            />
            <el-alert
              v-else-if="product.status === 'rejected'"
              type="info"
              :closable="false"
              show-icon
              class="state-alert"
              title="该商品审核未通过，普通用户无法查看详情"
            />

            <div class="gallery">
              <div class="gallery-main">
                <img v-if="activeImage" :src="activeImage" alt="商品图片" />
                <div v-else class="gallery-empty">无图片</div>
              </div>
              <div v-if="(product.image_urls || []).length > 1" class="gallery-thumbs">
                <button
                  v-for="(url, index) in product.image_urls"
                  :key="url"
                  type="button"
                  class="gallery-thumb"
                  :class="{ active: index === activeIndex }"
                  @click="activeIndex = index"
                >
                  <img :src="url" alt="" />
                </button>
              </div>
            </div>

            <div class="preview-head">
              <h2 class="preview-title">{{ product.title }}</h2>
              <div class="preview-meta">
                <el-tag :type="statusTagType(product.status)" effect="light">{{ statusLabel(product.status) }}</el-tag>
                <span class="preview-price">￥{{ (Number(product.price_cents || 0) / 100).toFixed(2) }}</span>
              </div>
            </div>

            <div class="preview-row">
              <span class="preview-label">分类标签</span>
              <div class="tag-chips">
                <el-tag v-for="name in product.tag_names" :key="name" effect="plain" size="small">{{ name }}</el-tag>
                <span v-if="!(product.tag_names || []).length" class="muted-text">（无）</span>
              </div>
            </div>
            <div class="preview-row">
              <span class="preview-label">卖方</span>
              <span>{{ product.seller_name || '—' }} <span class="muted-text">#{{ product.seller_id }}</span></span>
            </div>
            <div class="preview-row">
              <span class="preview-label">发布时间</span>
              <span>{{ fmt(product.created_at) || '—' }}</span>
            </div>
            <div class="preview-row">
              <span class="preview-label">商品描述</span>
              <p class="preview-description">{{ product.description }}</p>
            </div>
          </template>
        </el-card>

        <el-card class="form-card">
          <template #header><span class="card-title">分类纠正</span></template>
          <el-form label-position="top" class="correction-form">
            <el-form-item label="选择纠正后的分类（可多选）">
              <el-select
                v-model="categoryIds"
                multiple
                filterable
                placeholder="选择纠正后的分类"
                :loading="categoriesLoading"
                class="full-control"
              >
                <el-option
                  v-for="c in selectableCategories"
                  :key="c.id"
                  :label="categoryOptionLabel(c)"
                  :value="c.id"
                />
              </el-select>
              <p class="muted-text correction-hint">
                已停用分类不可用于新增关联；仅保留原商品已有关联（可取消）。
              </p>
            </el-form-item>
            <el-form-item label="依据说明">
              <TextInput :limit="500"
                v-model="reason"
                type="textarea"
                placeholder="纠正原因（必填，将通知卖方并留痕）"
                :autosize="{ minRows: 3, maxRows: 8 }"
               />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="submitCorrection">执行纠正</el-button>
              <el-button @click="$router.push('/products')">返回列表</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </div>
    </template>
  </div>
</template>

<script setup>
import TextInput from '../components/TextInput.vue'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import AppIcon from '../components/AppIcon.vue'
import {
  categoryOptionLabel,
  selectableCategoryOptions,
} from '../../../shared/categorySelection.mjs'

const route = useRoute()
const productId = Number(route.params.id)

const product = ref(null)
const categories = ref([])
const categoryIds = ref([])
// 纠正前商品原有分类：用于判断停用分类是否属于“保留原关联”而非新增关联。
const initialCategoryIds = ref([])
const reason = ref('')
const loading = ref(false)
const categoriesLoading = ref(false)
const submitting = ref(false)
const loadError = ref('')
const activeIndex = ref(0)

const activeImage = computed(() => product.value?.image_urls?.[activeIndex.value] || null)
const selectableCategories = computed(() => selectableCategoryOptions(categories.value, initialCategoryIds.value))

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

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

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await http.get(`/products/${productId}`)
    product.value = data
    initialCategoryIds.value = [...(data.tag_ids || [])]
    categoryIds.value = [...(data.tag_ids || [])]
    activeIndex.value = 0
  } catch (err) {
    loadError.value = `商品加载失败：${serverDetail(err)}`
  } finally {
    loading.value = false
  }
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

async function submitCorrection() {
  if (!categoryIds.value.length || !reason.value.trim()) {
    return ElMessage.warning('请选择纠正后的分类并填写纠正原因')
  }
  const allowedIds = new Set(selectableCategories.value.map((c) => Number(c.id)))
  if (categoryIds.value.some((id) => !allowedIds.has(Number(id)))) {
    return ElMessage.warning('所选分类包含不可新增的已停用分类，请调整后重试')
  }
  submitting.value = true
  try {
    await http.post(`/admin/products/${productId}/correct-category`, {
      category_ids: categoryIds.value,
      reason: reason.value.trim(),
    })
    ElMessage.success('分类纠正完成并通知卖方')
    reason.value = ''
    await load()
  } catch (err) {
    ElMessage.error(`分类纠正失败：${serverDetail(err)}`)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  if (!Number.isInteger(productId) || productId <= 0) {
    loadError.value = '商品编号无效'
    return
  }
  loadCategories()
  load()
})
</script>

<style scoped>
.head-main {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: none;
  color: var(--ink-soft);
  cursor: pointer;
  font-size: 13px;
  padding: 6px 8px;
  border-radius: 8px;
}
.back-link:hover {
  background: var(--brand-soft);
  color: var(--ink);
}
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(280px, 3fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 1080px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
.card-title {
  font-weight: 600;
  color: var(--ink);
}
.state-alert {
  margin-bottom: 14px;
}
.gallery {
  max-width: 420px;
}
.gallery-main {
  width: 100%;
  max-height: 320px;
  aspect-ratio: 4 / 3;
  border-radius: 10px;
  overflow: hidden;
  background: var(--brand-soft);
  display: flex;
  align-items: center;
  justify-content: center;
}
.gallery-main img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #fff;
}
.gallery-empty {
  color: var(--ink-meta);
  font-size: 13px;
}
.gallery-thumbs {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  overflow-x: auto;
}
.gallery-thumb {
  width: 64px;
  height: 64px;
  padding: 0;
  border: 2px solid transparent;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  background: var(--brand-soft);
}
.gallery-thumb.active {
  border-color: var(--brand);
}
.gallery-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.preview-head {
  margin-top: 14px;
}
.preview-title {
  margin: 0;
  font-size: 18px;
  color: var(--ink);
}
.preview-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
.preview-price {
  color: var(--brand-ink);
  font-weight: 700;
  font-size: 18px;
}
.preview-row {
  display: grid;
  grid-template-columns: 76px 1fr;
  gap: 10px;
  margin-top: 14px;
}
.preview-label {
  color: var(--ink-meta);
  font-size: 12.5px;
  padding-top: 2px;
}
.tag-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.preview-description {
  margin: 0;
  white-space: pre-wrap;
  color: var(--ink);
  line-height: 1.6;
}
.full-control {
  width: 100%;
}
.correction-hint {
  margin: 6px 0 0;
  line-height: 1.5;
}

.correction-form {
  max-width: 100%;
}
</style>
