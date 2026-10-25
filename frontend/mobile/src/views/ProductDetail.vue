<template>
  <div v-if="product">
    <van-nav-bar title="商品详情" left-arrow @click-left="$router.back()" fixed placeholder />

    <van-swipe class="swipe" :autoplay="3000" indicator-color="white">
      <van-swipe-item v-for="url in product.image_urls" :key="url">
        <van-image width="100%" height="260" fit="cover" :src="url" />
      </van-swipe-item>
    </van-swipe>

    <van-cell-group inset style="margin-top: 10px">
      <div class="price-line">
        <span class="price big">￥{{ fen2yuan(product.price_cents) }}</span>
        <van-tag :type="statusType(product.status)">{{ productStatusLabels[product.status] }}</van-tag>
      </div>
      <div class="title">{{ product.title }}</div>
      <div class="tags">
        <van-tag plain v-for="t in product.tag_names" :key="t" style="margin-right: 6px">{{ t }}</van-tag>
      </div>
      <van-cell title="发布者" is-link :value="sellerName" @click="$router.push(`/users/${product.seller_id}`)" />
    </van-cell-group>

    <van-cell-group inset style="margin-top: 10px">
      <div class="desc">{{ product.description }}</div>
    </van-cell-group>

    <van-cell-group inset style="margin-top: 10px" title="商品评论（咨询）">
      <div v-for="c in comments" :key="c.id" class="comment">
        <div class="comment-head">
          <b>{{ c.author_name }}</b>
          <span v-if="isSellerReply(c)" class="seller-tag">卖方回复</span>
          <span class="time">{{ fmtTime(c.created_at) }}</span>
        </div>
        <div class="comment-body" :class="{ deleted: c.deleted }">{{ c.content }}</div>
        <van-button
          v-if="c.author_id === session.user.id && !c.deleted"
          size="small" plain type="danger" style="margin-top: 4px"
          @click="removeComment(c)"
        >删除</van-button>
      </div>
      <div v-if="!comments.length" class="empty-tip">暂无评论</div>
    </van-cell-group>

    <div class="bottom-bar">
      <van-button v-if="!isMine" plain type="default" size="small" style="margin-right: 8px" @click="reportProduct">举报</van-button>
      <template v-if="isMine">
        <van-button v-if="product.status === 'listed'" type="warning" size="small" @click="delist">下架</van-button>
        <van-button v-if="product.status === 'delisted'" type="primary" size="small" @click="relist">重新上架</van-button>
        <van-button v-if="product.status === 'rejected'" type="primary" size="small" @click="openResubmit">修改重提</van-button>
      </template>
      <template v-else>
        <van-button :type="isFavored ? 'default' : 'primary'" plain size="small" @click="toggleFavorite">
          {{ isFavored ? '取消收藏' : '收藏' }}
        </van-button>
        <van-button type="primary" size="small" style="margin-left: 8px" :disabled="!canRequest" @click="requestTrade">
          购买请求
        </van-button>
      </template>
    </div>

    <van-dialog
      v-model:show="resubmitShow"
      title="修改重提（形成新的审核记录）"
      show-cancel-button
      :before-close="submitResubmit"
    >
      <van-field v-model="resubmitForm.title" label="标题" />
      <van-field v-model="resubmitForm.description" label="描述" type="textarea" rows="2" />
      <van-field v-model="resubmitPrice" label="价格(元)" type="number" />
    </van-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showDialog, showToast } from 'vant'
import http from '../api/http'
import { fen2yuan, fmtTime, productStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'

const route = useRoute()
const router = useRouter()
const session = useSession()
const product = ref(null)
const comments = ref([])
const isFavored = ref(false)
const sellerName = ref('')
const resubmitShow = ref(false)
const resubmitPrice = ref('')
const resubmitForm = reactive({ title: '', description: '' })

const isMine = computed(() => product.value?.seller_id === session.user.id)
const canRequest = computed(() => product.value?.status === 'listed' && !isMine.value)

async function load() {
  try {
    product.value = await http.get(`/products/${route.params.id}`)
    sellerName.value = (await http.get(`/users/${product.value.seller_id}/profile`)).display_name
  } catch {
    showDialog({ title: '商品不可见', message: '商品不存在或当前不可访问' }).then(() => router.back())
    return
  }
  comments.value = await http.get(`/products/${route.params.id}/comments`).catch(() => [])
  const favors = await http.get('/favorites').catch(() => [])
  isFavored.value = favors.some((f) => f.product_id === Number(route.params.id) && f.valid)
}

const isSellerReply = (c) => c.reply_to_comment_id !== null && c.author_id === product.value.seller_id
const statusType = (s) =>
  ({ listed: 'primary', in_transaction: 'warning', delisted: 'default', pending_review: 'warning', rejected: 'danger' }[s] || 'default')

async function toggleFavorite() {
  if (isFavored.value) {
    await http.delete(`/favorites/${route.params.id}`)
    isFavored.value = false
  } else {
    await http.post(`/favorites/${route.params.id}`)
    isFavored.value = true
  }
}

async function requestTrade() {
  await showConfirmDialog({ title: '提交购买请求', message: '将创建独立交易分支并通知卖方，接受前不锁单。' })
  const data = await http.post('/trades/requests', { product_id: Number(route.params.id) })
  showToast(data.detail)
  if (data.id) router.push(`/trades/${data.id}`)
}

async function delist() {
  await showConfirmDialog({ title: '下架商品', message: '下架将关闭待接受请求并注明原因。' })
  await http.post(`/products/${route.params.id}/delist`)
  showToast('已下架')
  load()
}

async function relist() {
  await showConfirmDialog({ title: '重新上架', message: '审核有效且当前限制允许时恢复公开可交易。' })
  await http.post(`/products/${route.params.id}/relist`)
  showToast('已重新上架')
  load()
}

function openResubmit() {
  resubmitForm.title = product.value.title
  resubmitForm.description = product.value.description
  resubmitPrice.value = fen2yuan(product.value.price_cents)
  resubmitShow.value = true
}

async function submitResubmit(action) {
  if (action !== 'confirm') return true
  const price = Math.round(Number(resubmitPrice.value || 0) * 100)
  if (!resubmitForm.title || price < 0) {
    showFailToast('请填写完整')
    return false
  }
  await http.post(`/products/${route.params.id}/resubmit`, {
    title: resubmitForm.title,
    description: resubmitForm.description,
    price_cents: price,
  })
  showToast('已重新提交审核')
  resubmitShow.value = true
  load()
  return true
}

async function removeComment(c) {
  await showConfirmDialog({ title: '删除评论', message: '删除为逻辑删除，历史保留。' })
  await http.delete(`/products/${route.params.id}/comments/${c.id}`)
  load()
}

async function reportProduct() {
  const { value } = await showDialog({
    title: '举报商品',
    message: '请输入举报原因（必填）',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (!value) return
  const data = await http.post('/reports', { target_type: 'product', target_id: Number(route.params.id), reason: value })
  showToast(data.detail)
}

onMounted(load)
</script>

<style scoped>
.swipe {
  background: #fff;
}
.price-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px 0;
}
.big {
  font-size: 22px;
}
.title {
  font-size: 16px;
  font-weight: 600;
  padding: 8px 16px 4px;
}
.tags {
  padding: 0 16px 10px;
}
.desc {
  padding: 12px 16px;
  font-size: 14px;
  color: #323233;
  white-space: pre-wrap;
}
.comment {
  padding: 10px 16px;
  border-bottom: 1px solid #f2f3f5;
}
.comment-head {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: #969799;
}
.seller-tag {
  color: #1989fa;
  border: 1px solid #1989fa;
  border-radius: 4px;
  padding: 0 4px;
  font-size: 10px;
}
.time {
  margin-left: auto;
}
.comment-body {
  margin-top: 4px;
  font-size: 14px;
}
.deleted {
  color: #c8c9cc;
}
.bottom-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #fff;
  padding: 8px 16px calc(8px + var(--safe-bottom));
  display: flex;
  justify-content: flex-end;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.04);
  z-index: 10;
}
</style>
