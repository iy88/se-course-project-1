<template>
  <div>
    <van-nav-bar title="我的收藏" left-arrow @click-left="$router.back()" fixed placeholder />
    <van-cell-group inset>
      <van-swipe-cell v-for="f in favorites" :key="f.favorite_id">
        <van-cell :title="f.valid ? f.title : '商品已失效'" :label="f.valid ? `￥${fen2yuan(f.price_cents)}` : '内容不可见，可取消收藏'">
          <template #value>
            <van-button v-if="f.valid" size="small" plain type="primary" @click="$router.push(`/products/${f.product_id}`)">查看</van-button>
          </template>
        </van-cell>
        <template #right>
          <van-button square type="danger" text="取消收藏" @click="remove(f)" />
        </template>
      </van-swipe-cell>
      <div v-if="!favorites.length" class="empty-tip">暂无收藏</div>
    </van-cell-group>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { showToast } from 'vant'
import http from '../api/http'
import { fen2yuan } from '../api/labels'

const favorites = ref([])

async function load() {
  favorites.value = await http.get('/favorites')
}

async function remove(f) {
  await http.delete(`/favorites/${f.product_id}`)
  showToast('已取消收藏')
  load()
}

onMounted(load)
</script>
