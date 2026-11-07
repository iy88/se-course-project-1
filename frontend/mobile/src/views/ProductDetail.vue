<template>
  <div class="detail-page">
    <AppNavBar title="商品详情" />

    <div v-if="restrictionNotice && !product" class="view">
      <div class="surface reject-box"><span>商品已停止公开</span><p>{{ restrictionNotice }}</p></div>
    </div>
    <div v-if="product" class="view view--with-bar">
      <div v-if="product.restriction_result" class="alert alert--warn">核查结果：{{ product.restriction_result }}</div>
      <div v-if="isMine && session.banned" class="alert alert--danger">
        <AppIcon name="alert" :size="17" />
        <span>账户封禁中：禁止修改、上下架或重新提交商品；仍可只读查看并管理沟通。</span>
      </div>
      <div v-else-if="isMine && session.hasFrozenTrade" class="alert alert--warn">
        <AppIcon name="alert" :size="17" />
        <span>交易冻结中：禁止发布、上架、下架及重新上架；本商品的合规编辑仍可保存。</span>
      </div>
      <div v-if="!isMine && session.hasFrozenTrade && !session.banned" class="alert alert--warn">
        <AppIcon name="alert" :size="17" />
        <span>您有其他交易处于冻结处置中：暂不能发起新的购买请求；浏览、收藏、举报与既往评价不受影响。</span>
      </div>

      <section class="surface gallery-card">
        <div class="gallery">
          <van-swipe
            v-if="product.image_urls && product.image_urls.length"
            class="gallery__swipe"
            :autoplay="3000"
            indicator-color="#2f6b4f"
          >
            <van-swipe-item v-for="url in product.image_urls" :key="url">
              <van-image width="100%" height="100%" fit="contain" :src="url">
                <template #error>
                  <div class="gallery__placeholder">
                    <AppIcon name="image" :size="30" />
                    <span>图片加载失败</span>
                  </div>
                </template>
              </van-image>
            </van-swipe-item>
          </van-swipe>
          <div v-else class="gallery__placeholder">
            <AppIcon name="image" :size="30" />
            <span>暂无商品图片</span>
          </div>
        </div>

        <div class="summary">
          <div class="summary__top">
            <div class="price price--lg">
              <span class="price__symbol">￥</span>{{ fen2yuan(product.price_cents) }}
            </div>
            <span class="pill" :class="stateTone(product.status)">{{ productStatusLabels[product.status] }}</span>
          </div>

          <h1 class="product-title">{{ product.title }}</h1>

          <div v-if="product.tag_names && product.tag_names.length" class="tags">
            <span v-for="t in product.tag_names" :key="t" class="pill pill--brand">{{ t }}</span>
          </div>

          <div v-if="product.reject_reason" class="reject-box">
            <span class="reject-box__label">审核原因</span>
            <p>{{ product.reject_reason }}</p>
          </div>

          <div v-if="isMine && product.decided_tag_applications?.length" class="reject-box">
            <span class="reject-box__label">标签申请处理结果</span>
            <p v-for="application in product.decided_tag_applications" :key="application.id">
              {{ application.requested_name }}：{{ application.status === 'rejected' ? '已拒绝' : '已批准' }}
              <template v-if="application.decision_reason">（{{ application.decision_reason }}）</template>
              <template v-else-if="application.status === 'rejected'">（历史记录未提供原因）</template>
            </p>
          </div>

          <router-link
            v-if="isMine"
            :to="`/products/${product.id}/review-records`"
            class="review-entry"
          >
            <span class="review-entry__icon"><AppIcon name="doc" :size="18" /></span>
            <span class="review-entry__main">
              <span class="review-entry__title">审核记录</span>
              <span class="review-entry__sub">查看历次审核结论与不通过原因</span>
            </span>
            <AppIcon name="chevron-right" :size="16" class="review-entry__arrow" />
          </router-link>

          <button type="button" class="seller-row" @click="router.push(`/users/${product.seller_id}`)">
            <span class="avatar-text seller-row__avatar">{{ sellerInitial }}</span>
            <span class="seller-row__main">
              <span class="seller-row__label">发布者</span>
              <span class="seller-row__name">{{ sellerName }}</span>
            </span>
            <AppIcon name="chevron-right" :size="16" class="seller-row__arrow" />
          </button>
        </div>
      </section>

      <section class="surface detail-section">
        <header class="detail-section__head">
          <h2>商品描述</h2>
        </header>
        <p class="desc">{{ product.description }}</p>
      </section>

      <section class="surface detail-section">
        <header class="detail-section__head">
          <h2>商品评论（咨询）</h2>
          <span class="detail-section__hint">{{ comments.length }} 条</span>
        </header>

        <form ref="commentComposer" class="comment-compose" @submit.prevent="submitComment">
          <div v-if="replyTarget" class="comment-compose__target">
            <span>回复 {{ replyTarget.author_name }}</span>
            <van-button size="mini" plain :disabled="commentSubmitting" @click="replyTarget = null">取消回复</van-button>
          </div>
          <TextField :limit="2000" ref="commentInput" v-model="commentDraft" type="textarea" rows="2" autosize label="评论内容"
            placeholder="输入商品咨询内容" :disabled="!canComment || commentSubmitting"  />
          <p v-if="!canComment" class="hint">{{ session.banned ? '账号已封禁，暂不能发表评论或回复。' : '当前商品不可新增评论或回复，历史评论仍按访问权限保留。' }}</p>
          <van-button native-type="submit" size="small" type="primary" :loading="commentSubmitting"
            :disabled="!canComment || !commentDraft.trim() || commentSubmitting || !!textError(commentDraft, 2000)">{{ replyTarget ? '发表回复' : '发表评论' }}</van-button>
          <p v-if="commentError" role="alert" class="comment-compose__error">{{ commentError }}</p>
        </form>
        <div v-if="commentsLoadError" class="comment-compose" role="alert">
          <p>{{ commentsLoadError }}</p>
          <van-button size="small" plain @click="refreshComments()">重新读取评论</van-button>
        </div>
        <div v-if="comments.length" class="comment-list">
          <article v-for="c in comments" :key="c.id" class="comment">
            <span class="avatar-text comment__avatar">{{ initialOf(c.author_name) }}</span>
            <div class="comment__body">
              <div class="comment__head">
                <span class="comment__author">{{ c.author_name }}</span>
                <span v-if="isSellerReply(c)" class="pill pill--brand comment__seller">卖方回复</span>
                <span class="comment__time">{{ fmtTime(c.created_at) }}</span>
              </div>
              <p class="comment__content" :class="{ 'comment__content--deleted': c.deleted }">{{ c.content }}</p>
              <p v-if="c.report_result" class="comment__result">核查结果：{{ c.report_result }}</p>
              <van-button v-if="canComment && isMine && !c.deleted && c.author_id !== product.seller_id"
                size="mini" plain type="primary" :disabled="commentSubmitting" @click="startReply(c)">回复</van-button>
              <van-button
                v-if="c.author_id === session.user.id && !c.deleted && !session.banned"
                size="mini"
                plain
                type="danger"
                class="comment__delete"
                @click="removeComment(c)"
              >
                删除
              </van-button>
              <van-button
                v-if="c.author_id !== session.user.id && !c.deleted && !session.banned"
                size="mini"
                plain
                type="warning"
                class="comment__report"
                @click="reportComment(c)"
              >
                举报
              </van-button>
            </div>
          </article>
        </div>

        <EmptyState v-else-if="!commentsLoadError" icon="comment" title="暂无评论" />
      </section>
    </div>

    <div v-else-if="loading" class="view">
      <div class="skeleton detail-skeleton__gallery" />
      <div class="surface detail-skeleton__card">
        <div class="skeleton detail-skeleton__line detail-skeleton__line--price" />
        <div class="skeleton detail-skeleton__line" />
        <div class="skeleton detail-skeleton__line detail-skeleton__line--short" />
      </div>
    </div>

    <div v-if="product" class="fixed-bar">
      <div class="fixed-bar__inner product-actions">
        <template v-if="!isMine">
          <van-button plain type="default" size="small" :disabled="session.banned" @click="reportProduct">举报</van-button>
          <span class="bar-spacer" />
          <van-button
            :type="isFavored ? 'default' : 'primary'"
            :plain="true"
            size="small"
            :disabled="session.banned"
            @click="toggleFavorite"
          >
            {{ isFavored ? '取消收藏' : '收藏' }}
          </van-button>
          <van-button type="primary" size="small" :disabled="!canRequest" @click="requestTrade">购买请求</van-button>
        </template>

        <template v-else>
          <span class="bar-spacer" />
          <van-button v-if="canEdit" plain type="primary" size="small" @click="edit(false)">编辑</van-button>
          <van-button v-if="canWithdrawReview" plain type="warning" size="small" @click="withdrawReview">撤回审核</van-button>
          <van-button v-if="canResubmit" type="primary" size="small" @click="edit(true)">修改重提</van-button>
          <van-button v-if="product.status === 'listed'" type="warning" size="small" :disabled="listingBlocked" @click="delist">
            下架
          </van-button>
          <van-button
            v-if="product.status === 'delisted' && !canResubmit"
            type="primary"
            size="small"
            :disabled="listingBlocked"
            @click="relist"
          >
            重新上架
          </van-button>
        </template>
      </div>
    </div>

    <ReportDialog
      v-model:show="reportOpen"
      :target-type="reportTarget.type"
      :target-id="reportTarget.id"
      :title="reportTarget.title"
    />
  </div>
</template>

<script setup>
import { textError } from '../api/text'
import TextField from '../components/TextField.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showDialog, showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import ReportDialog from '../components/ReportDialog.vue'
import http from '../api/http'
import { fen2yuan, fmtTime, productStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'

const route = useRoute()
const router = useRouter()
const session = useSession()
const product = ref(null)
const comments = ref([])
const commentDraft = ref('')
const commentComposer = ref(null)
const commentInput = ref(null)
const replyTarget = ref(null)
const commentSubmitting = ref(false)
const commentError = ref('')
const commentsLoadError = ref('')
const canComment = computed(() => !!session.user && !session.banned &&
  !!product.value && !product.value.display_restricted &&
  ['listed', 'in_transaction'].includes(product.value.status))
const isFavored = ref(false)
const sellerName = ref('')
const loading = ref(true)

const isMine = computed(() => product.value?.seller_id === session.user?.id)
const canRequest = computed(
  () =>
    product.value?.status === 'listed' &&
    !isMine.value &&
    !session.banned &&
    !session.hasFrozenTrade,
)
const listingBlocked = computed(() => session.banned || session.hasFrozenTrade)

const canResubmit = computed(() =>
  isMine.value &&
  !session.banned &&
  (
    product.value?.can_resubmit === true ||
    (product.value?.can_resubmit === undefined && product.value?.status === 'rejected')
  ),
)
const canEdit = computed(() =>
  isMine.value &&
  !session.banned &&
  !canResubmit.value &&
  ['pending_review', 'listed', 'delisted'].includes(product.value?.status) &&
  !product.value?.display_restricted,
)
const canWithdrawReview = computed(() =>
  isMine.value && !session.banned && product.value?.can_withdraw_review === true,
)

const sellerInitial = computed(() => initialOf(sellerName.value))

const stateTone = (status) =>
  ({
    listed: 'pill--brand',
    in_transaction: 'pill--info',
    pending_review: 'pill--warn',
    rejected: 'pill--danger',
    delisted: '',
  }[status] || '')

function initialOf(name) {
  return name ? Array.from(name)[0] : '用'
}

const restrictionNotice = ref('')

async function load() {
  product.value = null
  restrictionNotice.value = ''
  loading.value = true
  try {
    product.value = await http.get(`/products/${route.params.id}`)
  } catch (err) {
    if (err?.response?.status === 404) {
      const result = await http.get(`/products/${route.params.id}/restriction-result`).catch(() => null)
      if (result?.public_result) {
        restrictionNotice.value = result.public_result
        loading.value = false
        return
      }
    }
    loading.value = false
    showDialog({ title: '商品不可见', message: '商品不存在或当前不可访问' }).then(() => router.back())
    return
  }
  sellerName.value = await http
    .get(`/users/${product.value.seller_id}/profile`)
    .then((data) => data.display_name)
    .catch(() => `用户#${product.value.seller_id}`)
  await refreshComments()
  const favors = await http.get('/favorites').catch(() => [])
  isFavored.value = favors.some((f) => f.product_id === Number(route.params.id) && f.valid)
  loading.value = false
}

const isSellerReply = (c) => c.reply_to_comment_id !== null && c.author_id === product.value.seller_id

async function refreshComments(productId = String(route.params.id)) {
  try {
    const data = await http.get(`/products/${productId}/comments`)
    if (String(route.params.id) !== productId) return
    comments.value = data
    commentsLoadError.value = ''
  } catch {
    if (String(route.params.id) === productId) {
      commentsLoadError.value = '评论列表读取失败，请重新读取；已成功发表的内容无需重复提交。'
    }
  }
}

function startReply(comment) {
  if (!canComment.value || !isMine.value || commentSubmitting.value || comment.deleted || comment.author_id === product.value.seller_id) return
  replyTarget.value = comment
  commentError.value = ''
  nextTick(() => {
    commentComposer.value?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    commentInput.value?.focus()
  })
}

async function submitComment() {
  const content = commentDraft.value.trim()
  if (!canComment.value || commentSubmitting.value || !content || textError(content, 2000)) return
  const productId = String(route.params.id)
  const body = { content }
  if (replyTarget.value) body.reply_to_comment_id = replyTarget.value.id
  commentSubmitting.value = true
  commentError.value = ''
  try {
    await http.post(`/products/${productId}/comments`, body)
    if (String(route.params.id) !== productId) return
    commentDraft.value = ''
    replyTarget.value = null
    showToast('已发表')
    await refreshComments(productId)
  } catch (err) {
    if (String(route.params.id) !== productId) return
    const detail = err?.response?.data?.detail
    commentError.value = typeof detail === 'string' ? detail : '发表失败，请稍后重试；输入内容已保留。'
    const status = err?.response?.status
    if (status === 403) session.refreshUser().catch(() => {})
    if (status === 409) {
      // Sync the product's latest eligibility while preserving the draft; do not overwrite the existing product on network failure.
      const latest = await http.get(`/products/${productId}`).catch(() => null)
      if (latest && String(route.params.id) === productId) product.value = latest
    }
    if (status === 404) {
      await refreshComments(productId)
      if (String(route.params.id) === productId && replyTarget.value &&
          !comments.value.some(c => c.id === replyTarget.value.id && !c.deleted)) replyTarget.value = null
    }
  } finally {
    commentSubmitting.value = false
  }
}

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
  try {
    await showConfirmDialog({ title: '提交购买请求', message: '将创建独立交易分支并通知卖方，接受前不锁单。' })
  } catch {
    return
  }
  try {
    const data = await http.post('/trades/requests', { product_id: Number(route.params.id) })
    showToast(data.detail)
    if (data.id) router.push(`/trades/${data.id}`)
  } catch (err) {
    // Failure does not change product/request state; if the server rejects because of a new freeze/ban, refresh the user-level eligibility notice.
    if (err?.response?.status === 403) session.refreshUser().catch(() => {})
  }
}

function edit(resubmit) {
  router.push(`/products/${route.params.id}/edit${resubmit ? '?resubmit=1' : ''}`)
}

async function withdrawReview() {
  try {
    await showConfirmDialog({
      title: '撤回商品审核',
      message: '仅管理员认领前可撤回；撤回后商品置为已下架，需修改后重新提交审核，不会直接上架。',
    })
  } catch {
    return
  }
  try {
    const data = await http.post(`/products/${route.params.id}/withdraw-review`)
    showToast(data.detail || '已撤回审核并下架')
  } catch {
    // On server rejection keep the original state and re-read the current claim/review result.
  }
  await load()
}

async function delist() {
  try {
    await showConfirmDialog({ title: '下架商品', message: '下架将关闭待接受请求并注明原因。' })
  } catch {
    return
  }
  try {
    await http.post(`/products/${route.params.id}/delist`)
    showToast('已下架')
  } catch {
    // Rejections such as a locked trade are explained by the server; failure does not change page state.
  }
  await load()
}

async function relist() {
  try {
    await showConfirmDialog({ title: '重新上架', message: '审核有效且当前限制允许时恢复公开可交易。' })
  } catch {
    return
  }
  try {
    await http.post(`/products/${route.params.id}/relist`)
    showToast('已重新上架')
  } catch {
    // Keep the delisted state when frozen or when the review is invalid.
  }
  await load()
}

async function removeComment(c) {
  try {
    await showConfirmDialog({ title: '删除评论', message: '删除为逻辑删除，历史保留。' })
  } catch {
    return
  }
  await http.delete(`/products/${route.params.id}/comments/${c.id}`)
  load()
}

const reportOpen = ref(false)
const reportTarget = ref({ type: 'product', id: null, title: '举报' })

function openReport(type, id, title) {
  reportTarget.value = { type, id, title }
  reportOpen.value = true
}

function reportProduct() {
  openReport('product', Number(route.params.id), '举报商品')
}

function reportComment(comment) {
  openReport('comment', comment.id, '举报评论')
}

onMounted(load)
watch(() => route.params.id, () => {
  commentDraft.value = ''
  replyTarget.value = null
  commentError.value = ''
  commentsLoadError.value = ''
  comments.value = []
  load()
})
</script>

<style scoped>
.detail-page {
  padding-bottom: 0;
}

.gallery-card {
  overflow: hidden;
}

.gallery {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  max-height: 460px;
  background: #f7f9f7;
}

.gallery__swipe {
  width: 100%;
  height: 100%;
}

.gallery__swipe :deep(.van-swipe-item) {
  height: 100%;
}

.gallery__swipe :deep(.van-image) {
  display: block;
  width: 100%;
  height: 100%;
}

.gallery__swipe :deep(img) {
  object-fit: contain;
  background: #f7f9f7;
}

.gallery__placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 100%;
  color: #9aaba1;
  background: #f7f9f7;
  font-size: 12px;
}

.summary {
  padding: 14px 16px 12px;
}

.summary__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.summary__top .price {
  font-size: 26px;
  line-height: 1.15;
}

.product-title {
  margin: 6px 0 0;
  font-size: 18px;
  font-weight: 650;
  line-height: 1.45;
  word-break: break-word;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.reject-box {
  margin-top: 10px;
  padding: 9px 11px;
  border: 1px solid #e8cbc7;
  border-radius: 9px;
  background: var(--danger-soft);
  color: #7d2e28;
  font-size: 12.5px;
  line-height: 1.5;
}

.reject-box__label {
  display: block;
  font-weight: 650;
  margin-bottom: 1px;
}

.reject-box p {
  margin: 0;
}

.review-entry {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin-top: 10px;
  padding: 10px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #f7f9f7;
  color: var(--ink);
  text-align: left;
}

.review-entry:active {
  border-color: var(--line-strong);
}

.review-entry__icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand);
}

.review-entry__main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.review-entry__title {
  font-size: 13.5px;
  font-weight: 600;
}

.review-entry__sub {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.review-entry__arrow {
  flex: 0 0 auto;
  color: var(--ink-faint);
}

.seller-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin-top: 12px;
  padding: 10px 0 0;
  border: 0;
  border-top: 1px solid var(--line);
  background: transparent;
  color: var(--ink);
  text-align: left;
  cursor: pointer;
}

.seller-row__avatar {
  width: 36px;
  height: 36px;
  font-size: 14px;
}

.seller-row__main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.seller-row__label {
  color: var(--ink-meta);
  font-size: 11px;
}

.seller-row__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
  font-weight: 600;
}

.seller-row__arrow {
  flex: 0 0 auto;
  color: var(--ink-faint);
}

.detail-section {
  margin-top: 12px;
  overflow: hidden;
}

.detail-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.detail-section__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.detail-section__hint {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.desc {
  margin: 0;
  padding: 14px 16px;
  color: var(--ink-soft);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.comment-list {
  padding: 2px 0;
}

.comment {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
}

.comment + .comment {
  border-top: 1px solid var(--line);
}

.comment__avatar {
  width: 32px;
  height: 32px;
  font-size: 12.5px;
}

.comment__body {
  flex: 1;
  min-width: 0;
}

.comment__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.comment__author {
  font-size: 13px;
  font-weight: 600;
}

.comment__seller {
  padding: 0 6px;
  font-size: 10.5px;
}

.comment__time {
  margin-left: auto;
  color: var(--ink-meta);
  font-size: 11px;
}

.comment__content {
  margin: 4px 0 0;
  color: var(--ink-soft);
  font-size: 13.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.comment__content--deleted {
  color: var(--ink-faint);
}

.comment__delete {
  margin-top: 4px;
}

.product-actions {
  justify-content: flex-end;
}

.bar-spacer {
  flex: 1;
}

.product-actions :deep(.van-button) {
  min-width: 0;
  padding: 0 13px;
}

.detail-skeleton__gallery {
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: var(--radius);
}

.detail-skeleton__card {
  margin-top: 12px;
  padding: 16px;
}

.detail-skeleton__line {
  height: 13px;
  border-radius: 5px;
  margin-bottom: 10px;
}

.detail-skeleton__line--price {
  width: 36%;
  height: 22px;
}

.detail-skeleton__line--short {
  width: 58%;
}

@media (max-width: 359px) {
  .product-actions :deep(.van-button) {
    padding: 0 10px;
  }

  .summary {
    padding: 12px;
  }

  .desc,
  .comment,
  .detail-section__head {
    padding-left: 12px;
    padding-right: 12px;
  }
}

.comment-compose {
  padding: 12px 16px;
}
.comment-compose__target {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  overflow-wrap: anywhere;
}
.comment-compose__error {
  color: var(--danger, #a43b36);
  overflow-wrap: anywhere;
}
.comment__report {
  margin-top: 4px;
  margin-left: 8px;
}
.comment__result {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ink-soft, #4d5f58);
}
</style>
