<template>
  <div>
    <el-card>
      <template #header>
        <div class="header">
          <span>数据统计</span>
          <div class="range">
            <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" style="width: 280px" />
            <el-button @click="clearRange">全部</el-button>
            <el-button type="primary" @click="load">查询</el-button>
          </div>
        </div>
      </template>
      <el-row :gutter="16">
        <el-col :span="6">
          <el-statistic title="用户总数" :value="stats.users.total" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="封禁账户" :value="stats.users.banned" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="待处理审核" :value="stats.pending.review_cases" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="待处理举报" :value="stats.pending.report_cases" />
        </el-col>
      </el-row>
      <el-row v-if="stats.range.completed_trades !== null" style="margin-top: 16px">
        <el-col :span="8">
          <el-statistic :title="`范围完成交易（${stats.range.from || '…'} ~ ${stats.range.to || '…'}）`" :value="stats.range.completed_trades" />
        </el-col>
      </el-row>
    </el-card>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="12">
        <el-card header="商品状态分布">
          <div class="grid">
            <el-tag v-for="(value, key) in stats.products" :key="key" class="cell">
              {{ productLabel(key) }}：{{ value }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card header="交易状态分布">
          <div class="grid">
            <el-tag v-for="(value, key) in stats.trades" :key="key" class="cell" :type="key === 'terminated' ? 'danger' : 'primary'">
              {{ tradeLabel(key) }}：{{ value }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-alert type="info" :closable="false" style="margin-top: 12px"
      title="统计不包含真实付款金额或流水；状态数量按查询时点，范围统计按结果确认时间。" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import http from '../api/http'

const stats = ref({ users: {}, products: {}, pending: {}, trades: {}, range: {} })
const range = ref(null)

const productLabels = {
  pending_review: '待审核',
  rejected: '审核未通过',
  listed: '公开可交易',
  in_transaction: '交易中',
  delisted: '已下架',
  display_restricted: '停止公开',
}
const tradeLabels = {
  pending_acceptance: '待接受',
  rejected: '已拒绝',
  withdrawn: '已撤回',
  closed: '已关闭',
  in_progress: '进行中',
  disputed: '有争议',
  abnormal: '异常交易',
  terminated: '已终止（失败）',
  completed: '已完成',
  frozen_current: '冻结中',
}
const productLabel = (k) => productLabels[k] || k
const tradeLabel = (k) => tradeLabels[k] || k

function clearRange() {
  range.value = null
  load()
}

async function load() {
  const params = {}
  if (range.value && range.value.length === 2) {
    params.from = range.value[0]
    params.to = range.value[1]
  }
  stats.value = await http.get('/admin/stats', { params })
}

onMounted(load)
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.range {
  display: flex;
  gap: 8px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.cell {
  justify-content: center;
}
</style>
