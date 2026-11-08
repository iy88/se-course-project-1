<template>
  <div class="trade-panel">
    <el-card class="filter-card">
      <div class="query-bar">
        <span class="query-label">交易编号</span>
        <el-input-number v-model="tradeIdInput" :min="1" :controls="false" @change="onTradeIdChange" />
        <el-button :disabled="!tradeIdInput || actionBusy" :loading="tradeLoading" @click="load()">加载交易</el-button>

      </div>


      <div class="notice-stack">
        <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
          <template #default>
            <el-button v-if="tradeIdInput" size="small" @click="load()">重新加载</el-button>
          </template>
        </el-alert>
        <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon>
          <template #default>
            <el-button v-if="tradeIdInput" size="small" @click="load()">重新加载</el-button>
          </template>
        </el-alert>
      </div>
    </el-card>

    <el-card v-if="tradeLoading" class="data-card">
      <div class="load-skeleton">
        <el-skeleton :rows="5" animated />
      </div>
    </el-card>

    <el-card v-else-if="trade" class="summary-card">
      <template #header>
        <div class="card-head-row">
          <div>
            <span class="card-title">交易概要</span>
            <span class="card-sub">交易 #{{ trade.id }} · 当前状态 <span class="mono">{{ trade.status }}</span></span>
          </div>
          <el-tag v-if="trade.frozen" type="danger" effect="light">冻结中</el-tag>
          <el-tag v-else type="info" effect="plain">未冻结</el-tag>
        </div>
      </template>

      <el-descriptions :column="3" border>
        <el-descriptions-item label="交易#">{{ trade.id }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <span class="mono">{{ trade.status }}</span>
          <el-tag v-if="trade.frozen" type="danger" effect="light" class="inline-tag">冻结中</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="商品">
          {{ trade.product?.title }}（<span class="mono">{{ trade.product?.status }}</span>）
        </el-descriptions-item>
        <el-descriptions-item label="买方">{{ trade.buyer?.display_name }}#{{ trade.buyer?.id }}</el-descriptions-item>
        <el-descriptions-item label="卖方">{{ trade.seller?.display_name }}#{{ trade.seller?.id }}</el-descriptions-item>
        <el-descriptions-item label="当前约定">
          {{ currentAgreementText }}
        </el-descriptions-item>
        <el-descriptions-item label="当前有效确认" :span="2">{{ currentConfirmText }}</el-descriptions-item>
        <el-descriptions-item label="等待计时">{{ waitText }}</el-descriptions-item>
        <el-descriptions-item label="冻结原因" :span="3">
          {{ trade.frozen ? (trade.frozen_reason || '处置冻结') : '未冻结' }}
        </el-descriptions-item>
      </el-descriptions>

      <div class="trade-history-grid">
        <section>
          <div class="section-title"><h3>约定历史</h3></div>
          <div class="table-scroll table-compact">
            <el-table :data="trade.agreements" size="small" border>
              <el-table-column prop="round_no" label="轮次" width="62" />
              <el-table-column prop="status" label="状态" width="116" />
              <el-table-column label="金额" width="94">
                <template #default="{ row }">￥{{ (row.amount_cents / 100).toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="delivery_location" label="地点" />
              <el-table-column prop="payment_method" label="支付方式" width="108" />
            </el-table>
          </div>
        </section>

        <section>
          <div class="section-title"><h3>完成确认</h3></div>
          <div class="table-scroll table-compact">
            <el-table :data="trade.confirmations" size="small" border>
              <el-table-column label="确认人" width="190">
                <template #default="{ row }">{{ confirmerLabel(row) }}</template>
              </el-table-column>
              <el-table-column label="当前有效" width="92">
                <template #default="{ row }">{{ row.is_current ? '是' : '否' }}</template>
              </el-table-column>
              <el-table-column prop="confirmed_at" label="时间">
                <template #default="{ row }">{{ fmt(row.confirmed_at) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </section>
      </div>

      <div class="section-title transition-title"><h3>状态转移历史</h3></div>
      <div class="table-scroll">
        <el-table :data="trade.transitions" size="small" border max-height="340">
          <el-table-column prop="from_status" label="前状态" width="162" />
          <el-table-column prop="to_status" label="后状态" width="162" />
          <el-table-column prop="actor_role" label="主体" width="78" />
          <el-table-column prop="trigger" label="触发" width="136" />
          <el-table-column prop="reason" label="原因/依据" show-overflow-tooltip />
        </el-table>
      </div>

      <el-divider content-position="left">处置操作</el-divider>
      <el-form inline :disabled="!actionsEnabled" class="action-form trade-action-form">
        <div class="action-row">
          <el-form-item label="冻结理由">
            <el-input v-model="freezeReason" class="reason-input" placeholder="冻结须填写依据" />
          </el-form-item>
          <el-form-item class="button-item">
            <el-button
              type="warning"
              :loading="actionBusy"
              :disabled="!actionsEnabled || trade.frozen"
              @click="doFreeze"
            >
              冻结交易
            </el-button>
            <el-button
              type="success"
              :loading="actionBusy"
              :disabled="!actionsEnabled || !trade.frozen"
              @click="doUnfreeze"
            >
              解除冻结
            </el-button>
          </el-form-item>
        </div>

        <div class="action-row adjust-row">
          <el-form-item label="调整目标状态">
            <el-select v-model="adjustTarget" class="adjust-select">
              <el-option v-for="s in adjustTargets" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="依据">
            <el-input v-model="adjustReason" class="adjust-reason" placeholder="调整依据（必填，留据并通知双方）" />
          </el-form-item>
          <el-form-item class="button-item">
            <el-button type="danger" :loading="actionBusy" :disabled="!actionsEnabled" @click="doAdjust">
              执行调整
            </el-button>
          </el-form-item>
        </div>
      </el-form>
    </el-card>

  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import {
  beginTradeAction,
  beginTradeLoad,
  canUseLoadedTrade,
  createTradeSession,
  endTradeAction,
  failTradeLoad,
  finishTradeLoad,
  invalidateTradeSession,
  isSameTradeContext,
  normalizeTradeContext,
} from '../api/tradeContextState'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  caseId: { type: Number, required: true },
  tradeId: { type: Number, default: null },
})

const tradeIdInput = ref(Number(props.tradeId) || null)
const session = ref(createTradeSession())
const loadError = ref('')
const actionError = ref('')
const freezeReason = ref('')
const adjustTarget = ref('')
const adjustReason = ref('')
const adjustTargets = [
  { value: 'pending_acceptance', label: '待接受' },
  { value: 'in_progress', label: '进行中（恢复并清当前确认）' },
  { value: 'disputed', label: '有争议' },
  { value: 'abnormal', label: '异常交易' },
  { value: 'terminated', label: '已终止' },
  { value: 'completed', label: '已完成（不生成双方确认）' },
]

const fmtDuration = (seconds) => {
  const total = Number(seconds)
  if (!Number.isFinite(total) || total < 0) return ''
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days) return `${days} 天 ${hours} 小时`
  if (hours) return `${hours} 小时 ${minutes} 分`
  return `${minutes} 分`
}

const currentContext = computed(() => normalizeTradeContext(tradeIdInput.value, props.caseId))
const trade = computed(() => {
  const loaded = session.value.loaded
  return loaded && isSameTradeContext(loaded, currentContext.value) ? loaded.trade : null
})
const actionBusy = computed(() => session.value.actionBusy)
const tradeLoading = computed(() => session.value.loading)
const canQuery = computed(() => !!(currentContext.value.tradeId && currentContext.value.caseId))
const actionsEnabled = computed(() => canQuery.value && canUseLoadedTrade(session.value, currentContext.value))

const currentAgreementText = computed(() => {
  const t = trade.value
  if (!t?.current_agreement_id) return '无'
  const row = (t.agreements || []).find((a) => a.id === t.current_agreement_id)
  return row ? `第 ${row.round_no} 轮约定（约定#${row.id}）` : `约定#${t.current_agreement_id}`
})
const confirmerLabel = (row) => {
  const t = trade.value
  if (!t) return `#${row.confirmer_id}`
  if (row.confirmer_id === t.buyer?.id) return `买方 ${t.buyer?.display_name}（#${row.confirmer_id}）`
  if (row.confirmer_id === t.seller?.id) return `卖方 ${t.seller?.display_name}（#${row.confirmer_id}）`
  return `#${row.confirmer_id}`
}
const currentConfirmText = computed(() => {
  const rows = (trade.value?.confirmations || []).filter((c) => c.is_current)
  if (!rows.length) return '无当前有效声明'
  return rows.map((c) => {
    const role = c.confirmer_id === trade.value.buyer?.id ? '买方' : c.confirmer_id === trade.value.seller?.id ? '卖方' : `#${c.confirmer_id}`
    return `${role} ${fmt(c.confirmed_at)}`
  }).join('；')
})
const waitText = computed(() => {
  const t = trade.value
  if (!t) return ''
  const remaining = fmtDuration(t.confirm_wait_remaining_seconds)
  if (t.frozen && t.confirm_wait_paused_at) {
    return `暂停于 ${fmt(t.confirm_wait_paused_at)}${remaining ? `，剩余 ${remaining}` : ''}`
  }
  if (t.frozen) return '冻结期间不累计等待时间'
  if (t.confirm_wait_started_at) {
    return `自 ${fmt(t.confirm_wait_started_at)} 起算${remaining ? `，剩余 ${remaining}` : ''}`
  }
  return '无'
})

const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

function dropLoadedContext() {
  session.value = invalidateTradeSession(session.value)
}

function resetView() {
  dropLoadedContext()
  loadError.value = ''
  actionError.value = ''
}

function onTradeIdChange() {
  resetView()
  if (tradeIdInput.value) load()
}

async function load(expectedContext = null) {
  loadError.value = ''
  actionError.value = ''
  const ctx = currentContext.value
  if (expectedContext && !isSameTradeContext(expectedContext, ctx)) return
  if (!ctx.tradeId) {
    loadError.value = '请输入交易编号。'
    return
  }
  if (session.value.actionBusy) return
  session.value = beginTradeLoad(session.value, ctx)
  const seq = session.value.seq
  try {
    const data = await http.get(`/admin/trades/${ctx.tradeId}`, { params: { case_id: ctx.caseId } })
    const result = finishTradeLoad(session.value, { seq, context: ctx, trade: data })
    session.value = result.session
    if (!result.accepted && result.reason === 'trade-id') {
      loadError.value = '服务端返回的交易与当前交易不一致，请重新加载。'
    }
  } catch (err) {
    const failed = failTradeLoad(session.value, { seq, context: ctx })
    if (failed === session.value) return
    session.value = failed
    loadError.value = `交易加载失败：${serverDetail(err)}`
  }
}

async function executeAction(ctx, prefix, request, successMessage) {
  if (!isSameTradeContext(ctx, currentContext.value)) {
    return ElMessage.warning('交易上下文已变更，请重新确认')
  }
  if (!canQuery.value) return ElMessage.warning('请先加载与本事项相关的交易')
  const started = beginTradeAction(session.value, ctx)
  if (!started) {
    return ElMessage.warning(
      session.value.actionBusy ? '操作处理中，请勿重复提交' : '交易详情尚未加载，请重新加载',
    )
  }
  session.value = started
  actionError.value = ''
  const target = { ...started.actionTarget }
  try {
    const data = await request(target)
    ElMessage.success(typeof successMessage === 'function' ? successMessage(data) : successMessage)
    session.value = endTradeAction(session.value, ctx)
    await load(ctx)
  } catch (err) {
    session.value = endTradeAction(session.value, ctx)
    if (!isSameTradeContext(ctx, currentContext.value)) return
    await load(ctx)
    if (isSameTradeContext(ctx, currentContext.value)) {
      actionError.value = `${prefix}：${serverDetail(err)}`
    }
  }
}

async function doFreeze() {
  const ctx = currentContext.value
  if (!freezeReason.value.trim()) {
    actionError.value = '冻结须填写依据'
    return ElMessage.warning('冻结须填写依据')
  }
  await executeAction(
    ctx,
    '冻结失败',
    (target) =>
      http.post(`/admin/trades/${target.tradeId}/freeze`, {
        reason: freezeReason.value.trim(),
        case_id: target.caseId,
      }),
    '已冻结并通知双方',
  )
}

async function doUnfreeze() {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt('解除冻结依据', '解除冻结', { inputType: 'textarea' }))
  } catch {
    return
  }
  if (!value?.trim()) {
    actionError.value = '解除冻结须填写依据'
    return ElMessage.warning('解除冻结须填写依据')
  }
  const ctx = currentContext.value
  await executeAction(
    ctx,
    '解除冻结失败',
    (target) =>
      http.post(`/admin/trades/${target.tradeId}/unfreeze`, {
        reason: value.trim(),
        case_id: target.caseId,
      }),
    '已解除冻结',
  )
}

async function doAdjust() {
  if (!adjustTarget.value || !adjustReason.value.trim()) {
    actionError.value = '请选择目标状态并填写调整依据'
    return ElMessage.warning('请选择目标状态并填写调整依据')
  }
  try {
    await ElMessageBox.confirm(
      '确定调整交易状态？',
      '确认调整',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const ctx = currentContext.value
  await executeAction(
    ctx,
    '状态调整失败',
    (target) =>
      http.post(`/admin/trades/${target.tradeId}/adjust`, {
        to_status: adjustTarget.value,
        reason: adjustReason.value.trim(),
        case_id: target.caseId,
      }),
    (data) => data?.detail || '已调整并留据',
  )
}

onMounted(() => {
  if (tradeIdInput.value) load()
})

watch(
  () => props.tradeId,
  (value) => {
    resetView()
    tradeIdInput.value = Number(value) || null
    if (tradeIdInput.value) load()
  },
)
</script>

<style scoped>
.query-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.query-label {
  color: var(--ink-soft);
  font-size: 13px;
}
.trade-id-input {
  width: 220px;
}
.trade-id-text {
  font-weight: 650;
  color: var(--ink);
}
.query-hint {
  color: var(--ink-meta);
  font-size: 12px;
}
.trade-history-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}
.transition-title {
  margin-top: 18px;
}
.load-skeleton {
  padding: 4px 0;
  background: transparent;
}
.inline-tag {
  margin-left: 6px;
}
.reason-input {
  width: 240px;
}
.adjust-select {
  width: 220px;
}
.adjust-reason {
  width: 240px;
}
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0 16px;
  align-items: flex-start;
}
.action-row :deep(.el-form-item) {
  margin-bottom: 10px;
}
.adjust-row {
  margin-top: 2px;
}
.hint {
  color: var(--ink-meta);
  font-size: 12.5px;
}
.state-hint {
  margin: 6px 0 0;
  color: var(--ink-soft);
  font-size: 13px;
}
</style>
