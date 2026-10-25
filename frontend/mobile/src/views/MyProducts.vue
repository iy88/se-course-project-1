<template>
  <div>
    <van-nav-bar title="我的商品" left-arrow @click-left="$router.back()" fixed placeholder />
    <van-cell-group inset>
      <van-cell v-for="p in products" :key="p.id" :title="p.title" is-link @click="$router.push(`/products/${p.id}`)">
        <template #label>
          <van-tag :type="statusType(p.status)" plain>{{ productStatusLabels[p.status] }}</van-tag>
          <span v-if="p.reject_reason" style="color: #ee0a24; margin-left: 6px">原因：{{ p.reject_reason }}</span>
          <span v-else style="margin-left: 6px; color: #969799">￥{{ fen2yuan(p.price_cents) }}</span>
        </template>
        <template #value>
          <span v-if="p.pending_request_count" class="pending">待接受请求 {{ p.pending_request_count }}</span>
        </template>
      </van-cell>
      <div v-if="!products.length" class="empty-tip">还没有发布过商品</div>
    </van-cell-group>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import http from '../api/http'
import { fen2yuan, productStatusLabels } from '../api/labels'

const products = ref([])
const statusType = (s) =>
  ({ listed: 'primary', in_transaction: 'warning', delisted: 'default', pending_review: 'warning', rejected: 'danger' }[s] || 'default')

onMounted(async () => {
  products.value = await http.get('/products/mine')
})
</script>

<style scoped>
.pending {
  color: #ff976a;
  font-size: 12px;
}
</style>
