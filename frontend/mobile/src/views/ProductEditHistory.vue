<template>
  <div class="edit-history-page">
    <AppNavBar title="商品编辑历史" />
    <div class="view">
      <p class="history-scope">仅展示本人有权查看的商品编辑记录。</p>
      <div v-if="error" class="error-banner" role="alert">
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain :loading="loading" @click="load">重新加载</van-button>
      </div>
      <van-loading v-else-if="loading" size="20" />
      <div v-else-if="records.length" class="history-list">
        <article v-for="record in records" :key="record.id" class="surface history-card">
          <h2>{{ record.edit_type === 'category_correction' ? '分类纠正' : '商品编辑' }}</h2>
          <p class="history-meta">修改人：{{ record.editor_name || `用户 #${record.editor_id}` }} · {{ fmtTime(record.created_at) }}</p>
          <p v-if="record.reason">原因：{{ record.reason }}</p>
          <section v-for="side in sides" :key="side.key" class="history-snapshot">
            <h3>{{ side.title }}</h3>
            <dl>
              <dt>标题</dt><dd>{{ record[side.key]?.title || '未记录' }}</dd>
              <dt>描述</dt><dd class="history-description">{{ record[side.key]?.description || '未记录' }}</dd>
              <dt>价格</dt><dd>{{ priceText(record[side.key]?.price_cents) }}</dd>
              <dt>分类</dt><dd>{{ record[side.key]?.tags?.join('、') || '无分类记录' }}</dd>
            </dl>
            <div v-if="record[side.images]?.length" class="history-images">
              <van-image v-for="(url, index) in record[side.images]" :key="index" :src="url" width="88" height="88" fit="cover"
                :alt="`${side.title}图片 ${index + 1}`" @click="preview(record[side.images], index)" />
            </div>
            <p v-else class="history-meta">无图片记录</p>
          </section>
        </article>
      </div>
      <EmptyState v-else-if="loaded" icon="doc" title="暂无可查看的编辑历史" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { showImagePreview } from 'vant'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fen2yuan, fmtTime } from '../api/labels'
import { createEditHistoryLoader } from '../api/productEditHistory'

const route = useRoute()
const records = ref([])
const loading = ref(false)
const loaded = ref(false)
const error = ref('')
const sides = [
  { key: 'before_json', images: 'before_image_urls', title: '修改前' },
  { key: 'after_json', images: 'after_image_urls', title: '修改后' },
]
const priceText = (value) => Number.isFinite(value) ? `￥${fen2yuan(value)}` : '未记录'
function preview(images, index) {
  showImagePreview({ images, startPosition: index, closeable: true })
}
const loader = createEditHistoryLoader(
  (id) => http.get(`/products/${id}/edit-history`),
  (state) => {
    records.value = state.records
    loading.value = state.loading
    loaded.value = state.loaded
    error.value = state.error
  },
)
const load = () => loader.load(route.params.id)
onMounted(load)
watch(() => route.params.id, load)
onUnmounted(loader.invalidate)
</script>

<style scoped>
.edit-history-page { padding-bottom: calc(20px + var(--safe-bottom)); }
.history-list { display: grid; gap: 12px; }
.history-card { padding: 14px; overflow-wrap: anywhere; }
.history-card h2 { margin: 0; font-size: 16px; }
.history-scope, .history-meta { color: var(--ink-meta); font-size: 12px; }
.history-snapshot { margin-top: 12px; border-top: 1px solid var(--line); }
.history-snapshot h3 { font-size: 14px; }
.history-snapshot dl { margin: 0; }
.history-snapshot dt { margin-top: 8px; color: var(--ink-meta); font-size: 12px; }
.history-snapshot dd { margin: 4px 0; font-size: 13px; }
.history-description { white-space: pre-wrap; }
.history-images { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
</style>
