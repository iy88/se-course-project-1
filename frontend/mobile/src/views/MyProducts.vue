<template>
  <div class="history-page">
    <AppNavBar title="我的商品" />

    <div class="view">
      <div v-if="error" class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>

      <div v-else-if="products.length" class="listing-list">
        <article v-for="p in products" :key="p.id" class="surface listing-card">
          <div class="listing-card__head">
            <router-link :to="`/products/${p.id}`" class="listing-card__title">{{ p.title }}</router-link>
            <span class="pill" :class="statusTone(p.status)">{{ productStatusLabels[p.status] }}</span>
          </div>

          <div class="listing-card__meta">
            <span class="price price--sm"><span class="price__symbol">￥</span>{{ fen2yuan(p.price_cents) }}</span>
            <router-link v-if="p.pending_request_count" :to="productTradesLink(p.id)" class="pill pill--warn">待接受请求 {{ p.pending_request_count }}</router-link>
          </div>

          <p v-if="p.reject_reason" class="listing-card__reject">原因：{{ p.reject_reason }}</p>
          <p v-if="p.status === 'delisted' && canResubmit(p)" class="listing-card__tip">可修改后重新提交审核</p>

          <div v-if="canEdit(p) || p.can_withdraw_review === true || canResubmit(p)" class="listing-card__actions">
            <van-button v-if="canEdit(p)" size="small" plain type="primary" @click="edit(p)">编辑</van-button>
            <van-button
              v-if="p.can_withdraw_review === true && !session.banned"
              size="small"
              plain
              type="warning"
              @click="withdraw(p)"
            >
              撤回审核
            </van-button>
            <van-button v-if="canResubmit(p)" size="small" plain type="primary" @click="edit(p, true)">
              修改重提
            </van-button>
          </div>

          <div class="listing-card__foot">
            <router-link :to="`/products/${p.id}/edit-history`" class="listing-card__link">编辑历史</router-link>
            <router-link :to="productTradesLink(p.id)" class="listing-card__link">关联请求／交易</router-link>
            <router-link :to="`/products/${p.id}/review-records`" class="listing-card__link">
              <AppIcon name="doc" :size="14" />
              审核记录
            </router-link>
            <router-link :to="`/products/${p.id}`" class="listing-card__link">
              查看详情
              <AppIcon name="chevron-right" :size="15" />
            </router-link>
          </div>
        </article>
      </div>

      <EmptyState
        v-else-if="loaded"
        icon="box"
        title="还没有发布过商品"
      >
        <van-button size="small" type="primary" @click="$router.push('/publish')">去发布</van-button>
      </EmptyState>
    </div>
  </div>
</template>

<script setup>
import { onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fen2yuan, productStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'
import { productTradesLink } from '../api/myTrades'

const router = useRouter()
const session = useSession()
const products = ref([])
const loaded = ref(false)
const error = ref('')

const statusTone = (s) =>
  ({
    listed: 'pill--brand',
    in_transaction: 'pill--info',
    delisted: '',
    pending_review: 'pill--warn',
    rejected: 'pill--danger',
  }[s] || '')

const canResubmit = (p) =>
  !session.banned && (p.can_resubmit === true || (p.can_resubmit === undefined && p.status === 'rejected'))

const canEdit = (p) =>
  !session.banned && ['pending_review', 'listed', 'delisted'].includes(p.status) && !p.display_restricted && !canResubmit(p)

async function load() {
  error.value = ''
  try {
    products.value = await http.get('/products/mine')
    loaded.value = true
  } catch {
    error.value = '商品列表加载失败，请检查网络后重试。'
  }
}

function edit(p, resubmit = false) {
  router.push(`/products/${p.id}/edit${resubmit ? '?resubmit=1' : ''}`)
}

async function withdraw(p) {
  try {
    const data = await http.post(`/products/${p.id}/withdraw-review`)
    showToast(data.detail || '已撤回审核并下架')
  } catch {
    // Failure does not change local state; re-read the server's current status and claim result.
  }
  await load()
}

onMounted(load)
onActivated(load)
</script>

<style scoped>
.history-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.listing-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.listing-card {
  padding: 13px 14px;
}

.listing-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.listing-card__title {
  flex: 1;
  min-width: 0;
  color: var(--ink);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.45;
  word-break: break-word;
}

.listing-card__title:active {
  color: var(--brand);
}

.listing-card__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
}

.listing-card__reject {
  margin: 6px 0 0;
  color: var(--danger);
  font-size: 12px;
  line-height: 1.5;
}

.listing-card__tip {
  margin: 6px 0 0;
  color: var(--brand-ink);
  font-size: 12px;
}

.listing-card__actions + .listing-card__foot {
  margin-top: 6px;
  padding-top: 0;
  border-top: 0;
}

.listing-card__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 9px;
  padding-top: 9px;
  border-top: 1px solid var(--line);
}

.listing-card__link {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--brand-ink);
  font-size: 12px;
  font-weight: 600;
}

.listing-card__actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
</style>
