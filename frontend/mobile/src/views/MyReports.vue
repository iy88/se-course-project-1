<template>
  <div>
    <van-nav-bar title="我的举报 / 我收到的举报" left-arrow @click-left="$router.back()" fixed placeholder />
    <van-tabs v-model:active="tab">
      <van-tab title="我的举报" name="mine" />
      <van-tab title="我收到的" name="received" />
    </van-tabs>

    <van-cell-group inset style="margin-top: 10px" v-if="tab === 'mine'">
      <div v-for="r in mine" :key="r.id" class="report">
        <div class="head">
          <van-tag plain type="warning">{{ reportStatusLabels[r.status] }}</van-tag>
          <span class="target">{{ r.target_type }}#{{ r.target_id }}</span>
          <span class="time">{{ fmtTime(r.created_at) }}</span>
        </div>
        <div class="reason">原因：{{ r.reason }}</div>
        <div v-if="r.result_confirmed" class="result">
          处理结论：{{ r.public_result || '—' }}
          <van-button v-if="r.case_id && r.status === 'processing'" size="small" plain @click="supplement(r)">补充说明</van-button>
        </div>
        <div v-for="s in r.supplements" :key="s.id" class="supplement">补充：{{ s.content }}</div>
      </div>
      <div v-if="!mine.length" class="empty-tip">暂无举报记录</div>
    </van-cell-group>

    <van-cell-group inset style="margin-top: 10px" v-else>
      <van-cell v-for="r in received" :key="r.id" :title="`${r.target_type}#${r.target_id}`"
        :label="r.public_result || '已处置'" is-link @click="openCase(r)">
        <template #value>{{ fmtTime(r.created_at) }}</template>
      </van-cell>
      <van-empty v-if="!received.length" description="仅显示已实际处置的事项；问询阶段请从问询通知进入" />
    </van-cell-group>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showDialog } from 'vant'
import http from '../api/http'
import { fmtTime, reportStatusLabels } from '../api/labels'

const tab = ref('mine')
const mine = ref([])
const received = ref([])
const router = useRouter()

async function load() {
  mine.value = await http.get('/reports/mine')
  received.value = await http.get('/reports/received')
}

async function supplement(r) {
  const { value } = await showDialog({
    title: '补充说明或证据',
    message: '同一事项内补充，结案后不再接受。',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (!value) return
  await http.post(`/reports/${r.id}/supplements`, { content: value })
  load()
}

function openCase(r) {
  if (r.case_id) router.push(`/cases/${r.case_id}`)
}

onMounted(load)
</script>

<style scoped>
.report {
  padding: 10px 16px;
  border-bottom: 1px solid #f2f3f5;
}
.head {
  display: flex;
  gap: 8px;
  align-items: center;
}
.target {
  font-size: 13px;
}
.time {
  margin-left: auto;
  color: #969799;
  font-size: 12px;
}
.reason {
  margin: 6px 0;
  font-size: 14px;
}
.result {
  font-size: 13px;
  color: #07c160;
}
.supplement {
  font-size: 12px;
  color: #969799;
}
</style>
