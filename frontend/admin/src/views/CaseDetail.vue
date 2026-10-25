<template>
  <div v-if="detail">
    <el-page-header :content="detail.title" @back="$router.back()" style="margin-bottom: 16px" />

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card header="事项信息">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="编号">{{ detail.id }}</el-descriptions-item>
            <el-descriptions-item label="类型">{{ detail.case_type }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
            <el-descriptions-item label="认领人">{{ detail.claimed_by_id || '未认领' }}</el-descriptions-item>
            <el-descriptions-item label="结论" :span="2">{{ detail.conclusion || '—' }}</el-descriptions-item>
            <el-descriptions-item label="结论理由" :span="2">{{ detail.conclusion_reason || '—' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card v-if="detail.product" header="商品当次内容" style="margin-top: 16px">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="标题">{{ detail.product.title }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ detail.product.status }}</el-descriptions-item>
            <el-descriptions-item label="标价">￥{{ (detail.product.price_cents / 100).toFixed(2) }}</el-descriptions-item>
            <el-descriptions-item label="标签">{{ detail.product.tag_names.join('、') || '—' }}</el-descriptions-item>
            <el-descriptions-item label="描述" :span="2">{{ detail.product.description }}</el-descriptions-item>
          </el-descriptions>
          <div v-if="detail.tag_applications?.length" style="margin-top: 12px">
            <strong>标签申请：</strong>
            <el-tag v-for="app in detail.tag_applications" :key="app.id" style="margin-right: 6px">
              {{ app.requested_name }}（{{ app.status }}）
            </el-tag>
          </div>
        </el-card>

        <el-card v-if="detail.report" header="举报内容" style="margin-top: 16px">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="举报对象">{{ detail.report.target_type }}#{{ detail.report.target_id }}</el-descriptions-item>
            <el-descriptions-item label="原因">{{ detail.report.reason }}</el-descriptions-item>
            <el-descriptions-item label="补充说明" :span="2">{{ detail.report.detail || '—' }}</el-descriptions-item>
          </el-descriptions>
          <pre v-if="detail.report_target" class="snapshot">{{ JSON.stringify(detail.report_target, null, 2) }}</pre>
        </el-card>

        <el-card v-if="detail.trade" header="交易概要" style="margin-top: 16px">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="交易#">{{ detail.trade.id }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              {{ detail.trade.status }}
              <el-tag v-if="detail.trade.frozen" type="danger" style="margin-left: 6px">冻结中</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="买方">{{ detail.trade.buyer?.display_name }}（#{{ detail.trade.buyer?.id }}）</el-descriptions-item>
            <el-descriptions-item label="卖方">{{ detail.trade.seller?.display_name }}（#{{ detail.trade.seller?.id }}）</el-descriptions-item>
          </el-descriptions>
          <el-button style="margin-top: 10px" size="small" @click="$router.push(`/trades?trade_id=${detail.trade.id}`)">
            进入交易处置
          </el-button>
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card header="沟通与处理">
          <!-- 商品审核 -->
          <template v-if="detail.case_type === 'product_review' && detail.status !== 'disposed'">
            <el-form label-position="top">
              <el-form-item v-for="app in detail.tag_applications || []" :key="app.id" :label="`标签申请：${app.requested_name}`">
                <el-radio-group v-model="tagDecisions[app.id]">
                  <el-radio value="approve_new">批准为新标签</el-radio>
                  <el-radio value="map_alias">映射为已有分类别名</el-radio>
                  <el-radio value="reject">拒绝</el-radio>
                </el-radio-group>
                <el-select v-if="tagDecisions[app.id] === 'map_alias'" v-model="aliasTargets[app.id]" placeholder="选择已有分类" style="margin-top: 6px; width: 100%">
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
              <el-button type="primary" :disabled="detail.status === 'pending'" @click="submitReview">
                提交审核结论
              </el-button>
              <p v-if="detail.status === 'pending'" class="hint">请先在待处理池认领本事项</p>
            </el-form>
          </template>

          <!-- 举报处置 -->
          <template v-else-if="detail.case_type === 'report' && detail.status !== 'disposed'">
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
                <el-input v-model="reportForm.public_summary" type="textarea" :rows="2" placeholder="将向所有登录用户匿名展示" />
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
              <el-button type="primary" :disabled="detail.status === 'pending'" @click="submitReportDecision">
                提交核查结论
              </el-button>
            </el-form>
          </template>

          <el-divider>沟通单</el-divider>
          <div class="messages">
            <div v-for="m in detail.messages" :key="m.id" class="message" :class="m.role">
              <div class="meta">{{ roleLabel(m.role) }} · {{ kindLabel(m.kind) }} · {{ fmt(m.created_at) }}</div>
              <div>{{ m.content }}</div>
            </div>
            <el-empty v-if="!detail.messages?.length" description="暂无沟通记录" />
          </div>

          <template v-if="detail.status !== 'pending'">
            <el-divider content-position="left">发起问询（需被举报/涉事用户说明时）</el-divider>
            <el-input v-model="inquiryText" type="textarea" :rows="2" placeholder="说明需要回应的范围" />
            <el-button style="margin-top: 8px" @click="sendInquiry">发送问询</el-button>
            <el-divider content-position="left">事项回复</el-divider>
            <el-input v-model="replyText" type="textarea" :rows="2" placeholder="在沟通单回复说明/结论" />
            <el-button style="margin-top: 8px" @click="sendReply">发送回复</el-button>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'

const route = useRoute()
const detail = ref(null)
const categories = ref([])
const tagDecisions = reactive({})
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

async function load() {
  detail.value = await http.get(`/admin/cases/${route.params.id}`)
  if (detail.value.case_type === 'product_review') {
    categories.value = await http.get('/categories')
  }
}

async function submitReview() {
  if (reviewForm.result === 'rejected' && !reviewForm.reason.trim()) {
    return ElMessage.warning('不通过时须填写拒绝原因')
  }
  const tag_decisions = (detail.value.tag_applications || [])
    .filter((app) => tagDecisions[app.id])
    .map((app) => ({
      application_id: app.id,
      decision: tagDecisions[app.id],
      category_id: tagDecisions[app.id] === 'map_alias' ? aliasTargets[app.id] : null,
    }))
  await http.post(`/admin/products/cases/${detail.value.id}/review`, {
    result: reviewForm.result,
    reason: reviewForm.reason || null,
    tag_decisions,
  })
  ElMessage.success('审核结论已提交并通知发布者')
  load()
}

async function submitReportDecision() {
  if (!reportForm.reason.trim()) return ElMessage.warning('须填写结论理由')
  await ElMessageBox.confirm('提交后举报事项将结案归档，不再接受补充。确认提交？', '确认处置', { type: 'warning' })
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
  load()
}

async function sendInquiry() {
  if (!inquiryText.value.trim()) return
  await http.post(`/admin/cases/${detail.value.id}/inquiry`, { content: inquiryText.value })
  ElMessage.success('问询已发送')
  inquiryText.value = ''
  load()
}

async function sendReply() {
  if (!replyText.value.trim()) return
  await http.post(`/admin/cases/${detail.value.id}/messages`, { content: replyText.value })
  replyText.value = ''
  load()
}

const roleLabel = (r) => ({ admin: '管理员', user: '用户', system: '系统' }[r] || r)
const kindLabel = (k) =>
  ({ inquiry: '问询', statement: '说明', appeal: '申辩', reply: '回复', notice: '留痕' }[k] || k)
const fmt = (v) => (v ? new Date(v).toLocaleString('zh-CN') : '')

onMounted(load)
</script>

<style scoped>
.snapshot {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
}
.messages {
  max-height: 300px;
  overflow: auto;
}
.message {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
  font-size: 13px;
}
.message.admin {
  background: #ecf5ff;
}
.message.system {
  background: #f4f4f5;
}
.meta {
  color: #909399;
  font-size: 12px;
  margin-bottom: 4px;
}
.hint {
  color: #909399;
  font-size: 12px;
}
</style>
