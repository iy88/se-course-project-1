<template>
  <div class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">处置</p>
        <h1>交易处置</h1>
        <p class="sub">须关联本人认领事项；冻结、解冻和状态调整基于该事项执行，并记录依据、通知双方。</p>
      </div>
      <div class="page-head-actions">
        <el-button :loading="casesLoading" @click="loadCases">
          <el-icon><AppIcon name="refresh" /></el-icon>
          刷新事项
        </el-button>
      </div>
    </header>

    <el-card class="filter-card">
      <template #header>
        <div class="card-head-row">
          <div>
            <span class="card-title">事项上下文</span>
            <span class="card-sub">选择本人认领且与本交易相关的事项后加载交易。</span>
          </div>
          <span class="result-count">可用事项 {{ caseOptions.length }} 个</span>
        </div>
      </template>

      <el-form inline class="trade-query-form">
        <el-form-item label="交易 ID">
          <el-input-number v-model="tradeId" :min="1" :controls="false" class="trade-id-input" @change="onTradeIdChange" />
        </el-form-item>
        <el-form-item label="关联事项">
          <el-select
            v-model="caseSelectValue"
            filterable
            clearable
            placeholder="选择本人认领且相关的事项"
            class="case-select"
            :loading="casesLoading"
            @change="onCaseChange"
          >
            <el-option v-for="c in caseOptions" :key="c.id" :label="caseOptionLabel(c)" :value="c.id" />
          </el-select>
          <el-button :loading="casesLoading" @click="loadCases">刷新事项</el-button>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="tradeLoading" :disabled="!canQuery || actionBusy" @click="load()">
            加载交易
          </el-button>
        </el-form-item>
      </el-form>

      <div class="notice-stack context-notices">
        <el-alert
          v-if="!caseId"
          title="请选择本人认领且与本交易相关的事项后再加载交易。"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-alert v-if="casesError" :title="casesError" type="error" :closable="false" show-icon>
          <template #default>
            <el-button size="small" @click="loadCases">重试</el-button>
          </template>
        </el-alert>
        <el-alert
          v-if="selectedCase && !isCaseClaimant"
          title="该事项非本人认领：不能查看私人交易详情或执行冻结、解冻、状态调整。"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-alert
          v-if="selectedCase && directMismatch"
          :title="`所选事项直接关联交易 #${selectedCase.trade_id}，与当前交易 #${tradeId} 不一致；不能用于本交易。`"
          type="error"
          :closable="false"
          show-icon
        />
        <el-alert
          v-if="selectedCase && !directMismatch && !caseHasDirectTrade"
          title="该事项未直接关联本交易；加载后请核对交易概要是否与事项相关。"
          type="info"
          :closable="false"
          show-icon
        />
        <el-alert
          v-if="caseContext"
          :title="`关联事项 #${caseContext.id}（${caseContext.title}）· ${caseStatusLabel(caseContext.status)} · 认领人 #${caseContext.claimed_by_id || '未认领'}`"
          :type="isCaseClaimant ? 'success' : 'warning'"
          :closable="false"
          show-icon
        />
        <el-alert
          v-if="caseContext && caseContext.status === 'disposed' && isCaseClaimant"
          title="事项已处置：仍可基于该事项办理后续解冻或状态调整。"
          type="info"
          :closable="false"
          show-icon
        />
        <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
          <template #default>
            <el-button v-if="canQuery" size="small" @click="load()">重新加载</el-button>
          </template>
        </el-alert>
        <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon>
          <template #default>
            <el-button v-if="canQuery" size="small" @click="load()">重新加载</el-button>
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
          {{ trade.current_agreement_id ? `约定#${trade.current_agreement_id}` : '无' }}
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
              <el-table-column prop="confirmer_id" label="确认人" width="84" />
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
      <p v-if="!actionsEnabled" class="hint">
        需先选择本人认领且与本交易相关的事项；已处置事项仍可用于后续合法解冻或调整。
      </p>
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

    <el-card v-else-if="!loadError" class="data-card">
      <div class="state-block">
        <span class="state-icon"><AppIcon name="trades" :size="24" /></span>
        <p class="state-title">尚未加载交易</p>
        <p v-if="!canQuery">选择本人认领且与本交易相关的事项后加载交易。</p>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import { ensureAdminUser } from '../api/session'
import { caseCanContextTrade, isDirectTradeMismatch, ownedUsableCases } from '../api/tradeCaseContext'
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
import AppIcon from '../components/AppIcon.vue'

const route = useRoute()
const tradeId = ref(Number(route.query.trade_id) || null)
const caseId = ref(Number(route.query.case_id) || 0)
const session = ref(createTradeSession())
const caseOptions = ref([])
const adminId = ref(null)
const casesLoading = ref(false)
const casesError = ref('')
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

// 未选择事项时按 null 展示占位符；内部仍沿用 0 表示未选择，不改变上下文规则。
const caseSelectValue = computed({
  get: () => (caseId.value ? caseId.value : null),
  set: (value) => {
    caseId.value = value || 0
  },
})

const currentContext = computed(() => normalizeTradeContext(tradeId.value, caseId.value))
const trade = computed(() => {
  const loaded = session.value.loaded
  return loaded && isSameTradeContext(loaded, currentContext.value) ? loaded.trade : null
})
const actionBusy = computed(() => session.value.actionBusy)
const tradeLoading = computed(() => session.value.loading)
const selectedCase = computed(() => caseOptions.value.find((c) => c.id === caseId.value) || null)
const caseContext = computed(() => selectedCase.value)
const isCaseClaimant = computed(
  () =>
    !!selectedCase.value &&
    !!adminId.value &&
    Number(selectedCase.value.claimed_by_id) === Number(adminId.value),
)
const directMismatch = computed(() => isDirectTradeMismatch(selectedCase.value, tradeId.value))
const caseHasDirectTrade = computed(
  () => selectedCase.value?.trade_id != null && Number(selectedCase.value.trade_id) === Number(tradeId.value),
)
const canQuery = computed(() => {
  const ctx = currentContext.value
  if (!ctx.tradeId || !ctx.caseId || !selectedCase.value || !isCaseClaimant.value) return false
  if (directMismatch.value) return false
  return caseCanContextTrade(selectedCase.value, ctx.tradeId)
})
const actionsEnabled = computed(() => canQuery.value && canUseLoadedTrade(session.value, currentContext.value))

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
    return `暂停于 ${fmt(t.confirm_wait_paused_at)}${remaining ? `，剩余 ${remaining}` : ''}（服务端记录）`
  }
  if (t.frozen) return '冻结期间不累计等待时间'
  if (t.confirm_wait_started_at) {
    return `自 ${fmt(t.confirm_wait_started_at)} 起算${remaining ? `，剩余 ${remaining}` : '，剩余以服务端为准'}`
  }
  return '无'
})

const typeLabels = {
  product_review: '商品审核',
  report: '举报事项',
  trade_dispute: '交易争议',
  abnormal_trade: '异常交易',
  account_ban: '账户处置',
}
const statusLabels = { pending: '待认领', processing: '处理中', disposed: '已处置' }
const caseStatusLabel = (s) => statusLabels[s] || s || '未知'
const caseOptionLabel = (c) => {
  const related = c.trade_id
    ? `交易#${c.trade_id}`
    : c.product_id
      ? `商品#${c.product_id}`
      : c.report_id
        ? `举报#${c.report_id}`
        : c.subject_user_id
          ? `账户#${c.subject_user_id}`
          : '无业务关联'
  return `#${c.id} ${typeLabels[c.case_type] || c.case_type} · ${c.title}（${related}，${caseStatusLabel(c.status)}）`
}
const serverDetail = (err) => (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败')

let casesRequestSeq = 0

function dropLoadedContext() {
  session.value = invalidateTradeSession(session.value)
}

function resetView() {
  dropLoadedContext()
  loadError.value = ''
  actionError.value = ''
}

async function loadCases() {
  casesError.value = ''
  if (!adminId.value) {
    casesError.value = '无法确认当前管理员身份，不能加载事项。'
    return
  }
  const seq = ++casesRequestSeq
  const requestedCaseId = caseId.value
  casesLoading.value = true
  try {
    const rows = await http.get('/admin/cases', { params: { status: 'all' } })
    if (seq !== casesRequestSeq) return
    let usable = ownedUsableCases(rows, adminId.value)
    if (requestedCaseId && !usable.some((c) => c.id === requestedCaseId)) {
      try {
        const detail = await http.get(`/admin/cases/${requestedCaseId}`)
        if (seq !== casesRequestSeq) return
        usable = ownedUsableCases([...rows, detail], adminId.value)
        if (!usable.some((c) => c.id === requestedCaseId)) {
          casesError.value =
            detail?.case_type === 'product_review'
              ? '商品审核事项不能作为私人交易上下文，请选择举报、争议或账户处置等相关事项。'
              : `指定事项 #${requestedCaseId} 不可作为本人交易上下文（未认领、非本人认领或不可用）。`
          if (Number(caseId.value) === Number(requestedCaseId)) {
            caseId.value = 0
            dropLoadedContext()
          }
        }
      } catch {
        if (seq !== casesRequestSeq) return
        casesError.value = `指定事项 #${requestedCaseId} 不可作为本人交易上下文（未认领、非本人认领或不可用）。`
        if (Number(caseId.value) === Number(requestedCaseId)) {
          caseId.value = 0
          dropLoadedContext()
        }
      }
    }
    if (seq !== casesRequestSeq) return
    caseOptions.value = usable
  } catch (err) {
    if (seq !== casesRequestSeq) return
    casesError.value = `事项列表加载失败：${serverDetail(err)}`
  } finally {
    if (seq === casesRequestSeq) casesLoading.value = false
  }
}

function contextProblem(ctx) {
  if (!ctx.tradeId) return '请输入交易 ID。'
  if (!ctx.caseId) return '请选择本人认领且与本交易相关的事项后再加载交易。'
  if (!selectedCase.value) return '所选事项不在本人可用事项中，请刷新事项后重新选择。'
  if (!isCaseClaimant.value) return '该事项非本人认领，不能读取私人交易详情。'
  if (directMismatch.value) return '所选事项已关联其他交易，不能用于本交易。'
  if (!caseCanContextTrade(selectedCase.value, ctx.tradeId)) {
    return '所选事项不能作为本交易的上下文，请选择本人认领的相关事项。'
  }
  return ''
}

function onTradeIdChange() {
  resetView()
  if (caseId.value && tradeId.value) load()
}

function onCaseChange() {
  resetView()
  if (selectedCase.value?.trade_id != null) {
    tradeId.value = Number(selectedCase.value.trade_id)
  }
  if (caseId.value && tradeId.value) load()
}

async function load(expectedContext = null) {
  loadError.value = ''
  actionError.value = ''
  const ctx = currentContext.value
  if (expectedContext && !isSameTradeContext(expectedContext, ctx)) return
  const problem = contextProblem(ctx)
  if (problem) {
    dropLoadedContext()
    loadError.value = problem
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
  if (!canQuery.value) return ElMessage.warning('当前事项不能用于本交易')
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
  if (!canQuery.value) return ElMessage.warning('当前事项不能用于本交易')
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
  const ctx = currentContext.value
  if (!canQuery.value) return ElMessage.warning('当前事项不能用于本交易')
  let value
  try {
    ({ value } = await ElMessageBox.prompt('解除冻结依据', '解除冻结', { inputType: 'textarea' }))
  } catch {
    return
  }
  if (!isSameTradeContext(ctx, currentContext.value)) {
    return ElMessage.warning('交易上下文已变更，请重新确认')
  }
  if (!value?.trim()) {
    actionError.value = '解除冻结须填写依据'
    return ElMessage.warning('解除冻结须填写依据')
  }
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
  const ctx = currentContext.value
  if (!canQuery.value) return ElMessage.warning('当前事项不能用于本交易')
  if (!adjustTarget.value || !adjustReason.value.trim()) {
    actionError.value = '请选择目标状态并填写调整依据'
    return ElMessage.warning('请选择目标状态并填写调整依据')
  }
  try {
    await ElMessageBox.confirm(
      '状态调整须留据并通知双方；不会生成双方确认。确认执行？',
      '确认调整',
      { type: 'warning' },
    )
  } catch {
    return
  }
  if (!isSameTradeContext(ctx, currentContext.value)) {
    return ElMessage.warning('交易上下文已变更，请重新确认')
  }
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

watch(
  () => [route.query.trade_id, route.query.case_id],
  async ([tid, cid]) => {
    resetView()
    tradeId.value = Number(tid) || null
    caseId.value = Number(cid) || 0
    await loadCases()
    if (caseId.value && !tradeId.value && selectedCase.value?.trade_id != null) {
      tradeId.value = Number(selectedCase.value.trade_id)
    }
    if (caseId.value && tradeId.value) await load()
  },
)

onMounted(async () => {
  adminId.value = (await ensureAdminUser())?.id || null
  await loadCases()
  if (caseId.value && !tradeId.value && selectedCase.value?.trade_id != null) {
    tradeId.value = Number(selectedCase.value.trade_id)
  }
  if (caseId.value && tradeId.value) await load()
})
</script>

<style scoped>
.trade-query-form {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 0 16px;
  align-items: flex-start;
}

.trade-query-form :deep(.el-form-item) {
  margin-right: 0;
  margin-bottom: 12px;
}

.trade-id-input {
  width: 150px;
}

.case-select {
  width: 420px;
  max-width: 100%;
}

.context-notices {
  margin-top: 2px;
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

.data-card .load-skeleton {
  border: 0;
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
  width: 230px;
}

.adjust-reason {
  width: 270px;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  align-items: flex-end;
}

.adjust-row {
  border-top: 1px dashed var(--line);
  padding-top: 12px;
}

.hint {
  color: var(--ink-faint);
  font-size: 12px;
  margin: 0 0 10px;
}

@media (max-width: 1280px) {
  .trade-history-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .case-select,
  .reason-input,
  .adjust-select,
  .adjust-reason {
    width: 100%;
  }

  .trade-query-form {
    flex-direction: column;
  }

  .trade-query-form :deep(.el-form-item) {
    width: 100%;
  }

  .trade-query-form :deep(.el-form-item__content) {
    flex-wrap: wrap;
    gap: 8px;
  }

  .action-row {
    flex-direction: column;
    align-items: stretch;
  }

  .action-row :deep(.el-form-item) {
    width: 100%;
  }
}
</style>
