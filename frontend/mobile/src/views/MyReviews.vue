<template>
  <div>
    <van-nav-bar title="我的评价" left-arrow @click-left="$router.back()" fixed placeholder />
    <van-tabs v-model:active="type" @change="load">
      <van-tab title="我发表的" name="published" />
      <van-tab title="我收到的" name="received" />
    </van-tabs>
    <van-cell-group inset style="margin-top: 10px">
      <div v-for="r in reviews" :key="r.id" class="review">
        <div class="head">
          <b>{{ r.other_party_name }}</b>
          <van-rate :model-value="r.rating" readonly size="14" />
        </div>
        <div class="content">{{ r.content || '（未填写文字）' }}</div>
        <div class="meta">交易#{{ r.trade_id }} · {{ fmtTime(r.created_at) }} <van-tag v-if="r.deleted">已处理</van-tag></div>
      </div>
      <div v-if="!reviews.length" class="empty-tip">暂无评价</div>
    </van-cell-group>
    <van-notice-bar left-icon="info-o" text="评价仅在本人“我的评价”中查看，不公开展示；提交后不可自行修改或删除。" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import http from '../api/http'
import { fmtTime } from '../api/labels'

const reviews = ref([])
const type = ref('published')

async function load() {
  reviews.value = await http.get('/me/reviews', { params: { type: type.value } })
}

onMounted(load)
</script>

<style scoped>
.review {
  padding: 10px 16px;
  border-bottom: 1px solid #f2f3f5;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.content {
  margin: 6px 0;
  font-size: 14px;
}
.meta {
  color: #969799;
  font-size: 12px;
}
</style>
