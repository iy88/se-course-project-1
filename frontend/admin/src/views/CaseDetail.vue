<template>
  <div class="page">
    <div v-if="loading && !detail" class="load-skeleton">
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else-if="!detail" class="state-page">
      <span class="state-icon"><AppIcon name="alert" :size="26" /></span>
      <h2>事项详情未能打开</h2>
      <p>{{ loadError || '事项不存在或当前账户无权查看，请返回待处理池重新选择。' }}</p>
      <div class="state-actions">
        <el-button type="primary" @click="load()">重新加载</el-button>
        <el-button @click="$router.push('/cases')">返回待处理池</el-button>
      </div>
    </div>

    <template v-else>
      <header class="page-head">
        <div class="head-main">
          <button type="button" class="back-link" @click="$router.back()">
            <el-icon><AppIcon name="back" /></el-icon>
            返回
          </button>
          <p class="eyebrow">事项处理 · #{{ detail.id }}</p>
          <h1>{{ detail.title }}</h1>
          <div class="meta-row">
            <el-tag :type="statusTagType(detail.status)" effect="light">{{ statusLabel(detail.status) }}</el-tag>
            <el-tag type="info" effect="plain">{{ typeLabel(detail.case_type) }}</el-tag>
            <span>认领人 {{ detail.claimed_by_id ? `#${detail.claimed_by_id}` : '未认领' }}</span>
          </div>
        </div>
        <div class="page-head-actions">
          <el-button :loading="loading" @click="load()">
            <el-icon><AppIcon name="refresh" /></el-icon>
            刷新当前内容
          </el-button>
        </div>
      </header>

      <div class="notice-stack">
        <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon />
        <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon>
          <template #default>
            <el-button size="small" @click="load()">重新加载事项</el-button>
          </template>
        </el-alert>
        <el-alert
          v-if="!canAct"
          title="当前事项不在处理中，管理动作只读；如已处置请查看结论与沟通记录。"
          type="info"
          :closable="false"
          show-icon
        />
      </div>

      <div class="detail-grid">
        <div class="detail-main">
          <el-card>
            <template #header>
              <div class="card-head-row">
                <div>
                  <span class="card-title">事项信息</span>
                  <span class="card-sub">编号 #{{ detail.id }} · {{ typeLabel(detail.case_type) }}</span>
                </div>
              </div>
            </template>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="编号">{{ detail.id }}</el-descriptions-item>
              <el-descriptions-item label="类型">{{ detail.case_type }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
              <el-descriptions-item label="认领人">{{ detail.claimed_by_id || '未认领' }}</el-descriptions-item>
              <el-descriptions-item label="结论" :span="2">{{ detail.conclusion || '—' }}</el-descriptions-item>
              <el-descriptions-item label="结论理由" :span="2">
                {{ detail.conclusion_reason || '—' }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <el-card v-if="detail.product">
            <template #header>
              <div class="card-head-row">
                <div>
                  <span class="card-title">商品当次内容</span>
                  <span class="card-sub">审核依据提交结论时的最新保存内容；页面停留过久请刷新。</span>
                </div>
                <el-tag v-if="detail.product.display_restricted" type="danger" effect="light">
                  已停止公开访问
                </el-tag>
              </div>
            </template>

            <el-descriptions :column="2" border>
              <el-descriptions-item label="标题">{{ detail.product.title }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <span class="mono">{{ detail.product.status }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="公开展示">
                <el-tag v-if="detail.product.display_restricted" type="danger" effect="light">
                  已停止公开访问
                </el-tag>
                <span v-else>正常</span>
              </el-descriptions-item>
              <el-descriptions-item label="标价">
                ￥{{ (detail.product.price_cents / 100).toFixed(2) }}
              </el-descriptions-item>
              <el-descriptions-item label="标签" :span="2">
                {{ detail.product.tag_names?.join('、') || '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ detail.product.description }}</el-descriptions-item>
              <el-descriptions-item v-if="detail.product.display_restricted" label="展示限制原因" :span="2">
                {{ detail.product.display_restricted_reason || '处置停止公开访问' }}
              </el-descriptions-item>
            </el-descriptions>

            <div v-if="detail.tag_applications?.length" class="tag-applications">
              <span class="inline-label">标签申请：</span>
              <el-tag v-for="app in detail.tag_applications" :key="app.id" type="info" effect="plain">
                {{ app.requested_name }}（{{ app.status }}）
                <span v-if="app.decision_reason">：{{ app.decision_reason }}</span>
              </el-tag>
            </div>

            <div v-if="detail.product.display_restricted" class="restore-display">
              <template v-if="canRestoreDisplay">
                <strong>解除公开展示限制</strong>
                <p class="hint">
                  仅解除由本事项产生的公开展示限制；不解除交易冻结，也不把商品自动重新上架。其他账户封禁或其他处置限制不受影响。
                </p>
                <el-input
                  v-model="restoreReason"
                  type="textarea"
                  :rows="2"
                  placeholder="解除依据（必填，留据并通知卖方）"
                />
                <el-button
                  type="warning"
                  :loading="restoreLoading"
                  :disabled="!restoreReason.trim()"
                  class="restore-submit"
                  @click="restoreDisplay"
                >
                  提交解除展示限制
                </el-button>
              </template>
              <p v-else class="hint">
                当前展示限制不由本事项产生，或缺少原限制事项上下文；请返回对应相关事项处理，本页不提供任意解除入口。
              </p>
            </div>

            <div class="card-actions">
              <el-button size="small" @click="load()">刷新当前内容</el-button>
              <span class="hint">提交审核结论前会重新读取服务端内容；审核依据提交结论时的最新保存内容，页面停留过久请刷新。</span>
            </div>
          </el-card>

          <el-card v-if="detail.report">
            <template #header>
              <div class="card-head-row">
                <span class="card-title">举报内容</span>
              </div>
            </template>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="举报对象">
                <span class="mono">{{ detail.report.target_type }}#{{ detail.report.target_id }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="原因">{{ detail.report.reason }}</el-descriptions-item>
              <el-descriptions-item label="补充说明" :span="2">{{ detail.report.detail || '—' }}</el-descriptions-item>
            </el-descriptions>
            <pre v-if="detail.report_target" class="snapshot">{{ JSON.stringify(detail.report_target, null, 2) }}</pre>
          </el-card>

          <el-card v-if="detail.trade">
            <template #header>
              <div class="card-head-row">
                <div>
                  <span class="card-title">交易概要</span>
                  <span class="card-sub">交易 #{{ detail.trade.id }}</span>
                </div>
                <el-tag v-if="detail.trade.frozen" type="danger" effect="light">冻结中</el-tag>
              </div>
            </template>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="交易#">{{ detail.trade.id }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <span class="mono">{{ detail.trade.status }}</span>
                <el-tag v-if="detail.trade.frozen" type="danger" effect="light" class="inline-tag">冻结中</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="买方">
                {{ detail.trade.buyer?.display_name }}（#{{ detail.trade.buyer?.id }}）
              </el-descriptions-item>
              <el-descriptions-item label="卖方">
                {{ detail.trade.seller?.display_name }}（#{{ detail.trade.seller?.id }}）
              </el-descriptions-item>
              <el-descriptions-item label="当前有效确认" :span="2">{{ tradeConfirmText }}</el-descriptions-item>
              <el-descriptions-item label="等待计时" :span="2">{{ tradeWaitText }}</el-descriptions-item>
              <el-descriptions-item label="冻结原因" :span="2">
                {{ detail.trade.frozen ? (detail.trade.frozen_reason || '处置冻结') : '未冻结' }}
              </el-descriptions-item>
            </el-descriptions>

            <el-collapse class="trade-history">
              <el-collapse-item title="约定、完成确认与状态变更历史" name="trade-history">
                <div class="section-title"><h3>约定历史</h3></div>
                <div class="table-scroll table-compact">
                  <el-table :data="detail.trade.agreements || []" size="small" border>
                    <el-table-column prop="round_no" label="轮次" width="62" />
                    <el-table-column prop="status" label="状态" width="116" />
                    <el-table-column label="金额" width="94">
                      <template #default="{ row }">￥{{ (row.amount_cents / 100).toFixed(2) }}</template>
                    </el-table-column>
                    <el-table-column prop="delivery_location" label="地点" />
                    <el-table-column prop="payment_method" label="支付方式" width="104" />
                  </el-table>
                </div>

                <div class="section-title"><h3>完成确认记录</h3></div>
                <div class="table-scroll table-compact">
                  <el-table :data="detail.trade.confirmations || []" size="small" border>
                    <el-table-column prop="confirmer_id" label="确认人" width="84" />
                    <el-table-column label="当前有效" width="92">
                      <template #default="{ row }">{{ row.is_current ? '是' : '否' }}</template>
                    </el-table-column>
                    <el-table-column prop="confirmed_at" label="时间">
                      <template #default="{ row }">{{ fmt(row.confirmed_at) }}</template>
                    </el-table-column>
                  </el-table>
                </div>

                <div class="section-title"><h3>状态变更</h3></div>
                <div class="table-scroll table-compact">
                  <el-table :data="detail.trade.transitions || []" size="small" border max-height="260">
                    <el-table-column prop="from_status" label="前状态" width="162" />
                    <el-table-column prop="to_status" label="后状态" width="162" />
                    <el-table-column prop="actor_role" label="主体" width="74" />
                    <el-table-column prop="reason" label="原因/依据" show-overflow-tooltip />
                  </el-table>
                </div>
              </el-collapse-item>
            </el-collapse>

            <div v-if="detail.case_type !== 'product_review'" class="card-actions">
              <el-button
                size="small"
                @click="$router.push(`/trades?trade_id=${detail.trade.id}&case_id=${detail.id}`)"
              >
                进入交易处置
              </el-button>
            </div>
          </el-card>
        </div>

        <aside class="detail-side">
          <el-card class="side-card">
            <template #header>
              <div class="card-head-row">
                <div>
                  <span class="card-title">沟通与处理</span>
                  <span class="card-sub">{{ statusLabel(detail.status) }} · {{ typeLabel(detail.case_type) }}</span>
                </div>
                <el-tag :type="statusTagType(detail.status)" effect="plain">{{ statusLabel(detail.status) }}</el-tag>
              </div>
            </template>

            <template v-if="detail.case_type === 'product_review' && canAct">
              <el-form label-position="top">
                <el-form-item
                  v-for="app in pendingCaseTagApplications"
                  :key="app.id"
                  :label="`标签申请：${app.requested_name}`"
                >
                  <el-radio-group v-model="tagDecisions[app.id]">
                    <el-radio value="approve_new">批准为新标签</el-radio>
                    <el-radio value="map_alias">映射为已有分类别名</el-radio>
                    <el-radio value="reject">拒绝</el-radio>
                  </el-radio-group>
                  <el-input
                    v-if="tagDecisions[app.id] === 'reject'"
                    v-model="tagReasons[app.id]"
                    type="textarea"
                    :rows="2"
                    :maxlength="500"
                    show-word-limit
                    placeholder="说明拒绝该标签申请的原因"
                    aria-label="标签申请拒绝原因"
                  />
                  <el-select
                    v-if="tagDecisions[app.id] === 'map_alias'"
                    v-model="aliasTargets[app.id]"
                    placeholder="选择已有分类"
                    class="alias-select"
                  >
                    <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
                  </el-select>
                </el-form-item>
                <el-form-item label="审核结论">
                  <el-radio-group v-model="reviewForm.result">
                    <el-radio value="approved">通过</el-radio>
                    <el-radio value="rejected">不通过</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item v-if="reviewForm.result === 'rejected'" label="拒绝原因（不通过须记录理由）">
                  <el-input v-model="reviewForm.reason" type="textarea" :rows="2" />
                </el-form-item>
                <el-button
                  type="primary"
                  :disabled="!canAct || detail.product?.status !== 'pending_review'"
                  @click="submitReview"
                >
                  提交审核结论
                </el-button>
                <p v-if="!canAct" class="hint">仅事项认领管理员在处理中可提交审核结论</p>
                <p v-else-if="detail.product?.status !== 'pending_review'" class="hint">
                  商品当前状态为 {{ detail.product?.status }}，不再可审核；请刷新后按当前状态处理。
                </p>
              </el-form>
            </template>

            <template v-else-if="detail.case_type === 'report' && canAct">
              <el-form label-position="top">
                <el-form-item label="核查结论">
                  <el-radio-group v-model="reportForm.outcome">
                    <el-radio value="unfounded">无法认定 / 不予处理</el-radio>
                    <el-radio value="handled">认定违规并处置</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item label="结论理由">
                  <el-input v-model="reportForm.reason" type="textarea" :rows="2" />
                </el-form-item>
                <el-form-item label="匿名公开结果说明">
                  <el-input
                    v-model="reportForm.public_summary"
                    type="textarea"
                    :rows="2"
                    placeholder="将向所有登录用户匿名展示"
                  />
                </el-form-item>
                <template v-if="reportForm.outcome === 'handled'">
                  <el-form-item label="处置动作">
                    <el-checkbox v-model="reportForm.actions.remove_content">移除违规内容</el-checkbox>
                    <el-checkbox v-model="reportForm.actions.restrict_display">停止商品公开访问</el-checkbox>
                    <el-checkbox v-model="reportForm.actions.freeze_trade">冻结涉事交易</el-checkbox>
                    <el-checkbox v-model="reportForm.actions.ban_user">封禁违规账户</el-checkbox>
                  </el-form-item>
                  <el-form-item v-if="reportForm.actions.ban_user" label="封禁理由">
                    <el-input v-model="reportForm.actions.ban_reason" />
                  </el-form-item>
                </template>
                <el-button type="primary" :disabled="!canAct" @click="submitReportDecision">
                  提交核查结论
                </el-button>
                <p v-if="!canAct" class="hint">仅事项认领管理员在处理中可提交核查结论</p>
              </el-form>
            </template>

            <CaseConversation
              v-if="detail.readable_conversation_id"
              :key="`${detail.id}-${detail.readable_conversation_id}`"
              :case-id="detail.id"
              :conversation-id="detail.readable_conversation_id"
            />

            <el-divider content-position="left">沟通单</el-divider>
            <div class="message-list">
              <div v-for="m in detail.messages" :key="m.id" class="message-item" :class="m.role">
                <div class="message-meta">
                  {{ roleLabel(m.role) }} · {{ kindLabel(m.kind) }} · {{ fmt(m.created_at) }}
                </div>
                <div>{{ m.content }}</div>
              </div>
              <el-empty v-if="!detail.messages?.length" description="暂无沟通记录" />
            </div>

            <template v-if="canAct">
              <el-divider content-position="left">发起问询（需被举报/涉事用户说明时）</el-divider>
              <el-input v-model="inquiryText" type="textarea" :rows="2" placeholder="说明需要回应的范围" />
              <el-button class="message-submit" @click="sendInquiry">
                <el-icon><AppIcon name="send" /></el-icon>
                发送问询
              </el-button>

              <el-divider content-position="left">事项回复</el-divider>
              <el-input v-model="replyText" type="textarea" :rows="2" placeholder="在沟通单回复说明/结论" />
              <el-button class="message-submit" @click="sendReply">
                <el-icon><AppIcon name="send" /></el-icon>
                发送回复
              </el-button>
            </template>
          </el-card>
        </aside>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import { ensureAdminUser } from '../api/session'
import AppIcon from '../components/AppIcon.vue'
import CaseConversation from '../components/CaseConversation.vue'

const route = useRoute()
const detail = ref(null)
const adminId = ref(null)
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const categories = ref([])
const tagDecisions = reactive({})
const tagReasons = reactive({})
const aliasTargets = reactive({})
const reviewForm = reactive({ result: 'approved', reason: '' })
const reportForm = reactive({
  outcome: 'unfounded',
  reason: '',
  public_summary: '',
  actions: { remove_content: false, restrict_display: false, freeze_trade: false, ban_user: false, ban_reason: '' },
})
const inquiryText = ref('')
const replyText = ref('')
const restoreReason = ref('')
const restoreLoading = ref(false)

const typeLabels = {
  product_review: '商品审核',
  report: '举报事项',
  trade_dispute: '交易争议',
  abnormal_trade: '异常交易',
  account_ban: '账户封禁',
}
const statusLabels = { pending: '待认领', processing: '处理中', disposed: '已处置' }
const typeLabel = (t) => typeLabels[t] || t
const statusLabel = (s) => statusLabels[s] || s
const statusTagType = (s) => {
  if (s === 'pending') return 'warning'
  if (s === 'processing') return 'primary'
  if (s === 'disposed') return 'success'
  return 'info'
}

const canAct = computed(() => detail.value?.status === 'processing')
const pendingCaseTagApplications = computed(() =>
  (detail.value?.tag_applications || []).filter((app) => app.status === 'pending'),
)
const canRestoreDisplay = computed(
  () =>
    !!detail.value?.product?.display_restricted &&
    Number(detail.value.product.display_restricted_case_id) === Number(detail.value.id) &&
    !!adminId.value &&
    Number(detail.value.claimed_by_id) === Number(adminId.value),
)
const tradeConfirmText = computed(() => {
  const rows = (detail.value?.trade?.confirmations || []).filter((c) => c.is_current)
  if (!rows.length) return '无当前有效声明'
  return rows.map((c) => `#${c.confirmer_id} ${fmt(c.confirmed_at)}`).join('；')
})
const tradeWaitText = computed(() => {
  const t = detail.value?.trade
  if (!t) return '无'
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

const serverDetail = (err) => {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (!item || typeof item !== 'object') return ''
        const message = item.msg || item.message
        if (typeof message !== 'string' || !message.trim()) return ''
        const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
        return field ? `${field}：${message}` : message
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
    return '请求失败'
  }
  if (detail && typeof detail === 'object') {
    const message = detail.msg || detail.message
    if (typeof message === 'string' && message.trim()) return message
  }
  return '请求失败'
}

let loadVersion = 0
async function load(keepActionError = false) {
  const version = ++loadVersion
  const caseId = route.params.id
  loading.value = true
  loadError.value = ''
  detail.value = null
  if (!keepActionError) actionError.value = ''
  try {
    const data = await http.get(`/admin/cases/${caseId}`)
    if (version !== loadVersion) return
    detail.value = data
  } catch (err) {
    if (version !== loadVersion) return
    loadError.value = `事项详情加载失败：${serverDetail(err)}。仅该事项认领管理员可查看非公开内容；请先在共享池认领。`
    return
  } finally {
    if (version === loadVersion) loading.value = false
  }
  if (version !== loadVersion || !detail.value) return
  if (detail.value.case_type === 'product_review') {
    categories.value = await http.get('/categories').catch(() => [])
  }
}

async function submitReview() {
  if (!canAct.value) return ElMessage.warning('仅认领管理员在处理中可提交审核结论')
  if (reviewForm.result === 'rejected' && !reviewForm.reason.trim()) {
    return ElMessage.warning('不通过时须填写拒绝原因')
  }
  actionError.value = ''
  await load(true)
  if (loadError.value || !canAct.value) return
  if (detail.value.product?.status !== 'pending_review') {
    actionError.value = `商品当前状态为 ${detail.value.product?.status || '未知'}，不再可审核；未提交旧结论。`
    return
  }
  if (reviewForm.result === 'approved' && pendingCaseTagApplications.value.some((app) => !tagDecisions[app.id])) {
    return ElMessage.warning('请先处理每个待审核的标签申请')
  }
  if (reviewForm.result === 'approved' && pendingCaseTagApplications.value.some(
    (app) => tagDecisions[app.id] === 'reject' && !String(tagReasons[app.id] || '').trim(),
  )) {
    return ElMessage.warning('拒绝标签申请时须说明原因')
  }
  const tag_decisions = pendingCaseTagApplications.value
    .filter((app) => tagDecisions[app.id])
    .map((app) => ({
      application_id: app.id,
      decision: tagDecisions[app.id],
      reason: tagDecisions[app.id] === 'reject' ? String(tagReasons[app.id] || '').trim() || null : null,
      category_id: tagDecisions[app.id] === 'map_alias' ? aliasTargets[app.id] : null,
    }))
  try {
    await http.post(`/admin/products/cases/${detail.value.id}/review`, {
      result: reviewForm.result,
      reason: reviewForm.reason || null,
      tag_decisions,
    })
    ElMessage.success('审核结论已提交并通知发布者')
    await load()
  } catch (err) {
    await load(true)
    actionError.value = `审核提交失败：${serverDetail(err)}；未显示成功，已重新读取当前事项与商品状态。`
  }
}

async function submitReportDecision() {
  if (!canAct.value) return ElMessage.warning('仅认领管理员在处理中可提交核查结论')
  if (!reportForm.reason.trim()) return ElMessage.warning('须填写结论理由')
  try {
    await ElMessageBox.confirm('提交后举报事项将结案归档，不再接受补充。确认提交？', '确认处置', { type: 'warning' })
  } catch {
    return
  }
  actionError.value = ''
  await load(true)
  if (loadError.value || !canAct.value) return
  try {
    await http.post(`/admin/reports/cases/${detail.value.id}/decision`, {
      outcome: reportForm.outcome,
      reason: reportForm.reason,
      public_summary: reportForm.public_summary || null,
      actions: {
        ...reportForm.actions,
        ban_reason: reportForm.actions.ban_reason || null,
      },
    })
    ElMessage.success('举报结论已提交')
    await load()
  } catch (err) {
    await load(true)
    actionError.value = `核查结论提交失败：${serverDetail(err)}；未显示成功，已重新读取当前事项状态。`
  }
}

async function sendInquiry() {
  if (!canAct.value) return ElMessage.warning('仅认领管理员在处理中可发起问询')
  if (!inquiryText.value.trim()) return
  actionError.value = ''
  try {
    await http.post(`/admin/cases/${detail.value.id}/inquiry`, { content: inquiryText.value })
    ElMessage.success('问询已发送')
    inquiryText.value = ''
    await load()
  } catch (err) {
    actionError.value = `问询发送失败：${serverDetail(err)}`
  }
}

async function sendReply() {
  if (!canAct.value) return ElMessage.warning('仅认领管理员在处理中可回复')
  if (!replyText.value.trim()) return
  actionError.value = ''
  try {
    await http.post(`/admin/cases/${detail.value.id}/messages`, { content: replyText.value })
    replyText.value = ''
    await load()
  } catch (err) {
    actionError.value = `回复发送失败：${serverDetail(err)}`
  }
}

async function restoreDisplay() {
  if (!canRestoreDisplay.value) {
    return ElMessage.warning('仅原展示限制事项的认领管理员可提交解除')
  }
  if (!restoreReason.value.trim()) {
    return ElMessage.warning('请填写解除展示限制的依据')
  }
  restoreLoading.value = true
  actionError.value = ''
  try {
    const data = await http.post(`/admin/products/${detail.value.product.id}/restore-display`, {
      case_id: detail.value.id,
      reason: restoreReason.value.trim(),
    })
    ElMessage.success(data?.detail || '公开展示限制已解除')
    restoreReason.value = ''
    await load()
  } catch (err) {
    // 失败时保留当前事项、商品与已填依据，由管理员处理后重试；不显示成功。
    actionError.value = `解除展示限制失败：${serverDetail(err)}；未显示成功，已保留当前输入。`
  } finally {
    restoreLoading.value = false
  }
}

const roleLabel = (r) => {
  if (r === 'user' && ['trade_dispute', 'abnormal_trade'].includes(detail.value?.case_type)) {
    return '交易参与方'
  }
  return ({ admin: '管理员', user: '用户', system: '系统' }[r] || r)
}
const kindLabel = (k) =>
  ({ inquiry: '问询', statement: '说明', appeal: '申辩', reply: '回复', notice: '留痕' }[k] || k)
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

onBeforeUnmount(() => ++loadVersion)
onMounted(async () => {
  adminId.value = (await ensureAdminUser())?.id || null
  await load()
})
watch(() => route.params.id, () => {
  detail.value = null
  load()
})
</script>

<style scoped>
.head-main {
  min-width: 0;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  background: none;
  color: var(--ink-soft);
  font: inherit;
  font-size: 12.5px;
  padding: 2px 3px;
  margin-bottom: 8px;
  border-radius: 5px;
  cursor: pointer;
}

.back-link:hover {
  color: var(--brand);
}

.back-link:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 8px 14px;
  flex-wrap: wrap;
  color: var(--ink-faint);
  font-size: 12px;
  margin-top: 8px;
}

.state-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.32fr) minmax(340px, 0.92fr);
  gap: 16px;
  align-items: start;
}

.detail-main,
.detail-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.detail-side {
  position: sticky;
  top: 80px;
}

.tag-applications {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.inline-label {
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 600;
}

.restore-display {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid #eeddba;
  border-radius: 10px;
  background: var(--warn-soft);
}

.restore-display strong {
  font-size: 13px;
  color: #75500c;
}

.restore-display .hint {
  margin: 6px 0 8px;
  color: #75500c;
}

.restore-submit {
  margin-top: 10px;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.card-actions .hint {
  flex: 1;
  min-width: 220px;
}

.snapshot {
  background: #f5f8f5;
  border: 1px solid var(--line);
  padding: 12px;
  border-radius: 8px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
  max-height: 220px;
  overflow: auto;
  margin: 12px 0 0;
  color: var(--ink-soft);
}

.trade-history {
  margin-top: 14px;
}

.inline-tag {
  margin-left: 6px;
}

.alias-select {
  width: 100%;
  margin-top: 8px;
}

.hint {
  color: var(--ink-faint);
  font-size: 12px;
  margin-top: 8px;
}

.message-submit {
  margin-top: 8px;
}

.side-card :deep(.el-divider--horizontal) {
  margin: 18px 0 12px;
}

.side-card :deep(.el-form-item:last-of-type) {
  margin-bottom: 12px;
}

@media (max-width: 1200px) {
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-side {
    position: static;
  }
}

@media (max-width: 900px) {
  .state-actions {
    flex-direction: column;
    width: 100%;
  }
}
</style>
