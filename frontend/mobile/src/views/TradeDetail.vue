<template>
  <div v-if="trade">
    <van-nav-bar title="交易详情" left-arrow @click-left="$router.back()" fixed placeholder />

    <van-cell-group inset style="margin-top: 10px">
      <van-cell title="商品" :value="trade.product_title" is-link @click="$router.push(`/products/${trade.product_id}`)" />
      <van-cell title="状态">
        <template #value>
          <van-tag :type="statusType">{{ tradeStatusLabels[trade.status] }}</van-tag>
          <van-tag v-if="trade.frozen" type="danger" style="margin-left: 6px">冻结中</van-tag>
        </template>
      </van-cell>
      <van-cell title="我的身份" :value="trade.my_role === 'buyer' ? '买方' : '卖方'" />
      <van-cell title="对方" :value="peerName" />
      <van-cell title="交易沟通分支" is-link @click="$router.push(`/conversations/${trade.conversation_id}`)" value="进入分支" />
    </van-cell-group>

    <!-- 约定区 -->
    <van-cell-group inset style="margin-top: 10px" title="交易约定（交付与支付安排）">
      <template v-if="trade.effective_agreement">
        <van-cell title="交付时间" :value="trade.effective_agreement.delivery_time" />
        <van-cell title="交付地点" :value="trade.effective_agreement.delivery_location" />
        <van-cell title="交付方式" :value="trade.effective_agreement.delivery_method" />
        <van-cell title="约定金额">
          <template #value><span class="price">￥{{ fen2yuan(trade.effective_agreement.amount_cents) }}</span></template>
        </van-cell>
        <van-cell title="支付方式" :value="trade.effective_agreement.payment_method" />
        <van-cell title="支付时点" :value="trade.effective_agreement.payment_timing" />
      </template>
      <van-cell v-else title="尚无有效约定" value="进行中可提出约定" />

      <div v-if="pendingForMe" class="pending-box">
        <div class="pending-title">对方提出了新{{ trade.effective_agreement ? '约定变更' : '约定' }}（第 {{ pendingForMe.round_no }} 轮）</div>
        <div class="pending-content">
          交付：{{ pendingForMe.delivery_time }} · {{ pendingForMe.delivery_location }} · {{ pendingForMe.delivery_method }}<br />
          支付：￥{{ fen2yuan(pendingForMe.amount_cents) }} · {{ pendingForMe.payment_method }} · {{ pendingForMe.payment_timing }}
        </div>
        <div class="btns">
          <van-button type="primary" size="small" @click="decideAgreement(true)">同意</van-button>
          <van-button type="danger" plain size="small" @click="decideAgreement(false)">拒绝</van-button>
        </div>
      </div>
      <div v-else-if="pendingByMe" class="pending-box muted">已提出第 {{ pendingByMe.round_no }} 轮提案，等待对方确认…</div>

      <div class="action-row" v-if="canProposeAgreement">
        <van-button size="small" type="primary" plain @click="showAgreement = true">
          {{ trade.effective_agreement ? '变更约定' : '提出约定' }}
        </van-button>
      </div>
    </van-cell-group>

    <!-- 完成确认区 -->
    <van-cell-group inset style="margin-top: 10px" title="完成确认（同时声明交付与支付完成）">
      <van-cell title="本人确认" :value="trade.my_confirmed ? '已确认' : '未确认'" />
      <van-cell title="对方确认" :value="trade.other_party_confirmed ? '已确认' : '未确认'" />
      <van-cell v-if="trade.confirm_wait_started_at" title="等待计时" :value="`单方确认于 ${fmtTime(trade.confirm_wait_started_at)}，7 天未回应转异常`" />
      <div class="action-row" v-if="canConfirm">
        <van-button size="small" type="primary" @click="confirmCompletion">提交完成确认</van-button>
      </div>
    </van-cell-group>

    <!-- 取消/争议区 -->
    <van-cell-group inset style="margin-top: 10px" title="取消与争议">
      <van-cell v-if="trade.cancel_requested_by && trade.cancel_requested_by !== session.user.id" title="取消申请">
        <template #value>
          <van-button size="small" type="danger" @click="confirmCancel">对方已申请取消，点击同意</van-button>
        </template>
      </van-cell>
      <van-cell v-else-if="trade.cancel_requested_by === session.user.id" title="取消申请" value="已发起，等待对方同意" />
      <div class="action-row">
        <van-button size="small" type="warning" plain :disabled="!canCancel" @click="cancel">发起取消</van-button>
        <van-button size="small" type="danger" plain :disabled="trade.status !== 'in_progress'" @click="dispute">发起争议</van-button>
        <van-button v-if="trade.status === 'disputed'" size="small" type="primary" plain @click="resolveDispute">
          {{ trade.resolution_confirmed_by_id === session.user.id ? '已确认解决，待对方' : '确认争议已解决' }}
        </van-button>
      </div>
    </van-cell-group>

    <!-- 转移历史 -->
    <van-cell-group inset style="margin-top: 10px" title="状态历史">
      <van-steps direction="vertical" :active="history.length - 1">
        <van-step v-for="t in history" :key="t.id">
          <h4>{{ tradeStatusLabels[t.from_status] || '创建' }} → {{ tradeStatusLabels[t.to_status] }}</h4>
          <p>{{ t.actor_role === 'admin' ? '管理员' : t.actor_role === 'system' ? '系统' : (t.actor_name || '用户') }} · {{ fmtTime(t.created_at) }}</p>
          <p v-if="t.reason">{{ t.reason }}</p>
        </van-step>
      </van-steps>
    </van-cell-group>

    <!-- 评价入口 -->
    <van-cell-group inset style="margin-top: 10px" v-if="trade.status === 'completed'">
      <van-cell title="交易评价" :value="trade.my_reviewed ? '已评价' : '未评价'" is-link @click="showReview = true" />
    </van-cell-group>

    <!-- 约定弹层 -->
    <van-popup v-model:show="showAgreement" position="bottom" round :style="{ maxHeight: '80%' }">
      <div class="popup">
        <h3>{{ trade.effective_agreement ? '变更约定（须对方同意）' : '提出约定' }}</h3>
        <van-field v-model="agreementForm.delivery_time" label="交付时间" placeholder="如：周六上午十点" />
        <van-field v-model="agreementForm.delivery_location" label="交付地点" placeholder="文字地点" />
        <van-field v-model="agreementForm.delivery_method" label="交付方式" placeholder="如：当面交付" />
        <van-field v-model="agreementAmountYuan" label="约定金额(元)" type="number" />
        <van-field v-model="agreementForm.payment_method" label="支付方式" placeholder="如：微信转账" />
        <van-field v-model="agreementForm.payment_timing" label="支付时点" placeholder="如：当面付清" />
        <van-button type="primary" block round style="margin-top: 12px" @click="proposeAgreement">发送提案</van-button>
      </div>
    </van-popup>

    <!-- 评价弹层 -->
    <van-popup v-model:show="showReview" position="bottom" round>
      <div class="popup">
        <h3>评价本笔交易（1—5 分）</h3>
        <van-rate v-model="reviewForm.rating" />
        <van-field v-model="reviewForm.content" type="textarea" rows="2" placeholder="文字评价（可选）" style="margin-top: 10px" />
        <van-button type="primary" block round style="margin-top: 12px" :disabled="trade.my_reviewed" @click="submitReview">
          {{ trade.my_reviewed ? '已评价' : '提交评价' }}
        </van-button>
        <p class="hint">评价仅在本人"我的评价"中按发表/收到查看，提交后不可修改或删除。</p>
      </div>
    </van-popup>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showConfirmDialog, showDialog, showToast } from 'vant'
import http from '../api/http'
import { fen2yuan, fmtTime, tradeStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'

const route = useRoute()
const session = useSession()
const trade = ref(null)
const history = ref([])
const showAgreement = ref(false)
const showReview = ref(false)
const agreementAmountYuan = ref('')
const agreementForm = reactive({
  delivery_time: '', delivery_location: '', delivery_method: '', payment_method: '', payment_timing: '',
})
const reviewForm = reactive({ rating: 5, content: '' })

const peerName = computed(() => (trade.value?.my_role === 'buyer' ? trade.value.seller.display_name : trade.value.buyer.display_name))
const statusType = computed(() =>
  ({ completed: 'success', terminated: 'danger', disputed: 'warning', abnormal: 'danger', in_progress: 'primary' }[trade.value?.status] || 'default'))

const pendingForMe = computed(() =>
  trade.value?.pending_agreement && trade.value.pending_agreement.proposer_id !== session.user.id
    ? trade.value.pending_agreement
    : null)
const pendingByMe = computed(() =>
  trade.value?.pending_agreement && trade.value.pending_agreement.proposer_id === session.user.id
    ? trade.value.pending_agreement
    : null)

const interactive = computed(() => ['in_progress', 'disputed'].includes(trade.value?.status) && !trade.value?.frozen)
const canProposeAgreement = computed(() => trade.value?.status === 'in_progress' && !trade.value.frozen && !trade.value.pending_agreement)
const canConfirm = computed(() => trade.value?.status === 'in_progress' && !trade.value.frozen && !!trade.value.effective_agreement && !trade.value.my_confirmed)
const canCancel = computed(() => interactive.value && (!trade.value.cancel_requested_by_id || true))

async function load() {
  trade.value = await http.get(`/trades/${route.params.id}`)
  history.value = await http.get(`/trades/${route.params.id}/transitions`)
}

async function proposeAgreement() {
  const f = agreementForm
  if (!f.delivery_time || !f.delivery_location || !f.delivery_method || !f.payment_method || !f.payment_timing) {
    return showToast('请完整填写约定要素')
  }
  await http.post(`/trades/${route.params.id}/agreements`, {
    ...f,
    amount_cents: Math.round(Number(agreementAmountYuan.value || 0) * 100),
  })
  showToast('提案已发送，等待对方确认')
  showAgreement.value = false
  load()
}

async function decideAgreement(accept) {
  const a = pendingForMe.value
  await showConfirmDialog({
    title: accept ? '同意约定' : '拒绝提案',
    message: accept ? '同意后约定生效，可分别提交完成确认。' : '拒绝只结束本次提案，可重新提出。',
  })
  await http.post(`/trades/${route.params.id}/agreements/${a.id}/${accept ? 'confirm' : 'reject'}`)
  showToast(accept ? '约定已生效' : '已拒绝该提案')
  load()
}

async function confirmCompletion() {
  await showConfirmDialog({
    title: '提交完成确认',
    message: '确认同时声明线下交付与支付均已完成；对方确认后交易完成。仅一方确认时开始 7 天等待。',
  })
  const data = await http.post(`/trades/${route.params.id}/confirmations`, {})
  showToast(data.detail)
  load()
}

async function cancel() {
  const { value } = await showDialog({
    title: '发起取消',
    message: '可选：填写取消说明',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (value === null) return
  const data = await http.post(`/trades/${route.params.id}/cancel`, { reason: value || null })
  showToast(data.detail)
  load()
}

async function confirmCancel() {
  await showConfirmDialog({ title: '同意取消', message: '双方同意后交易终止并计为失败。' })
  const data = await http.post(`/trades/${route.params.id}/cancel/confirm`, {})
  showToast(data.detail)
  load()
}

async function dispute() {
  const { value } = await showDialog({
    title: '发起争议',
    message: '争议须填写说明；交易保持锁单，不自动冻结。',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (!value) return
  const data = await http.post(`/trades/${route.params.id}/disputes`, { description: value })
  showToast('已进入争议状态')
  load()
}

async function resolveDispute() {
  const data = await http.post(`/trades/${route.params.id}/disputes/resolve`, {})
  showToast(data.detail)
  load()
}

async function submitReview() {
  await http.post(`/trades/${route.params.id}/review`, reviewForm)
  showToast('评价已提交')
  showReview.value = false
  load()
}

onMounted(load)
</script>

<style scoped>
.action-row {
  display: flex;
  gap: 8px;
  padding: 10px 16px;
  flex-wrap: wrap;
}
.pending-box {
  margin: 10px 16px;
  padding: 10px;
  border: 1px solid #1989fa;
  border-radius: 8px;
  font-size: 13px;
}
.pending-box.muted {
  border-color: #dcdee0;
  color: #969799;
}
.pending-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.pending-content {
  color: #646566;
}
.btns {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.popup {
  padding: 20px 16px calc(20px + var(--safe-bottom));
}
.hint {
  color: #969799;
  font-size: 12px;
  text-align: center;
  margin-top: 8px;
}
</style>
