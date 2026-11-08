<template>
  <div class="reviews-page">
    <AppNavBar title="我的评价" />

    <ReportDialog
      v-model:show="reportOpen"
      target-type="review"
      :target-id="reportTarget.id"
      :title="reportTarget.title"
    />

    <van-tabs v-model:active="type" @change="load">
      <van-tab title="我发表的" name="published" />
      <van-tab title="我收到的" name="received" />
    </van-tabs>

    <div class="view">
      <div v-if="error" class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>

      <div v-else-if="reviews.length" class="review-list">
        <article v-for="r in reviews" :key="r.id" class="surface review-card">
          <div class="review-card__head">
            <span class="avatar-text review-card__avatar">{{ initialOf(r.other_party_name) }}</span>
            <div class="review-card__who">
              <span class="review-card__name">{{ r.other_party_name }}</span>
              <span class="review-card__label">{{ type === 'published' ? '我发表的评价' : '我收到的评价' }}</span>
            </div>
            <van-rate :model-value="r.rating" readonly size="14" />
          </div>

          <p class="review-card__content">{{ r.content || '（未填写文字）' }}</p>

          <div v-if="type === 'received' && !r.deleted" class="review-card__actions">
            <van-button size="mini" plain type="warning" @click="reportReview(r)">举报</van-button>
          </div>

          <div class="review-card__meta">
            <span>交易 #{{ r.trade_id }}</span>
            <span class="review-card__dot" aria-hidden="true">·</span>
            <span>{{ fmtTime(r.created_at) }}</span>
            <span v-if="r.deleted" class="pill review-card__deleted">已处理</span>
          </div>
        </article>
      </div>

      <EmptyState
        v-else-if="loaded"
        icon="comment"
        title="暂无评价"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import ReportDialog from '../components/ReportDialog.vue'
import http from '../api/http'
import { fmtTime } from '../api/labels'

const reviews = ref([])
const type = ref('published')
const loaded = ref(false)
const error = ref('')
const reportOpen = ref(false)
const reportTarget = ref({ type: 'review', id: null, title: '举报' })

function reportReview(review) {
  reportTarget.value = { type: 'review', id: review.id, title: '举报评价' }
  reportOpen.value = true
}

function initialOf(name) {
  return name ? Array.from(name)[0] : '评'
}

async function load() {
  error.value = ''
  try {
    reviews.value = await http.get('/me/reviews', { params: { type: type.value } })
    loaded.value = true
  } catch {
    error.value = '评价加载失败，请稍后重试。'
  }
}

onMounted(load)
</script>

<style scoped>
.reviews-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.review-card {
  padding: 13px 14px;
}

.review-card__head {
  display: flex;
  align-items: center;
  gap: 9px;
}

.review-card__avatar {
  width: 34px;
  height: 34px;
  font-size: 13px;
}

.review-card__who {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.review-card__name {
  font-size: 13.5px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-card__label {
  color: var(--ink-meta);
  font-size: 10.5px;
}

.review-card__content {
  margin: 9px 0 0;
  color: var(--ink-soft);
  font-size: 13.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.review-card__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
  color: var(--ink-meta);
  font-size: 11.5px;
}

.review-card__dot {
  color: var(--line-strong);
}

.review-card__deleted {
  margin-left: 4px;
  font-size: 10.5px;
}

.review-card__actions {
  margin-top: 8px;
}
</style>
