<template>
  <div v-if="c">
    <van-nav-bar :title="c.title" left-arrow @click-left="$router.back()" fixed placeholder />
    <van-cell-group inset style="margin-top: 10px">
      <van-cell title="类型" :value="caseTypeLabels[c.case_type]" />
      <van-cell title="状态" :value="caseStatusLabels[c.status]" />
      <van-cell v-if="c.conclusion" title="结论" :label="c.conclusion_reason || c.conclusion" />
    </van-cell-group>

    <van-cell-group inset style="margin-top: 10px" title="沟通记录（说明/申辩与管理员回复）">
      <div v-for="m in c.messages" :key="m.id" class="msg" :class="m.role">
        <div class="meta">
          <van-tag plain :type="m.role === 'admin' ? 'primary' : m.role === 'system' ? 'default' : 'success'">
            {{ { admin: '管理员', user: '我', system: '系统' }[m.role] }}
          </van-tag>
          {{ kindLabels[m.kind] || m.kind }} · {{ fmtTime(m.created_at) }}
        </div>
        <div class="body">{{ m.content }}</div>
      </div>
      <div v-if="!c.messages?.length" class="empty-tip">暂无沟通记录</div>
    </van-cell-group>

    <div class="actions" v-if="c.status !== 'pending'">
      <van-button v-if="c.has_inquiry && c.status !== 'disposed'" block type="primary" plain style="margin-bottom: 8px" @click="submit('statement')">
        提交说明（问询阶段）
      </van-button>
      <van-button v-if="c.status === 'disposed'" block type="warning" plain @click="submit('appeal')">提交申辩</van-button>
    </div>
    <p class="hint">说明与申辩由认领管理员在原事项回复；提交不自动撤销处置。</p>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showDialog, showToast } from 'vant'
import http from '../api/http'
import { caseTypeLabels, caseStatusLabels, fmtTime } from '../api/labels'

const route = useRoute()
const c = ref(null)
const kindLabels = { inquiry: '问询', statement: '说明', appeal: '申辩', reply: '回复', notice: '留痕' }

async function load() {
  c.value = await http.get(`/me/cases/${route.params.id}`)
}

async function submit(kind) {
  const title = kind === 'statement' ? '提交说明' : '提交申辩'
  const { value } = await showDialog({
    title,
    message: kind === 'statement' ? '针对问询内容进行说明' : '对处置结论提出申辩',
    showCancelButton: true,
  }).catch(() => ({ value: null }))
  if (!value) return
  const data = await http.post(`/me/cases/${route.params.id}/${kind}`, { content: value })
  showToast(data.detail)
  load()
}

onMounted(load)
</script>

<style scoped>
.msg {
  padding: 10px 16px;
  border-bottom: 1px solid #f2f3f5;
}
.msg.system .body {
  color: #969799;
}
.meta {
  font-size: 12px;
  color: #969799;
  margin-bottom: 4px;
  display: flex;
  gap: 6px;
  align-items: center;
}
.body {
  font-size: 14px;
}
.actions {
  margin: 14px 16px 0;
}
.hint {
  color: #969799;
  font-size: 12px;
  text-align: center;
  margin: 10px 0 20px;
}
</style>
