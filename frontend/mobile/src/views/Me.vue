<template>
  <div>
    <van-nav-bar title="我的" fixed placeholder />
    <div class="profile">
      <van-image round width="56" height="56" src="/icons/icon-192.png" />
      <div class="info">
        <div class="name">{{ session.user?.display_name }}</div>
        <div class="email">{{ session.user?.email }}</div>
      </div>
      <van-button v-if="session.user?.status === 'banned'" type="danger" size="small">封禁中</van-button>
    </div>

    <van-cell-group inset title="本人业务">
      <van-cell title="我的商品" icon="goods-collect-o" is-link to="/me/products" />
      <van-cell title="我的交易" icon="balance-list-o" is-link to="/me/trades" />
      <van-cell title="我的收藏" icon="star-o" is-link to="/me/favorites" />
      <van-cell title="我的评价" icon="comment-o" is-link to="/me/reviews" />
      <van-cell title="我的举报 / 我收到的举报" icon="warning-o" is-link to="/me/reports" />
    </van-cell-group>

    <van-cell-group inset title="管理沟通（处置通知与沟通单）" style="margin-top: 10px">
      <van-cell v-for="c in myCases" :key="c.id" :title="c.title" is-link :label="caseStatusLabels[c.status]"
        @click="$router.push(`/cases/${c.id}`)">
        <template #value>{{ caseTypeLabels[c.case_type] }}</template>
      </van-cell>
      <div v-if="!myCases.length" class="empty-tip">暂无相关事项</div>
    </van-cell-group>

    <van-cell-group inset title="账户" style="margin-top: 10px">
      <van-cell title="账户设置" icon="setting-o" is-link to="/me/settings" />
      <van-cell title="退出登录" icon="revoke" is-link @click="logout" />
    </van-cell-group>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import http from '../api/http'
import { caseTypeLabels, caseStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'

const router = useRouter()
const session = useSession()
const myCases = ref([])

async function logout() {
  await showConfirmDialog({ title: '退出登录' })
  await http.post('/auth/logout').catch(() => {})
  session.clear()
  showToast('已退出登录')
  router.replace('/auth/login')
}

onMounted(async () => {
  myCases.value = await http.get('/me/cases').catch(() => [])
})
</script>

<style scoped>
.profile {
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
.email {
  color: #969799;
  font-size: 13px;
}
.info {
  flex: 1;
}
</style>
