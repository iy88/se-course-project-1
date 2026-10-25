<template>
  <div>
    <el-card header="交易处置（冻结/解冻与有依据调整全部状态）">
      <el-form inline>
        <el-form-item label="交易 ID">
          <el-input-number v-model="tradeId" :min="1" @change="load" />
        </el-form-item>
        <el-form-item>
          <el-button @click="load">查询</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="$route.query.trade_id && !tradeId"
        :title="`从事项进入：交易 #${$route.query.trade_id}`"
        type="info"
        :closable="false"
      />
    </el-card>

    <el-card v-if="trade" style="margin-top: 16px">
      <el-descriptions :column="3" border title="交易概要">
        <el-descriptions-item label="交易#">{{ trade.id }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          {{ trade.status }}
          <el-tag v-if="trade.frozen" type="danger" style="margin-left: 6px">冻结中</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="商品">{{ trade.product?.title }}（{{ trade.product?.status }}）</el-descriptions-item>
        <el-descriptions-item label="买方">{{ trade.buyer?.display_name }}#{{ trade.buyer?.id }}</el-descriptions-item>
        <el-descriptions-item label="卖方">{{ trade.seller?.display_name }}#{{ trade.seller?.id }}</el-descriptions-item>
        <el-descriptions-item label="当前约定">{{ trade.current_agreement_id ? `约定#${trade.current_agreement_id}` : '无' }}</el-descriptions-item>
      </el-descriptions>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="12">
          <h4>约定历史</h4>
          <el-table :data="trade.agreements" size="small" border>
            <el-table-column prop="round_no" label="轮次" width="60" />
            <el-table-column prop="status" label="状态" width="90" />
            <el-table-column label="金额" width="90">
              <template #default="{ row }">￥{{ (row.amount_cents / 100).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="delivery_location" label="地点" />
            <el-table-column prop="payment_method" label="支付方式" width="100" />
          </el-table>
          <h4>完成确认</h4>
          <el-table :data="trade.confirmations" size="small" border>
            <el-table-column prop="confirmer_id" label="确认人" width="80" />
            <el-table-column label="当前有效" width="90">
              <template #default="{ row }">{{ row.is_current ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column prop="confirmed_at" label="时间">
              <template #default="{ row }">{{ fmt(row.confirmed_at) }}</template>
            </el-table-column>
          </el-table>
        </el-col>
        <el-col :span="12">
          <h4>状态转移历史</h4>
          <el-table :data="trade.transitions" size="small" border max-height="320">
            <el-table-column prop="from_status" label="前状态" width="110" />
            <el-table-column prop="to_status" label="后状态" width="110" />
            <el-table-column prop="actor_role" label="主体" width="70" />
            <el-table-column prop="trigger" label="触发" width="130" />
            <el-table-column prop="reason" label="原因/依据" show-overflow-tooltip />
          </el-table>
        </el-col>
      </el-row>

      <el-divider content-position="left">处置操作</el-divider>
      <el-form inline>
        <el-form-item label="冻结理由">
          <el-input v-model="freezeReason" style="width: 240px" placeholder="冻结须说明依据" />
        </el-form-item>
        <el-form-item>
          <el-button type="warning" :disabled="trade.frozen" @click="doFreeze">冻结交易</el-button>
          <el-button type="success" :disabled="!trade.frozen" @click="doUnfreeze">解除冻结</el-button>
        </el-form-item>
        <el-form-item label="调整目标状态">
          <el-select v-model="adjustTarget" style="width: 170px">
            <el-option v-for="s in adjustTargets" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="依据">
          <el-input v-model="adjustReason" style="width: 260px" placeholder="调整依据（必填，留据并通知双方）" />
        </el-form-item>
        <el-form-item>
          <el-button type="danger" @click="doAdjust">执行调整</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/http'

const route = useRoute()
const tradeId = ref(Number(route.query.trade_id) || null)
const trade = ref(null)
const freezeReason = ref('')
const adjustTarget = ref('')
const adjustReason = ref('')
const adjustTargets = [
  { value: 'pending_acceptance', label: '待接受' },
  { value: 'in_progress', label: '进行中（恢复并清当前确认）' },
  { value: 'disputed', label: '有争议' },
  { value: 'abnormal', label: '异常交易' },
  { value: 'terminated', label: '已终止' },
  { value: 'completed', label: '已完成（不伪造确认）' },
]
const fmt = (v) => (v ? new Date(v).toLocaleString('zh-CN') : '')

async function load() {
  if (!tradeId.value) return
  trade.value = await http.get(`/admin/trades/${tradeId.value}`)
}

async function doFreeze() {
  if (!freezeReason.value.trim()) return ElMessage.warning('冻结须填写理由')
  await http.post(`/admin/trades/${trade.value.id}/freeze`, { reason: freezeReason.value })
  ElMessage.success('已冻结并通知双方')
  load()
}

async function doUnfreeze() {
  const { value } = await ElMessageBox.prompt('解除冻结依据', '解除冻结', { inputType: 'textarea' })
  await http.post(`/admin/trades/${trade.value.id}/unfreeze`, { reason: value })
  ElMessage.success('已解除冻结')
  load()
}

async function doAdjust() {
  if (!adjustTarget.value || !adjustReason.value.trim()) return ElMessage.warning('请选择目标状态并填写依据')
  await ElMessageBox.confirm('状态调整须留据并通知双方，不伪造用户确认。确认执行？', '确认调整', { type: 'warning' })
  await http.post(`/admin/trades/${trade.value.id}/adjust`, {
    to_status: adjustTarget.value,
    reason: adjustReason.value,
  })
  ElMessage.success('已调整并留据')
  load()
}

onMounted(load)
</script>
