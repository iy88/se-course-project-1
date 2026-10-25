<template>
  <div>
    <van-nav-bar title="我的交易" left-arrow @click-left="$router.back()" fixed placeholder />
    <van-tabs v-model:active="role" @change="load">
      <van-tab title="全部" name="all" />
      <van-tab title="我买入" name="buyer" />
      <van-tab title="我卖出" name="seller" />
    </van-tabs>
    <van-cell-group inset style="margin-top: 10px">
      <van-cell v-for="t in trades" :key="t.id" :title="t.product_title" is-link @click="$router.push(`/trades/${t.id}`)">
        <template #label>
          <van-tag :type="t.frozen ? 'danger' : 'primary'" plain>{{ tradeStatusLabels[t.status] }}</van-tag>
          <van-tag v-if="t.frozen" type="danger" plain style="margin-left: 4px">冻结中</van-tag>
          <span style="margin-left: 6px; color: #969799">{{ t.my_role === 'buyer' ? '买方' : '卖方' }} · {{ fmtTime(t.created_at) }}</span>
        </template>
        <template #value>
          <span v-if="t.close_reason" style="font-size: 12px; color: #969799">{{ t.close_reason }}</span>
        </template>
      </van-cell>
      <div v-if="!trades.length" class="empty-tip">暂无交易记录</div>
    </van-cell-group>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import http from '../api/http'
import { fmtTime, tradeStatusLabels } from '../api/labels'

const trades = ref([])
const role = ref('all')

async function load() {
  trades.value = await http.get('/trades/mine', { params: { role: role.value } })
}

onMounted(load)
</script>
