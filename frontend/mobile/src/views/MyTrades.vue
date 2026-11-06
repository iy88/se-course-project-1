<template>
  <div class="trades-page">
    <AppNavBar title="我的交易" />

    <van-tabs v-model:active="role" @change="load">
      <van-tab title="全部" name="all" />
      <van-tab title="我买入" name="buyer" />
      <van-tab title="我卖出" name="seller" />
    </van-tabs>

    <div class="view">
      <div v-if="error" class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ error }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>

      <div v-else-if="trades.length" class="trade-list">
        <article v-for="t in trades" :key="t.id" class="surface trade-card">
          <div class="trade-card__head">
            <h3 class="trade-card__title"><router-link :to="`/trades/${t.id}`">{{ t.product_title }}</router-link></h3>
            <span class="pill" :class="t.frozen ? 'pill--danger' : statusTone(t.status)">
              {{ tradeStatusLabels[t.status] }}
            </span>
          </div>
          <div class="trade-card__meta">
            <span>{{ t.my_role === 'buyer' ? '买方' : '卖方' }}</span>
            <span class="trade-card__dot" aria-hidden="true">·</span>
            <span>{{ fmtTime(t.created_at) }}</span>
            <span v-if="t.frozen" class="pill pill--danger trade-card__frozen">冻结中</span>
          </div>
          <p v-if="t.close_reason" class="trade-card__reason">{{ t.close_reason }}</p>
          <div class="trade-card__foot">
            <router-link :to="`/trades/${t.id}`" class="trade-card__link">查看交易详情</router-link>
            <router-link :to="`/products/${t.product_id}/edit-history`" class="trade-card__link">编辑历史</router-link>
            <AppIcon name="chevron-right" :size="16" class="trade-card__arrow" />
          </div>
        </article>
      </div>

      <EmptyState
        v-else-if="loaded"
        icon="swap"
        title="暂无交易记录"
      />
    </div>
  </div>
</template>

<script setup>
import { onActivated, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { fmtTime, tradeStatusLabels } from '../api/labels'

const trades = ref([])
const role = ref('all')
const loaded = ref(false)
const error = ref('')

const statusTone = (s) =>
  ({
    completed: 'pill--ok',
    terminated: 'pill--danger',
    disputed: 'pill--warn',
    abnormal: 'pill--danger',
    in_progress: 'pill--brand',
    pending_acceptance: 'pill--info',
  }[s] || '')

async function load() {
  error.value = ''
  try {
    trades.value = await http.get('/trades/mine', { params: { role: role.value } })
    loaded.value = true
  } catch {
    error.value = '交易列表加载失败，请稍后重试。'
  }
}

onMounted(load)
onActivated(load)
</script>

<style scoped>
.trades-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.trade-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trade-card {
  display: block;
  padding: 13px 14px;
  color: var(--ink);
  text-decoration: none;
}

.trade-card:active {
  border-color: var(--line-strong);
}

.trade-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.trade-card__title {
  flex: 1;
  min-width: 0;
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.45;
  word-break: break-word;
}

.trade-card__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
  color: var(--ink-meta);
  font-size: 11.5px;
}

.trade-card__dot {
  color: var(--line-strong);
}

.trade-card__frozen {
  margin-left: 2px;
  font-size: 10.5px;
}

.trade-card__reason {
  margin: 6px 0 0;
  color: var(--ink-soft);
  font-size: 12px;
  line-height: 1.5;
}

.trade-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 9px;
  padding-top: 9px;
  border-top: 1px solid var(--line);
}

.trade-card__link {
  color: var(--brand-ink);
  font-size: 12px;
  font-weight: 600;
}

.trade-card__arrow {
  color: var(--ink-faint);
}
</style>
