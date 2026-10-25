<template>
  <div>
    <van-nav-bar title="发布商品" left-arrow @click-left="$router.back()" fixed placeholder />

    <van-cell-group inset title="发布前可查看禁发范围">
      <van-cell title="当前禁发范围" is-link @click="showProhibited = true" />
    </van-cell-group>

    <van-form @submit="submit">
      <van-cell-group inset style="margin-top: 10px">
        <van-field v-model="form.title" label="标题" placeholder="商品标题"
          :rules="[{ required: true, message: '请输入标题' }]" />
        <van-field v-model="form.description" label="描述" type="textarea" rows="3" placeholder="描述商品状况"
          :rules="[{ required: true, message: '请输入描述' }]" />
        <van-field v-model="priceYuan" label="价格(元)" type="number" placeholder="0.00"
          :rules="[{ required: true, message: '请输入价格' }]" />
      </van-cell-group>

      <van-cell-group inset style="margin-top: 10px" title="图片（至少一张）">
        <van-uploader v-model="fileList" :max-count="6" />
      </van-cell-group>

      <van-cell-group inset style="margin-top: 10px" title="分类标签（至少选择一个或申请新标签）">
        <van-checkbox-group v-model="selectedCategoryIds" direction="horizontal" class="tags">
          <van-checkbox v-for="c in categories" :key="c.id" :name="c.id" shape="square">{{ c.name }}</van-checkbox>
        </van-checkbox-group>
        <van-field v-model="newTagName" label="申请新标签" placeholder="没有合适的？申请新标签（随审核生效）" />
      </van-cell-group>

      <div class="submit">
        <van-button round block type="primary" native-type="submit" :loading="loading">提交审核</van-button>
        <p class="hint">提交后进入待审核，认领管理员审核通过后公开展示。</p>
      </div>
    </van-form>

    <van-action-sheet v-model:show="showProhibited" title="当前禁发范围">
      <div class="prohibited">
        <div v-for="item in prohibited" :key="item.id" class="item">
          <b>{{ item.group_name }}</b>
          <p>{{ item.content }}</p>
        </div>
      </div>
    </van-action-sheet>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import http from '../api/http'

const router = useRouter()
const form = reactive({ title: '', description: '' })
const priceYuan = ref('')
const fileList = ref([])
const categories = ref([])
const selectedCategoryIds = ref([])
const newTagName = ref('')
const prohibited = ref([])
const showProhibited = ref(false)
const loading = ref(false)

async function uploadAll() {
  const keys = []
  for (const file of fileList.value) {
    if (file.key) {
      keys.push(file.key)
      continue
    }
    file.status = 'uploading'
    file.message = '上传中'
    const fd = new FormData()
    fd.append('file', file.file)
    const data = await http.post('/files/upload?namespace=product', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    file.key = data.key
    file.status = 'done'
    file.message = ''
    keys.push(data.key)
  }
  return keys
}

async function submit() {
  if (!fileList.value.length) return showToast('请至少上传一张图片')
  const tags = selectedCategoryIds.value.map((id) => ({ category_id: id }))
  if (newTagName.value.trim()) tags.push({ new_name: newTagName.value.trim() })
  if (!tags.length) return showToast('请选择或申请至少一个分类标签')
  loading.value = true
  try {
    const image_keys = await uploadAll()
    const data = await http.post('/products', {
      title: form.title,
      description: form.description,
      price_cents: Math.round(Number(priceYuan.value || 0) * 100),
      image_keys,
      tags,
    })
    showToast('已提交，等待审核')
    router.replace(`/products/${data.id}`)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  categories.value = await http.get('/categories')
  prohibited.value = await http.get('/prohibited-items').catch(() => [])
})
</script>

<style scoped>
.tags {
  padding: 12px 16px;
  gap: 8px;
}
.tags :deep(.van-checkbox) {
  margin: 4px 12px 4px 0;
}
.submit {
  margin: 20px 16px;
}
.hint {
  text-align: center;
  color: #969799;
  font-size: 12px;
}
.prohibited {
  padding: 12px 16px 24px;
  max-height: 50vh;
  overflow: auto;
}
.item {
  padding: 8px 0;
  border-bottom: 1px solid #f2f3f5;
}
.item p {
  margin: 4px 0 0;
  color: #646566;
  font-size: 13px;
}
</style>
