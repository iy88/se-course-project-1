<template>
  <div class="home">
    <header class="home-head">
      <div class="home-brand">
        <BrandMark :size="32" />
        <div class="home-brand__text">
          <h1>校园二手</h1>
          <p>校内闲置 · 当面交易</p>
        </div>
        <button type="button" class="home-publish" aria-label="我的发布与商品管理" @click="router.push('/me/products')">
          <AppIcon name="box" :size="18" />
          <span>我的发布</span>
        </button>
      </div>

      <van-search
        v-model="keyword"
        placeholder="搜索商品名称、描述或标签"
        shape="round"
        @search="load(1)"
        @update:model-value="onType"
      >
        <template #left-icon>
          <AppIcon name="search" :size="18" />
        </template>
      </van-search>

      <div class="home-filters">
        <van-dropdown-menu>
          <van-dropdown-item ref="categoryDropdown" :title="categoryTitle" @open="syncCategoryDraft">
            <div class="category-panel">
              <p class="category-hint">按分类筛选（可多选）</p>
              <van-checkbox-group v-model="draftCategoryIds">
                <van-checkbox v-for="c in categories" :key="c.id" :name="c.id" shape="square" class="category-check">
                  <span :class="{ 'text-disabled': c.status === 'disabled' }">{{ c.name }}</span>
                  <span v-if="categoryAliasHint(c)" class="category-alias">{{ categoryAliasHint(c) }}</span>
                  <span v-if="c.status === 'disabled'" class="pill category-disabled">已停用</span>
                </van-checkbox>
              </van-checkbox-group>
              <div v-if="!categories.length" class="category-empty">分类暂未加载，可稍后重试</div>
              <div class="category-actions">
                <van-button size="small" plain @click="clearCategories">清空</van-button>
                <van-button size="small" type="primary" @click="applyCategories">确定</van-button>
              </div>
            </div>
          </van-dropdown-item>
          <van-dropdown-item v-model="priceOrder" :options="priceOptions" @change="load(1)" />
        </van-dropdown-menu>
      </div>

      <div v-if="nameFilterChips.length" class="name-filters">
        <span class="name-filter-label">名称筛选</span>
        <span
          v-for="f in nameFilterChips"
          :key="f.raw"
          class="name-chip"
          :class="{ 'name-chip--unknown': !f.known }"
        >
          {{ f.label }}<span v-if="!f.known">（当前不可识别）</span>
          <button
            type="button"
            class="name-chip__close"
            :aria-label="`移除名称筛选 ${f.label}`"
            @click="removeNameFilter(f.raw)"
          >
            <AppIcon name="close" :size="13" />
          </button>
        </span>
      </div>
    </header>

    <van-list
      :loading="loading"
      :finished="finished"
      :finished-text="loadError || !items.length ? '' : '没有更多了'"
      class="home-list"
      @load="loadMore"
    >
      <div v-if="loading && !items.length" class="grid" aria-hidden="true">
        <div v-for="n in 4" :key="n" class="product-card product-card--skeleton">
          <div class="skeleton product-card__media" />
          <div class="product-card__body">
            <div class="skeleton skeleton-line" />
            <div class="skeleton skeleton-line skeleton-line--short" />
            <div class="skeleton skeleton-price" />
          </div>
        </div>
      </div>

      <div v-else-if="items.length" class="grid">
        <article
          v-for="item in items"
          :key="item.id"
          class="product-card"
          role="link"
          tabindex="0"
          @click="openProduct(item)"
          @keydown.enter.prevent="openProduct(item)"
        >
          <div class="product-card__media">
            <van-image v-if="item.image_url" width="100%" height="100%" fit="cover" :src="item.image_url">
              <template #error>
                <div class="media-placeholder">
                  <AppIcon name="image" :size="26" />
                  <span>暂无图片</span>
                </div>
              </template>
              <template #loading>
                <div class="skeleton media-skeleton" />
              </template>
            </van-image>
            <div v-else class="media-placeholder">
              <AppIcon name="image" :size="26" />
              <span>暂无图片</span>
            </div>
            <span
              v-if="item.status && item.status !== 'listed'"
              class="pill product-state"
              :class="stateTone(item.status)"
            >
              {{ productStatusLabels[item.status] || item.status }}
            </span>
          </div>

          <div class="product-card__body">
            <h3 class="product-card__title clamp-2">{{ item.title }}</h3>
            <div class="product-card__price price">
              <span class="price__symbol">￥</span>{{ fen2yuan(item.price_cents) }}
            </div>
            <div class="product-card__foot">
              <span class="tag-soft">{{ (item.tag_names && item.tag_names[0]) || '未分类' }}</span>
              <span v-if="item.tag_names && item.tag_names.length > 1" class="tiny muted">
                +{{ item.tag_names.length - 1 }}
              </span>
            </div>
          </div>
        </article>
      </div>

      <div v-if="loadError" class="error-banner home-error">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ loadError }}</span>
        <van-button size="small" plain type="primary" @click="retryLoad">重试</van-button>
      </div>

      <EmptyState
        v-else-if="!loading && !items.length"
        icon="box"
        :title="message || '暂无在售商品'"
      />
    </van-list>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import EmptyState from '../components/EmptyState.vue'
import { categoryAliasHint } from '../api/categoryAlias'
import http from '../api/http'
import { fen2yuan, productStatusLabels } from '../api/labels'
import { buildProductSearchParams, normalizeNameFilters } from '../api/searchParams'

const route = useRoute()
const router = useRouter()
const keyword = ref('')
const priceOrder = ref('')
const items = ref([])
const message = ref('')
const loadError = ref('')
const loading = ref(false)
const finished = ref(false)
const page = ref(1)
const retryPage = ref(1)
const categories = ref([])
const categoryDropdown = ref(null)
const selectedCategoryIds = ref([])
const draftCategoryIds = ref([])
const nameFilters = ref(normalizeNameFilters(route.query.category_names))

const categoryTitle = computed(() => {
  if (!selectedCategoryIds.value.length) return '全部分类'
  const names = selectedCategoryIds.value
    .map((id) => categories.value.find((c) => Number(c.id) === Number(id))?.name)
    .filter(Boolean)
  if (!names.length) return `已选 ${selectedCategoryIds.value.length} 个分类`
  if (names.length <= 2) return names.join('、')
  return `已选 ${names.length} 个分类`
})

const nameFilterChips = computed(() =>
  nameFilters.value.map((raw) => {
    const matched = categories.value.find(
      (c) => c.name === raw || (Array.isArray(c.aliases) && c.aliases.includes(raw)),
    )
    // 只展示服务端当前主名；已移除/未知名称保留原文，交由服务端按无匹配处理，不静默转全量。
    return { raw, label: matched ? matched.name : raw, known: !!matched }
  }),
)

const priceOptions = [
  { text: '价格不限', value: '' },
  { text: '0-50元', value: '0-5000' },
  { text: '50-200元', value: '5000-20000' },
  { text: '200元以上', value: '20000-' },
]

const stateTone = (status) =>
  ({
    pending_review: 'pill--warn',
    rejected: 'pill--danger',
    in_transaction: 'pill--info',
    delisted: '',
  }[status] || '')

let typeTimer = null
function onType() {
  clearTimeout(typeTimer)
  typeTimer = setTimeout(() => load(1), 400)
}

function syncCategoryDraft() {
  draftCategoryIds.value = [...selectedCategoryIds.value]
}

function applyCategories() {
  selectedCategoryIds.value = [...new Set(draftCategoryIds.value.map((id) => Number(id)))]
  categoryDropdown.value?.toggle(false)
  load(1)
}

function clearCategories() {
  draftCategoryIds.value = []
  selectedCategoryIds.value = []
  categoryDropdown.value?.toggle(false)
  load(1)
}

function removeNameFilter(raw) {
  const next = nameFilters.value.filter((name) => name !== raw)
  const query = { ...route.query }
  if (next.length) query.category_names = next
  else delete query.category_names
  nameFilters.value = next
  router.replace({ query }).catch(() => {})
  load(1)
}

function retryLoad() {
  load(retryPage.value)
}

function openProduct(item) {
  router.push(`/products/${item.id}`)
}

let loadSeq = 0
async function load(targetPage = 1) {
  const seq = ++loadSeq
  loading.value = true
  loadError.value = ''
  try {
    let priceMin = null
    let priceMax = null
    if (priceOrder.value) {
      const [min, max] = priceOrder.value.split('-')
      priceMin = min ? Number(min) : null
      priceMax = max ? Number(max) : null
    }
    const params = buildProductSearchParams({
      page: targetPage,
      pageSize: 20,
      keyword: keyword.value.trim(),
      categoryIds: selectedCategoryIds.value,
      categoryNames: nameFilters.value,
      priceMin,
      priceMax,
    })
    const data = await http.get('/products/search', { params })
    if (seq !== loadSeq) return
    if (targetPage === 1) items.value = data.items
    else items.value.push(...data.items)
    message.value = data.message || ''
    finished.value = items.value.length >= data.total
    page.value = targetPage
  } catch {
    if (seq !== loadSeq) return
    retryPage.value = targetPage
    loadError.value = targetPage === 1 ? '商品加载失败，请稍后重试。' : '加载更多失败，请稍后重试。'
    finished.value = true
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function loadMore() {
  if (loading.value) return
  load(page.value + 1)
}

watch(
  () => route.query.category_names,
  (value) => {
    const next = normalizeNameFilters(value)
    if (JSON.stringify(next) === JSON.stringify(nameFilters.value)) return
    nameFilters.value = next
    load(1)
  },
)

onMounted(async () => {
  load(1)
  try {
    categories.value = await http.get('/categories')
  } catch {
    /* 分类加载失败不阻塞在售列表；已保存的名称筛选仍会原样交给服务端。 */
  }
})
</script>

<style scoped>
.home {
  min-height: 100vh;
  max-width: var(--content);
  margin: 0 auto;
}

.home-head {
  position: sticky;
  top: 0;
  z-index: 12;
  background: var(--bg);
  border-bottom: 1px solid var(--line);
  padding: calc(6px + var(--safe-top)) 12px 0;
}

.home-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 2px 10px;
}

.home-brand__text {
  flex: 1;
  min-width: 0;
}

.home-brand__text h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.3;
}

.home-brand__text p {
  margin: 1px 0 0;
  color: var(--ink-meta);
  font-size: 11.5px;
}

.home-publish {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  padding: 7px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  background: var(--panel);
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.home-publish:active {
  border-color: var(--brand);
  color: var(--brand);
}

.home-filters {
  margin: 8px -12px 0;
  background: var(--panel);
}

.category-panel {
  padding: 4px 14px 14px;
  max-height: 55vh;
  overflow: auto;
}

.category-hint {
  margin: 8px 0 4px;
  color: var(--ink-meta);
  font-size: 12px;
}

.category-check {
  align-items: flex-start;
  padding: 7px 0;
}

.category-check :deep(.van-checkbox__label) {
  display: inline-flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 14px;
}

.text-disabled {
  color: var(--ink-meta);
}

.category-alias {
  color: var(--ink-meta);
  font-size: 11.5px;
  overflow-wrap: anywhere;
}

.category-disabled {
  padding: 0 6px;
  font-size: 10.5px;
}

.category-empty {
  padding: 18px 0;
  color: var(--ink-meta);
  font-size: 12.5px;
  text-align: center;
}

.category-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
  margin-top: 8px;
  border-top: 1px solid var(--line);
}

.name-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 0 10px;
}

.name-filter-label {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.name-chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 3px 1px 8px;
  border: 1px solid #cfe3d7;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-size: 11.5px;
  font-weight: 600;
}

.name-chip--unknown {
  border-color: #e6d2ad;
  background: var(--warn-soft);
  color: var(--warn);
}

.name-chip__close {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.name-chip__close:active {
  background: rgba(31, 77, 56, 0.1);
}

.home-list {
  min-height: 50vh;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
}

.product-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.product-card:active {
  transform: scale(0.995);
  border-color: var(--line-strong);
}

.product-card__media {
  position: relative;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: #f1f5f2;
}

.product-card__media :deep(.van-image) {
  display: block;
  width: 100%;
  height: 100%;
}

.product-card__media :deep(img) {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.media-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  width: 100%;
  height: 100%;
  color: #9aaba1;
  background: #f1f5f2;
  font-size: 11px;
}

.media-skeleton {
  width: 100%;
  height: 100%;
  border-radius: 0;
}

.product-state {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 1px 7px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 1px 3px rgba(24, 36, 32, 0.12);
}

.product-card__body {
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex: 1;
  padding: 9px 10px 10px;
}

.product-card__title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
  min-height: 2.9em;
}

.product-card__price {
  font-size: 17px;
  line-height: 1.2;
}

.product-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: auto;
  padding-top: 2px;
}

.tag-soft {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 7px;
  border-radius: 5px;
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-size: 11px;
  font-weight: 600;
}

.product-card--skeleton {
  cursor: default;
}

.skeleton-line {
  height: 12px;
  border-radius: 5px;
}

.skeleton-line--short {
  width: 62%;
}

.skeleton-price {
  width: 44%;
  height: 16px;
  margin-top: 4px;
}

.home-error {
  margin: 4px 12px 20px;
}

@media (min-width: 560px) {
  .grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
    padding: 14px 12px;
  }
}

@media (max-width: 359px) {
  .home-brand__text p {
    display: none;
  }

  .home-publish span {
    display: none;
  }

  .home-publish {
    padding: 7px;
  }

  .grid {
    gap: 8px;
    padding: 10px;
  }

  .product-card__body {
    padding: 8px;
  }
}
</style>
