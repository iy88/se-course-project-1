<template>
  <div>
    <van-sticky>
      <van-nav-bar title="校园二手">
        <template #right>
          <van-icon name="apps-o" size="20" @click="$router.push('/me/products')" />
        </template>
      </van-nav-bar>
      <van-search v-model="keyword" placeholder="搜索关键词" @search="load(1)" @update:model-value="onType" />
      <div class="filters">
        <van-dropdown-menu>
          <van-dropdown-item v-model="categoryId" :options="categoryOptions" @change="load(1)" />
          <van-dropdown-item v-model="priceOrder" :options="priceOptions" @change="load(1)" />
        </van-dropdown-menu>
      </div>
    </van-sticky>

    <van-list :loading="loading" :finished="finished" finished-text="没有更多了" @load="loadMore">
      <div class="grid">
        <div v-for="item in items" :key="item.id" class="card" @click="$router.push(`/products/${item.id}`)">
          <van-image width="100%" height="110" fit="cover" radius="6" :src="item.image_url" />
          <div class="title">{{ item.title }}</div>
          <div class="row">
            <span class="price">￥{{ fen2yuan(item.price_cents) }}</span>
            <van-tag plain type="primary" size="medium">{{ item.tag_names[0] || '未分类' }}</van-tag>
          </div>
        </div>
      </div>
      <div v-if="!loading && !items.length" class="empty-tip">{{ message || '暂无在售商品' }}</div>
    </van-list>
  </div>
</template>

<script setup>
import { onMounted, ref, computed } from 'vue'
import http from '../api/http'
import { fen2yuan } from '../api/labels'

const keyword = ref('')
const categoryId = ref(0)
const priceOrder = ref('')
const items = ref([])
const message = ref('')
const loading = ref(false)
const finished = ref(false)
const page = ref(1)
const categories = ref([])

const categoryOptions = computed(() => [
  { text: '全部分类', value: 0 },
  ...categories.value.map((c) => ({ text: c.name, value: c.id })),
])
const priceOptions = [
  { text: '价格不限', value: '' },
  { text: '0-50元', value: '0-5000' },
  { text: '50-200元', value: '5000-20000' },
  { text: '200元以上', value: '20000-' },
]

let typeTimer = null
function onType() {
  clearTimeout(typeTimer)
  typeTimer = setTimeout(() => load(1), 400)
}

async function load(targetPage = 1) {
  loading.value = true
  try {
    const params = { page: targetPage, page_size: 20 }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (categoryId.value) params.category_ids = categoryId.value
    if (priceOrder.value) {
      const [min, max] = priceOrder.value.split('-')
      if (min) params.price_min_cents = Number(min)
      if (max) params.price_max_cents = Number(max)
    }
    const data = await http.get('/products/search', { params })
    if (targetPage === 1) items.value = data.items
    else items.value.push(...data.items)
    message.value = data.message || ''
    finished.value = items.value.length >= data.total
    page.value = targetPage
  } finally {
    loading.value = false
  }
}

function loadMore() {
  load(page.value + 1)
}

onMounted(async () => {
  load(1)
  try {
    categories.value = await http.get('/categories')
  } catch {
    /* 分类加载失败不阻塞列表 */
  }
})
</script>

<style scoped>
.filters {
  background: #fff;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  padding: 10px;
}
.card {
  background: #fff;
  border-radius: 8px;
  padding: 8px;
}
.title {
  font-size: 13px;
  margin: 6px 0 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
