<template>
  <div class="audit-page">
    <header class="page-head">
      <div><p class="eyebrow">治理</p><h1>审计查询</h1></div>
    </header>
    <section class="audit-overview" aria-label="审计概览" v-loading="summaryLoading">
      <div class="overview-head">
        <div><h2>审计概览</h2><p>北京时间 · 最近 {{ summaryDays }} 天</p></div>
        <div class="toolbar-actions"><el-radio-group v-model="summaryDays" size="small" @change="loadSummary"><el-radio-button :value="7">7 天</el-radio-button><el-radio-button :value="30">30 天</el-radio-button></el-radio-group><el-button :loading="summaryLoading" @click="loadSummary">刷新概览</el-button></div>
      </div>
      <el-alert v-if="summaryError" :title="summaryError" type="error" :closable="false" show-icon />
      <template v-if="summary && !summaryError">
        <div class="overview-metrics">
          <div><span>事件总数</span><strong>{{ number(summary.total) }}</strong></div>
          <div class="metric-success"><span>成功</span><strong>{{ number(summary.results.success) }}</strong></div>
          <div class="metric-failure"><span>失败</span><strong>{{ number(summary.results.failure) }}</strong></div>
          <div class="metric-denied"><span>拒绝</span><strong>{{ number(summary.results.denied) }}</strong></div>
        </div>
        <div class="overview-charts">
          <section><h3>每日事件趋势</h3><div v-if="summary.total" class="daily-chart" role="img" :aria-label="summary.daily.map(item => `${item.date}：${item.count} 条`).join('；')">
            <div v-for="item in summary.daily" :key="item.date" class="daily-column" :title="`${item.date} · ${number(item.count)} 条`"><div class="daily-track"><span :style="{ height: `${item.count / dailyMax * 100}%` }" /></div><small>{{ item.date.slice(5) }}</small></div>
          </div><p v-else class="chart-empty">当前时段暂无审计事件</p></section>
          <section><h3>事件分类</h3><div class="category-chart"><button v-for="item in summary.categories" :key="item.category" type="button" :class="{ selected: form.category === item.category }" :aria-pressed="form.category === item.category" @click="selectCategory(item.category)"><span>{{ categoryLabels[item.category] }}</span><i><b :style="{ width: `${item.count / categoryMax * 100}%` }" /></i><strong>{{ number(item.count) }}</strong></button></div><p class="chart-note">点击分类填入筛选，点击“查询”查看明细。</p></section>
        </div>
      </template>
    </section>
    <el-card>
      <el-form label-position="top" class="audit-filters" @submit.prevent="search">
        <el-form-item label="事件分类"><el-select v-model="form.category" clearable placeholder="全部分类"><el-option v-for="(label, value) in categoryLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="事件类型"><el-input v-model="form.event_type" maxlength="64" placeholder="如 auth.login_success" clearable /></el-form-item>
        <el-form-item label="操作者 ID"><el-input-number v-model="form.actor_id" :min="1" :precision="0" :controls="false" /></el-form-item>
        <el-form-item label="目标类型"><el-input v-model="form.target_type" maxlength="32" placeholder="如 trade" clearable /></el-form-item>
        <el-form-item label="目标 ID"><el-input v-model="form.target_id" maxlength="64" clearable /></el-form-item>
        <el-form-item label="执行结果">
          <el-select v-model="form.result" clearable placeholder="全部"><el-option label="成功" value="success" /><el-option label="失败" value="failure" /><el-option label="拒绝" value="denied" /></el-select>
        </el-form-item>
        <el-form-item label="请求 ID"><el-input v-model="form.request_id" maxlength="64" clearable /></el-form-item>
        <el-form-item :label="`开始时间（${localZone}）`"><input v-model="form.from" type="datetime-local" class="time-input" aria-label="开始时间" /></el-form-item>
        <el-form-item :label="`结束时间（${localZone}）`"><input v-model="form.to" type="datetime-local" class="time-input" aria-label="结束时间" /></el-form-item>
        <div class="filter-actions"><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button @click="reset">重置</el-button><el-button v-if="queried" :loading="loading" @click="load(page)">刷新记录</el-button></div>
      </el-form>

    </el-card>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="audit-error"><el-button size="small" @click="load(page)">重试查询</el-button></el-alert>
    <el-card v-if="!queried" class="query-placeholder"><el-icon :size="24"><Search /></el-icon><h3>查询审计明细</h3><p>选择分类、时间或操作人后点击查询，明细将按页展示。</p></el-card>
    <el-card v-else class="audit-results" v-loading="loading">
      <div class="audit-table-wrap">
        <el-table :data="rows" row-key="event_id" empty-text="无匹配审计记录">
          <el-table-column prop="event_id" label="事件 ID" width="100" />
          <el-table-column label="时间（北京）" width="185"><template #default="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
          <el-table-column prop="event_type" label="事件类型" min-width="220" />
          <el-table-column label="操作者" min-width="130"><template #default="{ row }">{{ row.actor_id == null ? (row.actor_role === 'system' ? '系统' : '匿名请求') : `#${row.actor_id}` }} · {{ row.actor_role || '—' }}</template></el-table-column>
          <el-table-column label="目标" min-width="140"><template #default="{ row }">{{ row.target_type || '—' }} {{ row.target_id == null ? '' : `#${row.target_id}` }}</template></el-table-column>
          <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="resultType(row.result)">{{ resultLabel(row.result) }}</el-tag></template></el-table-column>
          <el-table-column prop="reason_code" label="原因码" min-width="160" />
          <el-table-column label="详情" width="85" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="showEvent(row.event_id)">查看</el-button></template></el-table-column>
        </el-table>
      </div>
      <el-pagination class="audit-pagination" :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="changeSize" />
    </el-card>
    <el-drawer v-model="drawerOpen" title="审计事件详情（只读）" size="min(720px, 95vw)" @closed="clearEvent">
      <div v-loading="detailLoading">
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false"><el-button @click="showEvent(selectedId)">重新读取</el-button></el-alert>
        <template v-if="event">
          <el-descriptions :column="1" border>
            <el-descriptions-item v-for="field in detailFields" :key="field.key" :label="field.label">{{ field.key === 'created_at' ? fmt(event[field.key]) : (event[field.key] ?? '—') }}</el-descriptions-item>
          </el-descriptions>
          <h3>变更前</h3><pre>{{ json(event.before_json) }}</pre><h3>变更后</h3><pre>{{ json(event.after_json) }}</pre>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import http from '../api/http'
import { Search } from '@element-plus/icons-vue'
import { fmtTime as fmt } from '../api/time'
const blank = () => ({ event_type: '', actor_id: undefined, target_type: '', target_id: '', result: '', request_id: '', from: '', to: '' })
const form = reactive({ ...blank(), category: '' })
const categoryLabels = { account: '账户与认证', product: '商品', trade: '交易', message: '消息与会话', governance: '治理与处置', file: '文件上传', configuration: '平台配置', other: '其他' }
const queried = ref(false)
const summary = ref(null), summaryDays = ref(7), summaryLoading = ref(false), summaryError = ref('')
let summaryVersion = 0
const number = (value) => Number(value || 0).toLocaleString('zh-CN')
const dailyMax = computed(() => Math.max(1, ...(summary.value?.daily || []).map(item => item.count)))
const categoryMax = computed(() => Math.max(1, ...(summary.value?.categories || []).map(item => item.count)))
function selectCategory(category) { form.category = category }
async function loadSummary() {
  const version = ++summaryVersion
  summaryLoading.value = true; summaryError.value = ''; summary.value = null
  try {
    const data = await http.get('/admin/audit/summary', { params: { days: summaryDays.value } })
    if (version === summaryVersion) summary.value = data
  } catch (e) { if (version === summaryVersion) summaryError.value = message(e) }
  finally { if (version === summaryVersion) summaryLoading.value = false }
}
const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone
const applied = ref({})
const rows = ref([]), total = ref(0), page = ref(1), pageSize = ref(20)
const loading = ref(false), error = ref('')
const drawerOpen = ref(false), event = ref(null), selectedId = ref(null), detailLoading = ref(false), detailError = ref('')
let listVersion = 0, detailVersion = 0
const resultLabel = (r) => ({ success: '成功', failure: '失败', denied: '拒绝' }[r] || r)
const resultType = (r) => ({ success: 'success', failure: 'danger', denied: 'warning' }[r] || 'info')
const json = (v) => JSON.stringify(v ?? null, null, 2)
const detailFields = [ ['event_id','事件 ID'],['created_at','时间（北京）'],['event_type','事件类型'],['actor_id','操作者 ID'],['actor_role','操作者角色'],['target_type','目标类型'],['target_id','目标 ID'],['result','结果'],['reason_code','原因码'],['request_id','请求 ID'],['ip','来源 IP'],['user_agent','浏览器标识'] ].map(([key,label]) => ({key,label}))
const message = (e) => typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : '查询失败，请检查网络并重试'
async function load(next = 1) {
  if (!queried.value) return
  const version = ++listVersion
  page.value = next; loading.value = true; error.value = ''; rows.value = []
  try {
    const data = await http.get('/admin/audit/events', { params: { ...applied.value, offset: (next - 1) * pageSize.value, limit: pageSize.value } })
    if (version !== listVersion) return
    rows.value = data.items; total.value = data.total
  } catch (e) {
    if (version === listVersion) { error.value = message(e); total.value = 0 }
  } finally { if (version === listVersion) loading.value = false }
}
function search() {
  const params = {}
  for (const [key,value] of Object.entries(form)) {
    if (value == null || value === '') continue
    if (key === 'from' || key === 'to') {
      const date = new Date(value)
      if (!Number.isFinite(date.getTime())) { error.value = '请填写有效时间'; return }
      params[key] = date.toISOString()
    } else if (key === 'actor_id') {
      if (!Number.isInteger(value) || value < 1) { error.value = '操作者 ID 须为正整数'; return }
      params[key] = value
    } else if (value.trim()) params[key] = value.trim()
  }
  if (params.from && params.to && Date.parse(params.from) > Date.parse(params.to)) { error.value = '开始时间不得晚于结束时间'; return }
  queried.value = true; applied.value = params; load(1)
}
function reset() { ++listVersion; Object.assign(form, blank(), { category: '' }); applied.value = {}; rows.value = []; total.value = 0; page.value = 1; queried.value = false; loading.value = false; error.value = ''; drawerOpen.value = false; clearEvent() }
function changeSize(size) { pageSize.value = size; load(1) }
async function showEvent(id) {
  const version = ++detailVersion
  selectedId.value = id; drawerOpen.value = true; event.value = null; detailError.value = ''; detailLoading.value = true
  try {
    const data = await http.get(`/admin/audit/events/${id}`)
    if (version === detailVersion) event.value = data
  } catch (e) { if (version === detailVersion) detailError.value = message(e) }
  finally { if (version === detailVersion) detailLoading.value = false }
}
function clearEvent() { ++detailVersion; event.value = null; detailError.value = ''; detailLoading.value = false }
onMounted(loadSummary)
onBeforeUnmount(() => { ++listVersion; ++detailVersion; ++summaryVersion })
</script>

<style scoped>
.audit-overview { padding: 22px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.overview-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
.overview-head h2 { font-size: 17px; } .overview-head p { font-size: 12px; color: var(--ink-faint); margin-top: 4px; }
.overview-metrics { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; margin-bottom: 24px; }
.overview-metrics > div { padding: 16px; background: #f6f8f6; border-radius: 10px; display: grid; gap: 5px; }
.overview-metrics span { font-size: 12px; color: var(--ink-soft); } .overview-metrics strong { font-size: 25px; font-variant-numeric: tabular-nums; }
.metric-success strong { color: var(--ok); } .metric-failure strong { color: var(--danger); } .metric-denied strong { color: var(--warn); }
.overview-charts { display: grid; grid-template-columns: minmax(0,1.2fr) minmax(0,1fr); gap: 28px; }
.overview-charts h3 { font-size: 13px; margin-bottom: 16px; }
.daily-chart { height: 218px; display: flex; gap: 6px; overflow-x: auto; align-items: stretch; padding-top: 12px; }
.daily-column { flex: 1; min-width: 20px; display: flex; flex-direction: column; gap: 10px; align-items: center; }
.daily-track { width: 100%; height: 175px; display: flex; align-items: flex-end; border-bottom: 1px solid var(--line); }
.daily-track span { background: var(--brand); width: 100%; min-height: 1px; border-radius: 4px 4px 0 0; }
.daily-column small { font-size: 9px; color: var(--ink-faint); white-space: nowrap; }
.category-chart { display: grid; gap: 5px; }
.category-chart button { display: flex; align-items: center; gap: 12px; border: 0; padding: 5px 8px; border-radius: 6px; background: transparent; font: inherit; cursor: pointer; text-align: left; color: var(--ink-soft); }
.category-chart button:hover, .category-chart button.selected { background: var(--brand-soft); color: var(--brand-ink); }
.category-chart button:focus-visible { outline: 2px solid var(--brand); }
.category-chart button > span { width: 90px; font-size: 12px; flex-shrink: 0; }
.category-chart i { flex: 1; background: #edf2ee; height: 7px; border-radius: 4px; overflow: hidden; }
.category-chart b { display: block; height: 100%; background: #73a58b; border-radius: 4px; }
.category-chart strong { min-width: 38px; font-size: 12px; text-align: right; }
.chart-note { color: var(--ink-faint); font-size: 11px; margin-top: 10px; }
.chart-empty { display: grid; place-items: center; min-height: 210px; color: var(--ink-faint); }
.query-placeholder { text-align: center; color: var(--ink-faint); padding: 24px; }
.query-placeholder h3 { margin: 10px 0 6px; font-size: 15px; color: var(--ink-soft); }
.query-placeholder p { font-size: 12px; }
@media(max-width:800px) { .overview-charts { grid-template-columns: 1fr; } .overview-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); } }

.audit-page { display: grid; gap: 18px; }
.page-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
h1 { margin: 4px 0 8px; } .eyebrow,.sub,.hint { color: #63756b; } .eyebrow { margin: 0; }
.audit-filters { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 0 16px; }
.audit-filters :deep(.el-input-number),.audit-filters :deep(.el-select) { width: 100%; }
.time-input { width: 100%; min-width: 0; height: 38px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; color: var(--ink); background: #f9fbf9; transition: border-color .16s, box-shadow .16s; }
.time-input:hover { border-color: var(--line-strong); }
.time-input:focus { outline: none; border-color: var(--brand); background: #fff; box-shadow: 0 0 0 3px rgba(47,107,79,.08); }
.filter-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; grid-column: 1 / -1; padding: 12px 0; }
.filter-actions .el-button + .el-button { margin-left: 0; } .audit-table-wrap { overflow-x: auto; }
.audit-pagination { margin-top: 20px; overflow-x: auto; } pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f7f5; padding: 14px; border-radius: 6px; }
@media(max-width:1100px) { .audit-filters { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media(max-width:600px) { .audit-filters { grid-template-columns: 1fr; } .page-head { align-items: flex-start; flex-direction: column; } }
</style>
