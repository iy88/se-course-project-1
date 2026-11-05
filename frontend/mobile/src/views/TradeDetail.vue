<template>
  <div class="trade-page">
    <AppNavBar title="交易详情" />

    <div v-if="trade" class="view">
      <div v-if="session.hasFrozenTrade && !trade.frozen" class="alert alert--warn">
        <AppIcon name="alert" :size="17" />
        <span>您有其他交易处于冻结处置中：所有交易推进（接受/拒绝/撤回请求、约定、完成确认、取消、争议）暂停；收藏、既往评价、其他举报、第三方私聊及无关商品合规编辑不受影响。</span>
      </div>

      <div v-if="actionError" class="error-banner">
        <AppIcon name="alert" :size="17" />
        <span class="error-banner__text">{{ actionError }}</span>
        <van-button size="small" plain type="primary" @click="load">重新读取</van-button>
      </div>

      <div v-if="trade.frozen" class="freeze-box">
        <div class="freeze-box__title">
          <AppIcon name="alert" :size="18" />
          <span>交易已暂停</span>
        </div>
        <p>原因：{{ trade.frozen_reason || '处置冻结' }}。冻结期间推进、确认、取消、争议及双方互发消息暂停，历史只读；处置沟通保留。</p>
        <p v-if="waitPausedText" class="freeze-box__wait">完成确认等待：{{ waitPausedText }}</p>
        <p v-else-if="hasCurrentConfirmation" class="freeze-box__wait">当前完成声明保留；冻结期间不累计等待时间。</p>
      </div>

      <section class="surface trade-section">
        <header class="trade-section__head">
          <h2>交易概览</h2>
        </header>
        <van-cell title="商品" :value="trade.product_title" is-link @click="$router.push(`/products/${trade.product_id}`)" />
        <van-cell title="状态">
          <template #value>
            <span class="pill" :class="statusTone">{{ tradeStatusLabels[trade.status] }}</span>
            <span v-if="trade.frozen" class="pill pill--danger trade-status-gap">冻结中</span>
          </template>
        </van-cell>
        <van-cell title="我的身份" :value="trade.my_role === 'buyer' ? '买方' : '卖方'" />
        <van-cell title="对方" :value="peerName" />
        <van-cell title="交易沟通分支" is-link value="进入分支" @click="$router.push(`/conversations/${trade.conversation_id}`)" />
      </section>

      <section v-if="trade.status === 'pending_acceptance'" class="surface trade-section">
        <header class="trade-section__head">
          <h2>购买请求</h2>
          <span>等待卖方接受</span>
        </header>
        <van-cell title="当前状态" value="等待卖方接受" />
        <div v-if="trade.my_role === 'seller'" class="action-row">
          <van-button size="small" type="primary" :disabled="!canAcceptRequest" @click="acceptRequest">接受请求</van-button>
          <van-button size="small" type="danger" plain :disabled="!canRejectRequest" @click="rejectRequest">拒绝请求</van-button>
        </div>
        <div v-else class="action-row">
          <van-button size="small" type="warning" plain :disabled="!canWithdrawRequest" @click="withdrawRequest">撤回请求</van-button>
        </div>
        <p v-if="!requestActionAllowed" class="hint">
          当前状态下不能推进该购买请求；交易冻结、账户封禁或请求已处理时以服务端结果为准。
        </p>
      </section>

      <section class="surface trade-section">
        <header class="trade-section__head">
          <h2>交易约定</h2>
          <span>交付与支付安排</span>
        </header>

        <template v-if="trade.effective_agreement">
          <van-cell title="交付时间" :value="trade.effective_agreement.delivery_time" />
          <van-cell title="交付地点" :value="trade.effective_agreement.delivery_location" />
          <van-cell title="交付方式" :value="trade.effective_agreement.delivery_method" />
          <van-cell title="约定金额">
            <template #value><span class="price price--sm"><span class="price__symbol">￥</span>{{ fen2yuan(trade.effective_agreement.amount_cents) }}</span></template>
          </van-cell>
          <van-cell title="支付方式" :value="trade.effective_agreement.payment_method" />
          <van-cell title="支付时点" :value="trade.effective_agreement.payment_timing" />
        </template>
        <van-cell v-else title="尚无有效约定" value="进行中可提出约定" />

        <div v-if="hasCurrentConfirmation" class="reset-hint">
          一方或双方已有当前完成确认。变更约定须对方明确同意；同意生效后将清空双方当前确认并结束旧计时，原约定、确认及计时历史保留。
        </div>

        <div v-if="pendingForMe" class="pending-box">
          <div class="pending-box__title">对方提出了新{{ trade.effective_agreement ? '约定变更' : '约定' }}（第 {{ pendingForMe.round_no }} 轮）</div>
          <div class="pending-box__content">
            交付：{{ pendingForMe.delivery_time }} · {{ pendingForMe.delivery_location }} · {{ pendingForMe.delivery_method }}<br />
            支付：￥{{ fen2yuan(pendingForMe.amount_cents) }} · {{ pendingForMe.payment_method }} · {{ pendingForMe.payment_timing }}
          </div>
          <div class="btns">
            <van-button type="primary" size="small" :disabled="!canDecideAgreement" @click="decideAgreement(true)">同意</van-button>
            <van-button type="danger" plain size="small" :disabled="!canDecideAgreement" @click="decideAgreement(false)">拒绝</van-button>
          </div>
        </div>
        <div v-else-if="pendingByMe" class="pending-box pending-box--muted">已提出第 {{ pendingByMe.round_no }} 轮提案，等待对方确认…</div>

        <div v-if="canProposeAgreement" class="action-row">
          <van-button size="small" type="primary" plain @click="openAgreementForm">
            {{ trade.effective_agreement ? '变更约定' : '提出约定' }}
          </van-button>
        </div>

        <van-collapse v-if="agreementHistory.length" v-model="agreementOpen" class="history-collapse">
          <van-collapse-item :title="`约定历史（${agreementHistory.length} 轮）`" name="agreements">
            <div v-for="a in agreementHistory" :key="a.id" class="history-item">
              <div class="history-item__head">
                第 {{ a.round_no }} 轮 · {{ agreementStatusLabel(a.status) }} · {{ actorName(a.proposer_id) }}提出
              </div>
              <div>交付：{{ a.delivery_time }} · {{ a.delivery_location }} · {{ a.delivery_method }}</div>
              <div>支付：￥{{ fen2yuan(a.amount_cents) }} · {{ a.payment_method }} · {{ a.payment_timing }}</div>
              <div class="muted">提出 {{ fmtTime(a.proposed_at) }}<span v-if="a.decided_at"> · 处理 {{ fmtTime(a.decided_at) }}</span></div>
            </div>
          </van-collapse-item>
        </van-collapse>
      </section>

      <section class="surface trade-section">
        <header class="trade-section__head">
          <h2>完成确认</h2>
          <span>同时声明交付与支付完成</span>
        </header>
        <van-cell title="本人确认" :value="trade.my_confirmed ? '已确认' : '未确认'" />
        <van-cell title="对方确认" :value="trade.other_party_confirmed ? '已确认' : '未确认'" />
        <van-cell v-if="waitStatusText" title="等待计时" :value="waitStatusText" />

        <div class="current-confirm">
          <div class="current-confirm__title">当前有效完成声明</div>
          <div v-for="c in currentConfirmations" :key="c.id" class="confirm-row">
            {{ actorName(c.confirmer_id) }} · {{ fmtTime(c.confirmed_at) }}
            <span v-if="c.note" class="muted"> · {{ c.note }}</span>
          </div>
          <div v-if="!currentConfirmations.length" class="muted confirm-empty">暂无当前完成声明</div>
        </div>

        <div v-if="canConfirm" class="action-row">
          <van-button size="small" type="primary" @click="confirmCompletion">提交完成确认</van-button>
        </div>
        <div v-else-if="trade.frozen" class="action-row">
          <span class="muted">冻结期间暂停完成确认；解冻且原确认有效时按服务端剩余时间续算。</span>
        </div>

        <van-collapse v-if="confirmationHistory.length" v-model="confirmationOpen" class="history-collapse">
          <van-collapse-item :title="`完成声明历史（${confirmationHistory.length} 条）`" name="confirmations">
            <div v-for="c in confirmationHistory" :key="c.id" class="history-item">
              <div class="history-item__head">
                {{ actorName(c.confirmer_id) }} · {{ fmtTime(c.confirmed_at) }}
                <span class="pill" :class="c.is_current ? 'pill--ok' : ''" style="margin-left: 6px">
                  {{ c.is_current ? '当前有效' : '已结束' }}
                </span>
              </div>
              <div v-if="c.note" class="muted">{{ c.note }}</div>
            </div>
          </van-collapse-item>
        </van-collapse>
      </section>

      <section class="surface trade-section">
        <header class="trade-section__head">
          <h2>取消与争议</h2>
        </header>
        <van-cell v-if="trade.cancel_requested_by && trade.cancel_requested_by !== session.user.id" title="取消申请">
          <template #value>
            <van-button size="small" type="danger" :disabled="!canDecideCancel" @click="confirmCancel">对方已申请取消，点击同意</van-button>
          </template>
        </van-cell>
        <van-cell v-else-if="trade.cancel_requested_by === session.user.id" title="取消申请" value="已发起，等待对方同意" />
        <div class="action-row">
          <van-button size="small" type="warning" plain :disabled="!canCancel" @click="cancel">发起取消</van-button>
          <van-button size="small" type="danger" plain :disabled="!canDispute" @click="dispute">发起争议</van-button>
          <van-button v-if="trade.status === 'disputed'" size="small" type="primary" plain
            :disabled="!canResolveDispute" @click="resolveDispute">
            {{ trade.resolution_confirmed_by === session.user.id ? '已确认解决，待对方' : '确认争议已解决' }}
          </van-button>
        </div>
        <p v-if="trade.frozen" class="hint">交易冻结中：取消、争议及解决操作暂停，仅保留只读与处置沟通。</p>
      </section>

      <section class="surface trade-section">
        <header class="trade-section__head">
          <h2>状态历史</h2>
        </header>
        <div class="history-steps">
          <van-steps direction="vertical" :active="history.length - 1">
            <van-step v-for="t in history" :key="t.id">
              <h4>{{ tradeStatusLabels[t.from_status] || '创建' }} → {{ tradeStatusLabels[t.to_status] }}</h4>
              <p>{{ t.actor_role === 'admin' ? '管理员' : t.actor_role === 'system' ? '系统' : (t.actor_name || '用户') }} · {{ fmtTime(t.created_at) }}</p>
              <p v-if="t.reason">{{ t.reason }}</p>
            </van-step>
          </van-steps>
          <div v-if="!history.length" class="empty-inline">暂无状态历史</div>
        </div>
      </section>

      <section v-if="trade.status === 'completed'" class="surface trade-section">
        <header class="trade-section__head">
          <h2>交易评价</h2>
        </header>
        <van-cell title="交易评价" :value="trade.my_reviewed ? '已评价' : '未评价'" :is-link="canWrite"
          @click="canWrite && (showReview = true)" />
      </section>
    </div>

    <div v-else-if="loadError" class="view">
      <div class="error-banner">
        <AppIcon name="alert" :size="18" />
        <span class="error-banner__text">{{ loadError }}</span>
        <van-button size="small" plain type="primary" @click="load">重新加载</van-button>
      </div>
    </div>

    <van-popup v-model:show="showAgreement" position="bottom" round class="app-bottom-popup">
      <div class="popup-panel">
        <h3>{{ trade?.effective_agreement ? '变更约定（须对方同意）' : '提出约定' }}</h3>
        <p v-if="hasCurrentConfirmation" class="popup-warn">
          当前已有完成确认。变更生效会清空双方当前确认并结束旧计时，需对方同意；不同意则原约定、确认和计时都保留。
        </p>
        <div class="popup-fields">
          <TextField :limit="200" v-model="agreementForm.delivery_time" label="交付时间" placeholder="如：周六上午十点"  />
          <TextField :limit="200" v-model="agreementForm.delivery_location" label="交付地点" placeholder="文字地点"  />
          <TextField :limit="200" v-model="agreementForm.delivery_method" label="交付方式" placeholder="如：当面交付"  />
          <van-field v-model="agreementAmountYuan" label="约定金额(元)" type="number" />
          <TextField :limit="100" v-model="agreementForm.payment_method" label="支付方式" placeholder="如：微信转账"  />
          <TextField :limit="200" v-model="agreementForm.payment_timing" label="支付时点" placeholder="如：当面付清"  />
        </div>
        <van-button type="primary" block style="margin-top: 14px" :disabled="!canWrite" @click="proposeAgreement">发送提案</van-button>
      </div>
    </van-popup>

    <van-popup v-model:show="showReview" position="bottom" round class="app-bottom-popup">
      <div class="popup-panel">
        <h3>评价本笔交易（1—5 分）</h3>
        <van-rate v-model="reviewForm.rating" />
        <TextField :limit="1000" v-model="reviewForm.content" type="textarea" rows="2" placeholder="文字评价（可选）" style="margin-top: 10px"  />
        <van-button type="primary" block style="margin-top: 12px" :disabled="trade?.my_reviewed || !canWrite" @click="submitReview">
          {{ trade?.my_reviewed ? '已评价' : '提交评价' }}
        </van-button>
        <p class="hint hint--left">评价仅在本人"我的评价"中按发表/收到查看，提交后不可修改或删除。</p>
      </div>
    </van-popup>
  </div>
</template>

<script setup>
import TextField from '../components/TextField.vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { showConfirmDialog, showDialog, showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import http from '../api/http'
import { fen2yuan, fmtDuration, fmtTime, tradeStatusLabels } from '../api/labels'
import { useSession } from '../stores/session'

const route = useRoute()
const session = useSession()
const trade = ref(null)
const history = ref([])
const loadError = ref('')
const actionError = ref('')
const showAgreement = ref(false)
const showReview = ref(false)
const agreementOpen = ref([])
const confirmationOpen = ref([])
const agreementAmountYuan = ref('')
const agreementForm = reactive({
  delivery_time: '', delivery_location: '', delivery_method: '', payment_method: '', payment_timing: '',
})
const reviewForm = reactive({ rating: 5, content: '' })

const peerName = computed(() => (trade.value?.my_role === 'buyer' ? trade.value.seller.display_name : trade.value.buyer.display_name))
const statusTone = computed(() =>
  ({
    completed: 'pill--ok',
    terminated: 'pill--danger',
    disputed: 'pill--warn',
    abnormal: 'pill--danger',
    in_progress: 'pill--brand',
    pending_acceptance: 'pill--info',
  }[trade.value?.status] || ''))

const pendingForMe = computed(() =>
  trade.value?.pending_agreement && trade.value.pending_agreement.proposer_id !== session.user.id
    ? trade.value.pending_agreement
    : null)
const pendingByMe = computed(() =>
  trade.value?.pending_agreement && trade.value.pending_agreement.proposer_id === session.user.id
    ? trade.value.pending_agreement
    : null)

const currentConfirmations = computed(() => (trade.value?.confirmations || []).filter((c) => c.is_current))
const confirmationHistory = computed(() => [...(trade.value?.confirmations || [])].reverse())
const agreementHistory = computed(() => [...(trade.value?.agreement_history || [])].reverse())
const hasCurrentConfirmation = computed(
  () => currentConfirmations.value.length > 0 || trade.value?.my_confirmed || trade.value?.other_party_confirmed,
)

const canWrite = computed(() => session.user?.status !== 'banned')
// BR-33/D-50：has_frozen_trade 是用户级交易资格；任一交易冻结时，所有交易推进写操作都不可用。
// 收藏、既往评价、其他举报、第三方普通私聊及无关商品合规编辑仍按各自规则处理。
const tradeWriteAllowed = computed(() => canWrite.value && !session.hasFrozenTrade)
const requestActionAllowed = computed(
  () => trade.value?.status === 'pending_acceptance' && !trade.value?.frozen && tradeWriteAllowed.value,
)
const canAcceptRequest = computed(() => requestActionAllowed.value && trade.value?.my_role === 'seller')
const canRejectRequest = computed(() => requestActionAllowed.value && trade.value?.my_role === 'seller')
const canWithdrawRequest = computed(() => requestActionAllowed.value && trade.value?.my_role === 'buyer')
const interactive = computed(
  () => ['in_progress', 'disputed'].includes(trade.value?.status) && !trade.value?.frozen && tradeWriteAllowed.value,
)
const canProposeAgreement = computed(
  () => trade.value?.status === 'in_progress' && !trade.value.frozen && !trade.value.pending_agreement && tradeWriteAllowed.value,
)
const canConfirm = computed(
  () => trade.value?.status === 'in_progress' && !trade.value.frozen && !!trade.value.effective_agreement && !trade.value.my_confirmed && tradeWriteAllowed.value,
)
const canDecideAgreement = computed(() => !trade.value?.frozen && tradeWriteAllowed.value)
const canDecideCancel = computed(() => !trade.value?.frozen && tradeWriteAllowed.value)
const canCancel = computed(
  () => interactive.value && !trade.value?.cancel_requested_by,
)
const canDispute = computed(
  () => trade.value?.status === 'in_progress' && !trade.value.frozen && tradeWriteAllowed.value,
)
const canResolveDispute = computed(
  () => trade.value?.status === 'disputed' && !trade.value.frozen && tradeWriteAllowed.value,
)

const remainingText = computed(() => fmtDuration(trade.value?.confirm_wait_remaining_seconds))
const waitPausedText = computed(() => {
  if (!trade.value?.frozen || !trade.value?.confirm_wait_paused_at) return ''
  return `已暂停于 ${fmtTime(trade.value.confirm_wait_paused_at)}${remainingText.value ? `，剩余 ${remainingText.value}` : '，剩余时间以服务端记录为准'}`
})
const waitStatusText = computed(() => {
  if (waitPausedText.value) return waitPausedText.value
  if (trade.value?.frozen) return '冻结期间等待计时暂停'
  if (!trade.value?.confirm_wait_started_at) return ''
  const suffix = remainingText.value ? `，剩余 ${remainingText.value}` : '，剩余时间以服务端为准'
  return `自 ${fmtTime(trade.value.confirm_wait_started_at)} 起算${suffix}（页面不按自然时间倒数）`
})

const agreementStatusLabel = (s) =>
  ({ proposed: '提案中', confirmed: '已生效', rejected: '已拒绝', superseded: '已被后续变更替代' }[s] || s)

function actorName(id) {
  if (!id) return '系统'
  if (id === session.user?.id) return '我'
  if (id === trade.value?.buyer?.id) return `${trade.value.buyer.display_name}（买方）`
  if (id === trade.value?.seller?.id) return `${trade.value.seller.display_name}（卖方）`
  return `用户 #${id}`
}

const serverDetail = (err) =>
  typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败，请稍后重试'

function keepStateOnFailure(prefix, err) {
  // 不用失败响应改写本页状态；保留当前交易与表单，由用户重新读取或重试。
  actionError.value = `${prefix}：${serverDetail(err)}。已保留当前页面与表单状态，未显示成功。`
  if (err?.response?.status === 403) {
    // 冻结/封禁或身份变化可能由服务端先拒绝；刷新用户级资格，及时收起不可用动作。
    session.refreshUser().catch(() => {})
  }
}

async function load() {
  loadError.value = ''
  actionError.value = ''
  try {
    trade.value = await http.get(`/trades/${route.params.id}`)
  } catch {
    loadError.value = '交易详情加载失败，可重试。'
    return
  }
  history.value = await http.get(`/trades/${route.params.id}/transitions`).catch(() => [])
}

async function acceptRequest() {
  if (!canAcceptRequest.value) return
  try {
    await showConfirmDialog({
      title: '接受购买请求',
      message: '接受后锁单，商品进入交易中，并关闭该商品其他待接受请求。',
    })
  } catch {
    return
  }
  if (!canAcceptRequest.value) return
  actionError.value = ''
  try {
    const data = await http.post(`/trades/${route.params.id}/accept`, {})
    showToast(data.detail)
    await load()
  } catch (err) {
    keepStateOnFailure('接受购买请求失败', err)
  }
}

async function rejectRequest() {
  if (!canRejectRequest.value) return
  const { value } = await showDialog({
    title: '拒绝购买请求',
    message: '可选：填写拒绝说明',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (value === null) return
  actionError.value = ''
  try {
    const data = await http.post(`/trades/${route.params.id}/reject`, { reason: value || null })
    showToast(data.detail)
    await load()
  } catch (err) {
    keepStateOnFailure('拒绝购买请求失败', err)
  }
}

async function withdrawRequest() {
  if (!canWithdrawRequest.value) return
  try {
    await showConfirmDialog({ title: '撤回购买请求', message: '撤回后该请求结束，可在商品页重新发起。' })
  } catch {
    return
  }
  actionError.value = ''
  try {
    const data = await http.post(`/trades/${route.params.id}/withdraw`, {})
    showToast(data.detail)
    await load()
  } catch (err) {
    keepStateOnFailure('撤回购买请求失败', err)
  }
}

function openAgreementForm() {
  if (!canProposeAgreement.value) return
  const a = trade.value?.effective_agreement
  if (a) {
    agreementForm.delivery_time = a.delivery_time
    agreementForm.delivery_location = a.delivery_location
    agreementForm.delivery_method = a.delivery_method
    agreementForm.payment_method = a.payment_method
    agreementForm.payment_timing = a.payment_timing
    agreementAmountYuan.value = fen2yuan(a.amount_cents)
  }
  showAgreement.value = true
}

async function proposeAgreement() {
  if (!canProposeAgreement.value) return
  const f = agreementForm
  if (!f.delivery_time || !f.delivery_location || !f.delivery_method || !f.payment_method || !f.payment_timing) {
    return showToast('请完整填写约定要素')
  }
  actionError.value = ''
  try {
    await http.post(`/trades/${route.params.id}/agreements`, {
      ...f,
      amount_cents: Math.round(Number(agreementAmountYuan.value || 0) * 100),
    })
    showToast('提案已发送，等待对方确认')
    showAgreement.value = false
    await load()
  } catch (err) {
    keepStateOnFailure('约定提案提交失败', err)
  }
}

async function decideAgreement(accept) {
  const a = pendingForMe.value
  if (!a || !canDecideAgreement.value) return
  try {
    await showConfirmDialog({
      title: accept ? '同意约定' : '拒绝提案',
      message: accept
        ? (hasCurrentConfirmation.value
          ? '同意后新约定生效：双方当前完成确认将被清空、旧计时结束并保留历史；之后任一方重新确认才重新计时。'
          : '同意后约定生效，可分别提交完成确认。')
        : '拒绝只结束本次提案，可重新提出；原约定、当前确认和计时不变。',
    })
  } catch {
    return
  }
  if (!canDecideAgreement.value) return
  actionError.value = ''
  try {
    await http.post(`/trades/${route.params.id}/agreements/${a.id}/${accept ? 'confirm' : 'reject'}`)
    showToast(accept ? '约定已生效' : '已拒绝该提案')
    await load()
  } catch (err) {
    keepStateOnFailure(accept ? '同意约定失败' : '拒绝约定失败', err)
  }
}

async function confirmCompletion() {
  if (!canConfirm.value) return
  try {
    await showConfirmDialog({
      title: '提交完成确认',
      message: '确认同时声明线下交付与支付均已完成；对方确认后交易完成。仅一方确认时开始 7 天等待。',
    })
  } catch {
    return
  }
  if (!canConfirm.value) return
  actionError.value = ''
  try {
    const data = await http.post(`/trades/${route.params.id}/confirmations`, {})
    showToast(data.detail)
    await load()
  } catch (err) {
    keepStateOnFailure('提交完成确认失败', err)
  }
}

async function cancel() {
  if (!canCancel.value) return
  const { value } = await showDialog({
    title: '发起取消',
    message: '可选：填写取消说明',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (value === null) return
  actionError.value = ''
  try {
    const data = await http.post(`/trades/${route.params.id}/cancel`, { reason: value || null })
    showToast(data.detail)
    await load()
  } catch (err) {
    keepStateOnFailure('发起取消失败', err)
  }
}

async function confirmCancel() {
  if (!canDecideCancel.value) return
  try {
    await showConfirmDialog({ title: '同意取消', message: '双方同意后交易终止并计为失败。' })
  } catch {
    return
  }
  if (!canDecideCancel.value) return
  actionError.value = ''
  try {
    const data = await http.post(`/trades/${route.params.id}/cancel/confirm`, {})
    showToast(data.detail)
    await load()
  } catch (err) {
    keepStateOnFailure('同意取消失败', err)
  }
}

async function dispute() {
  if (!canDispute.value) return
  const { value } = await showDialog({
    title: '发起争议',
    message: '争议须填写说明；交易保持锁单，不自动冻结。',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (!value) return
  actionError.value = ''
  try {
    await http.post(`/trades/${route.params.id}/disputes`, { description: value })
    showToast('已进入争议状态')
    await load()
  } catch (err) {
    keepStateOnFailure('发起争议失败', err)
  }
}

async function resolveDispute() {
  if (!canResolveDispute.value) return
  actionError.value = ''
  try {
    const data = await http.post(`/trades/${route.params.id}/disputes/resolve`, {})
    showToast(data.detail)
    await load()
  } catch (err) {
    keepStateOnFailure('确认争议解决失败', err)
  }
}

async function submitReview() {
  if (!canWrite.value || trade.value?.my_reviewed) return
  actionError.value = ''
  try {
    await http.post(`/trades/${route.params.id}/review`, reviewForm)
    showToast('评价已提交')
    showReview.value = false
    await load()
  } catch (err) {
    // 评价不受交易冻结影响，但封禁仍禁写；失败时保留弹层中的评分与文字。
    keepStateOnFailure('评价提交失败', err)
  }
}

onMounted(load)
watch(() => route.params.id, () => {
  trade.value = null
  load()
})
</script>

<style scoped>
.trade-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.freeze-box {
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid #e8cbc7;
  border-radius: var(--radius);
  background: var(--danger-soft);
  color: #7d2e28;
  font-size: 12.5px;
  line-height: 1.55;
}

.freeze-box__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  font-weight: 650;
}

.freeze-box p {
  margin: 6px 0 0;
}

.freeze-box__wait {
  padding-top: 6px;
  border-top: 1px dashed #e0bdb8;
}

.trade-section {
  margin-bottom: 12px;
  overflow: hidden;
}

.trade-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.trade-section__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.trade-section__head span {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.trade-status-gap {
  margin-left: 6px;
}

.action-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 11px 16px;
}

.action-row + .action-row {
  padding-top: 0;
}

.hint {
  margin: 0;
  padding: 0 16px 12px;
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.55;
}

.hint--left {
  text-align: left;
  padding: 8px 0 0;
}

.pending-box {
  margin: 10px 12px;
  padding: 11px 12px;
  border: 1px solid #cfe3d7;
  border-radius: 10px;
  background: #fbfdfb;
  font-size: 12.5px;
  line-height: 1.55;
}

.pending-box--muted {
  border-color: var(--line);
  background: #f7f9f7;
  color: var(--ink-meta);
}

.pending-box__title {
  font-weight: 650;
  font-size: 13px;
  margin-bottom: 4px;
}

.pending-box__content {
  color: var(--ink-soft);
}

.btns {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.reset-hint {
  margin: 10px 12px;
  padding: 9px 11px;
  border: 1px solid #ebd8b6;
  border-radius: 9px;
  background: var(--warn-soft);
  color: #6f4c0d;
  font-size: 11.5px;
  line-height: 1.55;
}

.current-confirm {
  padding: 10px 16px 4px;
  border-top: 1px solid var(--line);
}

.current-confirm__title {
  margin-bottom: 5px;
  font-size: 12.5px;
  font-weight: 650;
  color: var(--ink-soft);
}

.confirm-row {
  padding: 2px 0;
  font-size: 12.5px;
  line-height: 1.55;
}

.confirm-empty {
  padding: 2px 0 4px;
  font-size: 12.5px;
}

.history-collapse {
  margin-top: 2px;
  border-top: 1px solid var(--line);
}

.history-item {
  padding: 7px 0;
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
  line-height: 1.6;
}

.history-item:last-child {
  border-bottom: 0;
}

.history-item__head {
  font-weight: 600;
  color: var(--ink-soft);
}

.history-steps {
  padding: 14px 16px 10px;
}

.history-steps h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.history-steps p {
  margin: 2px 0 0;
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.5;
}

.empty-inline {
  padding: 18px 0;
  color: var(--ink-meta);
  font-size: 12.5px;
  text-align: center;
}

.popup-panel {
  max-height: 86vh;
  overflow-y: auto;
}

.popup-warn {
  margin: 0 0 10px;
  padding: 9px 11px;
  border: 1px solid #ebd8b6;
  border-radius: 9px;
  background: var(--warn-soft);
  color: #6f4c0d;
  font-size: 11.5px;
  line-height: 1.55;
}

.popup-fields {
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}

.popup-fields :deep(.van-field) {
  padding: 10px 12px;
}

.popup-fields :deep(.van-field::after) {
  left: 12px;
  right: 12px;
  border-color: var(--line);
}

.popup-fields :deep(.van-field:last-child::after) {
  display: none;
}

.popup-fields :deep(.van-field__label) {
  width: 80px;
  margin-right: 8px;
  color: var(--ink-soft);
  font-size: 12.5px;
}

.popup-panel :deep(.van-rate) {
  padding: 2px 0 4px;
}

@media (max-width: 359px) {
  .trade-section__head,
  .action-row,
  .current-confirm,
  .history-steps {
    padding-left: 12px;
    padding-right: 12px;
  }

  .hint {
    padding-left: 12px;
    padding-right: 12px;
  }

  .pending-box,
  .reset-hint {
    margin-left: 10px;
    margin-right: 10px;
  }
}
</style>
