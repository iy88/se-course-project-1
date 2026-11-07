<template>
  <div class="page">
    <div v-if="loading && !detail" class="load-skeleton">
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else-if="!detail" class="state-page">
      <span class="state-icon"><AppIcon name="alert" :size="26" /></span>
      <h2>事项详情未能打开</h2>
      <p>{{ loadError || '事项不存在或当前账户无权查看，请返回列表重新选择。' }}</p>
      <div class="state-actions">
        <el-button type="primary" @click="load()">重新加载</el-button>
        <el-button @click="$router.push($route.query.from === 'my-cases' ? '/my-cases' : '/cases')">
          {{ $route.query.from === 'my-cases' ? '返回我的审核' : '返回待处理池' }}
        </el-button>
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
          <div class="detail-title-row">
            <h1>{{ detail.title }}</h1>
            <el-button :loading="loading" title="刷新当前内容" aria-label="刷新当前内容" @click="load()">
              <el-icon><AppIcon name="refresh" /></el-icon><span>刷新</span>
            </el-button>
          </div>
          <div class="meta-row">
            <el-tag :type="statusTagType(detail.status)" effect="light">{{ statusLabel(detail.status) }}</el-tag>
            <el-tag type="info" effect="plain">{{ typeLabel(detail.case_type) }}</el-tag>
            <span>认领人 {{ detail.claimed_by_id ? `#${detail.claimed_by_id}` : '未认领' }}</span>
          </div>
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
              <el-descriptions-item v-if="detail.basis" label="处置依据" :span="2">
                {{ detail.basis }}
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

            <div v-if="detail.product.image_urls?.length" class="media-block">
              <span class="inline-label">商品图片（{{ detail.product.image_urls.length }}）</span>
              <div class="media-grid">
                <el-image
                  v-for="(url, index) in detail.product.image_urls"
                  :key="url"
                  :src="url"
                  :preview-src-list="detail.product.image_urls"
                  :initial-index="index"
                  preview-teleported
                  fit="cover"
                  class="media-grid__item"
                />
              </div>
            </div>

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
                <TextInput :limit="500"
                  v-model="restoreReason"
                  type="textarea"
                  placeholder="解除依据（必填，留据并通知卖方）"
                 :autosize="{ minRows: 3, maxRows: 8 }"/>
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

            <div v-if="detail.report.evidence_urls?.length" class="media-block">
              <span class="inline-label">举报证据（{{ detail.report.evidence_urls.length }}）</span>
              <div class="media-grid">
                <el-image
                  v-for="(url, index) in detail.report.evidence_urls"
                  :key="url"
                  :src="url"
                  :preview-src-list="detail.report.evidence_urls"
                  :initial-index="index"
                  preview-teleported
                  fit="cover"
                  class="media-grid__item"
                />
              </div>
            </div>

            <div v-if="detail.report.supplements?.length" class="supplements">
              <h4 class="target-snapshot__title">后续补充</h4>
              <div v-for="supplement in detail.report.supplements" :key="supplement.id" class="supplement">
                <p class="target-snapshot__meta">{{ fmt(supplement.created_at) }}</p>
                <p class="supplement__content">{{ supplement.content || '—' }}</p>
                <div v-if="supplement.evidence_urls?.length" class="media-block">
                  <span class="inline-label">补充证据（{{ supplement.evidence_urls.length }}）</span>
                  <div class="media-grid">
                    <el-image
                      v-for="(url, index) in supplement.evidence_urls"
                      :key="url"
                      :src="url"
                      :preview-src-list="supplement.evidence_urls"
                      :initial-index="index"
                      preview-teleported
                      fit="cover"
                      class="media-grid__item"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div v-if="detail.report_target" class="target-snapshot">
              <h4 class="target-snapshot__title">被举报内容</h4>
              <p v-if="detail.report_target.missing" class="hint">举报对象已不存在或当前不可见。</p>
              <template v-else-if="detail.report_target.type === 'product'">
                <el-descriptions :column="2" border>
                  <el-descriptions-item label="标题">{{ detail.report_target.title }}</el-descriptions-item>
                  <el-descriptions-item label="状态"><span class="mono">{{ detail.report_target.status }}</span></el-descriptions-item>
                  <el-descriptions-item label="标价">￥{{ (detail.report_target.price_cents / 100).toFixed(2) }}</el-descriptions-item>
                  <el-descriptions-item label="卖方">#{{ detail.report_target.seller_id }}</el-descriptions-item>
                  <el-descriptions-item label="描述" :span="2">{{ detail.report_target.description }}</el-descriptions-item>
                </el-descriptions>
                <div v-if="detail.report_target.image_urls?.length" class="media-block">
                  <div class="media-grid">
                    <el-image
                      v-for="(url, index) in detail.report_target.image_urls"
                      :key="url"
                      :src="url"
                      :preview-src-list="detail.report_target.image_urls"
                      :initial-index="index"
                      preview-teleported
                      fit="cover"
                      class="media-grid__item"
                    />
                  </div>
                </div>
              </template>
              <template v-else-if="detail.report_target.type === 'user'">
                <el-descriptions :column="2" border>
                  <el-descriptions-item label="账户">#{{ detail.report_target.id }}</el-descriptions-item>
                  <el-descriptions-item label="名称">{{ detail.report_target.display_name }}</el-descriptions-item>
                  <el-descriptions-item label="状态">{{ detail.report_target.status }}</el-descriptions-item>
                </el-descriptions>
                <div v-if="detail.report_target.avatar_url" class="media-block">
                  <div class="media-grid">
                    <el-image
                      :src="detail.report_target.avatar_url"
                      :preview-src-list="[detail.report_target.avatar_url]"
                      preview-teleported
                      fit="cover"
                      class="media-grid__item media-grid__item--avatar"
                    />
                  </div>
                </div>
              </template>
              <template v-else>
                <p class="target-snapshot__content">{{ detail.report_target.content || '—' }}</p>
                <p v-if="detail.report_target.rating" class="target-snapshot__meta">评分：{{ detail.report_target.rating }} / 5</p>
              </template>
            </div>
          </el-card>

          <TradeCasePanel
            v-if="showTradePanel"
            :key="`${detail.id}-${detailRevision}`"
            :case-id="detail.id"
            :trade-id="detail.trade?.id || null"
          />
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

            <template v-if="detail.case_type === 'avatar_review'">
              <el-image v-if="detail.avatar?.url" :src="detail.avatar.url" :preview-src-list="[detail.avatar.url]" preview-teleported style="width:160px;height:160px;border-radius:16px" fit="cover" />
              <el-form v-if="canAct" label-position="top">
                <el-form-item label="审核原因"><TextInput :limit="500" v-model="avatarReason" type="textarea" placeholder="拒绝时填写原因"  :autosize="{ minRows: 3, maxRows: 8 }" /></el-form-item>
                <el-button type="primary" :disabled="avatarBusy" @click="submitAvatarDecision(true)">通过</el-button>
                <el-button type="danger" :disabled="avatarBusy" @click="submitAvatarDecision(false)">拒绝</el-button>
              </el-form>
            </template>
            <template v-else-if="detail.case_type === 'product_review' && canAct">
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
                  <TextInput :limit="500"
                    v-if="tagDecisions[app.id] === 'reject'"
                    v-model="tagReasons[app.id]"
                    type="textarea"
                    placeholder="说明拒绝该标签申请的原因"
                    aria-label="标签申请拒绝原因"
                   :autosize="{ minRows: 3, maxRows: 8 }" />
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
                  <TextInput :limit="500" v-model="reviewForm.reason" type="textarea"  :autosize="{ minRows: 3, maxRows: 8 }" />
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
                  <TextInput :limit="500" v-model="reportForm.reason" type="textarea"  :autosize="{ minRows: 3, maxRows: 8 }" />
                </el-form-item>
                <el-form-item v-if="reportForm.outcome === 'handled'" label="匿名公开结果说明">
                  <TextInput :limit="500"
                    v-model="reportForm.public_summary"
                    type="textarea"
                    placeholder="将展示在被处置内容的原入口（BR-25）"
                   :autosize="{ minRows: 3, maxRows: 8 }" />
                </el-form-item>
                <template v-if="reportForm.outcome === 'handled'">
                  <el-form-item label="处置动作">
                    <el-checkbox v-model="reportForm.actions.remove_content">移除违规内容</el-checkbox>
                    <el-checkbox v-model="reportForm.actions.restrict_display">停止商品公开访问</el-checkbox>
                    <el-checkbox v-model="reportForm.actions.freeze_trade">冻结涉事交易</el-checkbox>
                    <el-checkbox v-model="reportForm.actions.ban_user">封禁违规账户</el-checkbox>
                  </el-form-item>
                  <el-form-item v-if="reportForm.actions.ban_user" label="封禁理由">
                    <TextInput :limit="500" v-model="reportForm.actions.ban_reason"  />
                  </el-form-item>
                </template>
                <el-button type="danger" :disabled="!canAct" @click="submitReportDecision">
                  提交结论并办结
                </el-button>
                <p class="hint">提交后事项办结归档；认定违规时，匿名结果显示在被处置内容的原入口</p>
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
              <div class="case-composer">
              <h3>发起问询</h3>
              <p>要求参与方在事项内作出说明，将推送站内通知</p>
              <div v-if="detail.participants?.length" class="participant-row">
                <span class="participant-label">问询对象</span>
                <el-tag v-for="u in detail.participants" :key="u.id" effect="plain" size="small">
                  {{ u.display_name || '用户' }}（#{{ u.id }}）
                </el-tag>
              </div>
              <TextInput :limit="2000" v-model="inquiryText" type="textarea" placeholder="说明需要回应的范围"  :autosize="{ minRows: 3, maxRows: 8 }" />
              <el-button class="message-submit" @click="sendInquiry">
                <el-icon><AppIcon name="send" /></el-icon>
                发送问询
              </el-button>

              </div>
              <div class="case-composer">
              <h3>事项回复</h3>
              <p>在沟通单记录处理说明或结论；将推送站内通知，参与方从通知进入查看</p>
              <div v-if="detail.participants?.length" class="participant-row">
                <span class="participant-label">可见对象</span>
                <el-tag v-for="u in detail.participants" :key="u.id" effect="plain" size="small">
                  {{ u.display_name || '用户' }}（#{{ u.id }}）
                </el-tag>
              </div>
              <TextInput :limit="2000" v-model="replyText" type="textarea" placeholder="在沟通单回复说明/结论"  :autosize="{ minRows: 3, maxRows: 8 }" />
              <el-button class="message-submit" @click="sendReply">
                <el-icon><AppIcon name="send" /></el-icon>
                发送回复
              </el-button>
              </div>
              <div v-if="showDisposeForm" class="case-composer dispose-composer">
              <h3>办结事项</h3>
              <p>记录处置结论后事项归档；已办结事项仍可作为后续交易处置的依据</p>
              <TextInput :limit="200"
                v-model="disposeForm.conclusion"
                placeholder="处置结论（必填，如：异常已处理，交易维持完成）"
               />
              <TextInput :limit="500"
                v-model="disposeForm.reason"
                type="textarea"
                placeholder="结论理由（留据，参与方查看事项时可见）"
                :autosize="{ minRows: 2, maxRows: 6 }"
               />
              <TextInput :limit="500"
                v-model="disposeForm.basis"
                type="textarea"
                placeholder="处置依据（可选，如调整记录、沟通情况）"
                :autosize="{ minRows: 2, maxRows: 6 }"
               />
              <el-button class="message-submit" type="danger" :disabled="actionBusy" @click="submitDispose">
                办结事项
              </el-button>
              </div>
            </template>
          </el-card>
        </aside>
      </div>
    </template>
  </div>
</template>

<script setup>
import TextInput from '../components/TextInput.vue'
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'
import { fmtTime as fmt } from '../api/time'
import { ensureAdminUser } from '../api/session'
import AppIcon from '../components/AppIcon.vue'
import TradeCasePanel from '../components/TradeCasePanel.vue'
import CaseConversation from '../components/CaseConversation.vue'

const route = useRoute()
const detail = ref(null)
const detailRevision = ref(0)
const disposeForm = reactive({ conclusion: '', reason: '', basis: '' })
const showDisposeForm = computed(() =>
  ['trade_dispute', 'abnormal_trade', 'account_ban'].includes(detail.value?.case_type),
)
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
  avatar_review: '头像审核',
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
const showTradePanel = computed(() =>
  ['trade_dispute', 'abnormal_trade', 'report', 'account_ban'].includes(detail.value?.case_type),
)

async function submitDispose() {
  if (!disposeForm.conclusion.trim()) {
    return ElMessage.warning('请填写处置结论')
  }
  try {
    await ElMessageBox.confirm('办结后事项归档，不再接收问询与回复；确认提交？', '办结事项', {
      type: 'warning',
      confirmButtonText: '办结',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  actionError.value = ''
  try {
    await http.post(`/admin/cases/${detail.value.id}/dispose`, {
      conclusion: disposeForm.conclusion.trim(),
      reason: disposeForm.reason.trim() || null,
      basis: disposeForm.basis.trim() || null,
    })
    ElMessage.success('事项已办结')
    disposeForm.conclusion = ''
    disposeForm.reason = ''
    disposeForm.basis = ''
    await load(true)
  } catch (err) {
    actionError.value = `办结失败：${serverDetail(err)}`
  }
}

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
    detailRevision.value += 1
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
      public_summary: reportForm.outcome === 'handled' ? reportForm.public_summary || null : null,
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
    // On failure keep the current case, product, and entered basis so the admin can retry; do not show success.
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
const avatarReason = ref('')
const avatarBusy = ref(false)
async function submitAvatarDecision(approved) {
  if (!approved && !avatarReason.value.trim()) return ElMessage.warning('请填写拒绝原因')
  avatarBusy.value = true
  try {
    await http.post(`/admin/cases/${detail.value.id}/avatar-decision`, { key: detail.value.avatar.key, approved, reason: avatarReason.value })
    ElMessage.success('头像审核完成')
    await load()
  } catch {} finally { avatarBusy.value = false }
}
</script>

<style scoped>
.head-main { width: 100%; min-width: 0; }
.detail-title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.detail-title-row h1 { min-width: 0; overflow-wrap: anywhere; }
.detail-title-row .el-button { flex-shrink: 0; }

.case-composer { margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--line); }
.case-composer h3 { font-size: 14px; margin-bottom: 5px; }
.case-composer p { margin: 0 0 12px; font-size: 12px; line-height: 1.6; color: var(--ink-faint); }

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
  /* The scroll container is .main (the top bar is outside it), so top resolves against it; internal scrolling in the right column keeps the bottom actions reachable. */
  top: 16px;
  max-height: calc(100vh - 64px - 16px - 34px);
  overflow-y: auto;
  padding-right: 2px;
  /* Visible thin scrollbar hinting that the right column can scroll. */
  scrollbar-width: thin;
  scrollbar-color: #b7c6be transparent;
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

.media-block {
  margin-top: 14px;
}

.media-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}

.media-grid__item {
  width: 112px;
  height: 112px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: #f5f8f5;
  cursor: zoom-in;
}

.media-grid__item--avatar {
  border-radius: 50%;
}

.target-snapshot {
  margin-top: 16px;
}

.supplements { margin-top: 16px; }
.supplement { padding: 12px 0; border-top: 1px solid var(--line); }
.supplement__content { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }

.target-snapshot__title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.target-snapshot__content {
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f5f8f5;
  color: var(--ink-soft);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.target-snapshot__meta {
  margin: 8px 0 0;
  color: var(--ink-faint);
  font-size: 12.5px;
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
.participant-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 6px 0 10px;
}
.participant-label {
  color: var(--ink-meta);
  font-size: 12.5px;
}
.dispose-composer {
  border-top: 1px solid var(--line);
  padding-top: 14px;
  margin-top: 14px;
}
.dispose-composer .el-input,
.dispose-composer .el-textarea {
  margin-bottom: 10px;
}
</style>
