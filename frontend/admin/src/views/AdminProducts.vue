<template>
  <div>
    <el-card header="商品检索（处置/纠正视角）">
      <div class="toolbar">
        <el-input v-model="keyword" placeholder="按用户邮箱/名称检索其商品需从账户管理进入；此处按商品检索不支持，走待审事项" disabled style="width: 320px" />
      </div>
      <el-alert type="info" :closable="false" show-icon
        title="管理端不提供全量商品浏览；商品内容通过认领的审核/举报事项查看，分类纠正针对具体商品执行。" />
    </el-card>

    <el-card header="分类纠正（输入商品 ID）" style="margin-top: 16px">
      <el-form inline>
        <el-form-item label="商品 ID">
          <el-input-number v-model="correctForm.product_id" :min="1" />
        </el-form-item>
        <el-form-item label="选择分类（可多选）">
          <el-select v-model="correctForm.category_ids" multiple style="min-width: 260px">
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="依据说明">
          <el-input v-model="correctForm.reason" style="width: 280px" placeholder="纠正原因（必填，将通知卖方）" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submitCorrection">执行纠正</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/http'

const keyword = ref('')
const categories = ref([])
const correctForm = reactive({ product_id: null, category_ids: [], reason: '' })

async function submitCorrection() {
  if (!correctForm.product_id || !correctForm.category_ids.length || !correctForm.reason.trim()) {
    return ElMessage.warning('请完整填写商品 ID、分类与纠正原因')
  }
  await http.post(`/admin/products/${correctForm.product_id}/correct-category`, {
    category_ids: correctForm.category_ids,
    reason: correctForm.reason,
  })
  ElMessage.success('分类纠正完成并通知卖方')
  correctForm.reason = ''
}

onMounted(async () => {
  categories.value = await http.get('/categories')
})
</script>

<style scoped>
.toolbar {
  margin-bottom: 12px;
}
</style>
