<template>
  <div v-if="profile">
    <van-nav-bar title="个人主页" left-arrow @click-left="$router.back()" fixed placeholder />
    <div class="head">
      <van-image round width="52" height="52" src="/icons/icon-192.png" />
      <div class="name">{{ profile.display_name }}</div>
    </div>

    <van-cell-group inset title="在售商品">
      <van-cell v-for="p in profile.products" :key="p.id" :title="p.title" is-link
        :label="`￥${fen2yuan(p.price_cents)}`" @click="$router.push(`/products/${p.id}`)">
        <template #icon>
          <van-image width="40" height="40" radius="4" fit="cover" :src="p.image_url" style="margin-right: 8px" />
        </template>
      </van-cell>
      <div v-if="!profile.products.length" class="empty-tip">暂无在售商品</div>
    </van-cell-group>

    <div class="chat-btn" v-if="!profile.is_self">
      <van-button type="primary" block round @click="startChat">发起普通私聊</van-button>
      <p class="hint">普通私聊独立于商品与交易；购买请求请在商品页发起。</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import http from '../api/http'
import { fen2yuan } from '../api/labels'

const route = useRoute()
const router = useRouter()
const profile = ref(null)

async function startChat() {
  const data = await http.post('/conversations/normal', { peer_user_id: Number(route.params.id) })
  showToast('会话已就绪')
  router.push(`/conversations/${data.id}`)
}

onMounted(async () => {
  profile.value = await http.get(`/users/${route.params.id}/profile`)
})
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: #fff;
  margin: 10px 16px;
  border-radius: 8px;
}
.name {
  font-size: 17px;
  font-weight: 600;
}
.chat-btn {
  margin: 20px 16px;
}
.hint {
  color: #969799;
  font-size: 12px;
  text-align: center;
  margin-top: 8px;
}
</style>
