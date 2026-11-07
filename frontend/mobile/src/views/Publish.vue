<template>
  <div class="publish-page">
    <AppNavBar :title="isEdit ? '编辑商品' : '发布商品'" />

    <div class="view">
      <div v-if="session.banned" class="alert alert--danger">
        <AppIcon name="alert" :size="17" />
        <span>账户封禁中：禁止发布或修改商品；仍可只读查看本人记录，并通过处置通知与沟通单联系管理员。</span>
      </div>
      <div v-else-if="session.hasFrozenTrade" class="alert alert--warn">
        <AppIcon name="alert" :size="17" />
        <span>
          {{ isEdit
            ? '交易冻结中：可保存无关商品的合规编辑；不能发布、上架、下架或重新上架。'
            : '交易冻结中：禁止发布新商品、主动上下架；无关商品的合规编辑仍可保存。' }}
        </span>
      </div>
      <div v-if="editNotice" class="alert alert--info">
        <AppIcon name="info" :size="17" />
        <span>{{ editNotice }}</span>
      </div>
      <div v-if="submitError" class="alert alert--danger">
        <AppIcon name="alert" :size="17" />
        <span>{{ submitError }}</span>
      </div>

      <router-link v-if="isEdit" :to="`/products/${editId}/review-records`" class="scope-entry">
        <span class="scope-entry__icon"><AppIcon name="doc" :size="19" /></span>
        <span class="scope-entry__main">
          <span class="scope-entry__title">审核记录</span>
          <span class="scope-entry__sub">查看历次审核结论与不通过原因</span>
        </span>
        <AppIcon name="chevron-right" :size="16" class="scope-entry__arrow" />
      </router-link>

      <button type="button" class="scope-entry" @click="showProhibited = true">
        <span class="scope-entry__icon"><AppIcon name="shield" :size="19" /></span>
        <span class="scope-entry__main">
          <span class="scope-entry__title">当前禁发范围</span>
          <span class="scope-entry__sub">发布前可查看平台禁止发布的物品</span>
        </span>
        <AppIcon name="chevron-right" :size="16" class="scope-entry__arrow" />
      </button>

      <van-form @submit="submit">
        <section class="surface form-section">
          <header class="form-section__head">
            <h2>基本信息</h2>
            <span>必填</span>
          </header>
          <div class="form-fields">
            <TextField :limit="120"
              v-model="form.title"
              label="标题"
              placeholder="商品标题"
              :rules="[{ required: true, message: '请输入标题' }]"
             />
            <TextField :limit="5000"
              v-model="form.description"
              label="描述"
              type="textarea"
              rows="3"
              autosize
              placeholder="描述商品状况、成色与附件"
              :rules="[{ required: true, message: '请输入描述' }]"
             />
            <van-field
              v-model="priceYuan"
              label="价格(元)"
              type="number"
              placeholder="0.00"
              :rules="[{ required: true, message: '请输入价格' }]"
            />
          </div>
        </section>

        <section class="surface form-section">
          <header class="form-section__head">
            <h2>商品图片</h2>
            <span>至少一张，最多 6 张</span>
          </header>
          <div class="upload-wrap">
            <van-uploader v-model="fileList" :max-count="6" />
            <p class="form-hint">建议上传清晰实拍图，图片比例会按原图保留。最多 6 张，单张不超过 10 MiB，支持 JPG/PNG/WebP/GIF。</p>
          </div>
        </section>

        <section class="surface form-section">
          <header class="form-section__head">
            <h2>分类标签</h2>
            <span>至少选择一个或申请新标签</span>
          </header>
          <van-checkbox-group v-model="selectedCategoryIds" direction="horizontal" class="tags">
            <van-checkbox
              v-for="c in categories"
              :key="c.id"
              :name="c.id"
              shape="square"
              :disabled="!isCategorySelectable(c, initialCategoryIds)"
            >
              <span :class="{ 'category-name--off': c.status === 'disabled' }">{{ c.name }}</span>
              <span v-if="c.status === 'disabled'" class="category-disabled">已停用</span>
            </van-checkbox>
          </van-checkbox-group>
          <div v-if="!categories.length" class="form-hint form-hint--pad">分类暂未加载，请刷新页面后重试。</div>
          <p v-else-if="hasDisabledCategories" class="form-hint form-hint--pad">
            已停用标签不能用于新发布或新增关联；编辑时仅保留原已有分类。
          </p>

          <div class="form-fields form-fields--top">
            <TextField :limit="64"
              v-if="!isEdit"
              v-model="newTagName"
              label="申请新标签"
              placeholder="没有合适的？申请新标签（随审核生效）"
             />
            <p v-else class="edit-tag-hint">编辑只能调整已有标签；需要新标签时请在审核未通过后重新提交申请。</p>
          </div>
        </section>

        <section v-if="isEdit && pendingTagApplications.length" class="surface form-section">
          <header class="form-section__head">
            <h2>本人待审核的新标签申请</h2>
            <span>可勾选撤回</span>
          </header>
          <van-checkbox-group v-model="withdrawTagIds" class="tags">
            <van-checkbox v-for="app in pendingTagApplications" :key="app.id" :name="app.id" shape="square">
              {{ app.requested_name }}
            </van-checkbox>
          </van-checkbox-group>
          <p class="edit-tag-hint">
            勾选表示保存时撤回该申请；只撤回本商品当前待审核的申请，不会重新发布或新造草稿。已有公共标签仍可在上方调整。
          </p>
        </section>

        <div class="publish-submit">
          <van-button block type="primary" native-type="submit" :loading="loading" :disabled="blocked">
            {{ submitText }}
          </van-button>
          <p class="publish-hint">{{ hintText }}</p>
        </div>
      </van-form>
    </div>

    <van-action-sheet v-model:show="showProhibited" title="当前禁发范围" class="app-bottom-popup">
      <div class="prohibited">
        <div v-for="item in prohibited" :key="item.id" class="prohibited__item">
          <b>{{ item.group_name }}</b>
          <p>{{ item.content }}</p>
        </div>
        <EmptyState
          v-if="!prohibited.length"
          icon="shield"
          title="暂未获取到禁发范围"
        />
      </div>
    </van-action-sheet>
  </div>
</template>

<script setup>
import TextField from '../components/TextField.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import AppIcon from '../components/AppIcon.vue'
import AppNavBar from '../components/AppNavBar.vue'
import EmptyState from '../components/EmptyState.vue'
import http from '../api/http'
import { uploadImage } from '../api/uploads'
import { uploadErrorMessage } from '../api/uploadErrors'
import {
  isCategorySelectable,
  pendingTagApplications as readPendingTagApplications,
  resolveResubmitMode,
  withdrawalSelection,
} from '../api/productEdit'
import { useSession } from '../stores/session'

const route = useRoute()
const router = useRouter()
const session = useSession()
const editId = computed(() => Number(route.params.id) || 0)
const isEdit = computed(() => editId.value > 0)

const form = reactive({ title: '', description: '' })
const priceYuan = ref('')
const fileList = ref([])
const categories = ref([])
const selectedCategoryIds = ref([])
const initialCategoryIds = ref([])
const newTagName = ref('')
const prohibited = ref([])
const showProhibited = ref(false)
const loading = ref(false)
const product = ref(null)
const submitError = ref('')
const withdrawTagIds = ref([])
const pendingTagApplications = computed(() => readPendingTagApplications(product.value))
// Disabled tags are retained only as previously existing categories when editing the original product; selectability is determined by isCategorySelectable against the initial associations.
const hasDisabledCategories = computed(() =>
  categories.value.some((category) => category.status === 'disabled'),
)

// When only a trade is frozen and the account is not banned, editing unrelated products is still allowed; new publishes and listing/unlisting are jointly restricted by the server and buttons.
const blocked = computed(() => {
  if (session.banned) return true
  if (!isEdit.value) return session.hasFrozenTrade
  return product.value?.display_restricted === true || product.value?.status === 'in_transaction'
})

// Determine resubmission only from the server's can_resubmit; withdrawing a pending tag application still uses a normal PATCH and must not become a republish via a query parameter.
const resubmitMode = computed(() => isEdit.value && resolveResubmitMode(product.value))

const submitText = computed(() => {
  if (resubmitMode.value) return '保存并重新提交审核'
  return isEdit.value ? '保存修改' : '提交审核'
})

const hintText = computed(() => {
  if (session.banned) return '封禁期间不能保存商品修改；管理沟通入口仍保留。'
  if (!isEdit.value && session.hasFrozenTrade) return '交易冻结期间不能发布新商品；无关商品仍可编辑。'
  if (resubmitMode.value) return '保存后重新进入待审核，不直接公开；原审核记录保留。'
  if (product.value?.status === 'pending_review') return '待审核期间可修改；审核以管理员提交结论时的最新保存内容为准，不重新排队。'
  if (isEdit.value) return '保存保留编辑前后内容；不触发二次审核，待接受请求不关闭。'
  return '提交后进入待审核，认领管理员审核通过后公开展示。'
})

const editNotice = computed(() => {
  if (!isEdit.value) return ''
  if (product.value?.status === 'in_transaction') return '商品交易中：禁止修改关键内容，保存会被服务端拒绝。'
  if (product.value?.display_restricted) return '商品因处置停止公开访问，当前不可编辑。'
  if (product.value?.status === 'rejected') return '审核未通过：保存将作为修改重提，形成新的审核记录。'
  if (resubmitMode.value) return '该商品已下架且可重新提交审核；保存将进入待审核，不会直接上架。'
  if (product.value?.status === 'pending_review') return '待审核商品可修改；撤回审核仅在管理员认领前可用。'
  return ''
})

async function uploadAll() {
  const keys = []
  for (const file of fileList.value) {
    if (file.key) {
      keys.push(file.key)
      continue
    }
    file.status = 'uploading'
    file.message = '上传中'
    try {
      const key = await uploadImage(file.file, 'product')
      file.key = key
      file.status = 'done'
      file.message = ''
      keys.push(key)
    } catch (error) {
      file.status = 'failed'
      // Show the specific reason (empty file / over 10 MiB / unsupported type / server rejection, etc.) so the user can correct it.
      file.message = uploadErrorMessage(error)
      throw error
    }
  }
  return keys
}

function serverDetail(err) {
  return typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '请求失败，请稍后重试'
}

async function submit() {
  submitError.value = ''
  if (blocked.value) return showToast('当前限制下不能保存商品')
  if (!fileList.value.length) return showToast('请至少上传一张图片')
  if (!selectedCategoryIds.value.length && !newTagName.value.trim()) return showToast('请选择或申请至少一个分类标签')
  loading.value = true
  try {
    const image_keys = await uploadAll()
    const payload = {
      title: form.title,
      description: form.description,
      price_cents: Math.round(Number(priceYuan.value || 0) * 100),
      image_keys,
      category_ids: selectedCategoryIds.value,
    }
    if (!isEdit.value) {
      const tags = selectedCategoryIds.value.map((id) => ({ category_id: id }))
      if (newTagName.value.trim()) tags.push({ new_name: newTagName.value.trim() })
      const idempotencyKey = (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`
      const data = await http.post('/products', { ...payload, tags }, {
        headers: { 'Idempotency-Key': idempotencyKey },
      })
      showToast('已提交，等待审核')
      router.replace(`/products/${data.id}`)
      return
    }
    if (resubmitMode.value) {
      const resubmitKey = (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`
      await http.post(`/products/${editId.value}/resubmit`, payload, {
        headers: { 'Idempotency-Key': resubmitKey },
      })
      showToast('已重新提交审核')
    } else {
      const withdrawal = withdrawalSelection(withdrawTagIds.value, pendingTagApplications.value)
      if (withdrawal.stale.length) {
        submitError.value = '部分待撤回标签申请已在服务端变化，未提交旧申请；请刷新页面后重新选择。'
        return
      }
      if (withdrawal.ids.length) payload.withdraw_tag_application_ids = withdrawal.ids
      await http.patch(`/products/${editId.value}`, payload)
      showToast('商品修改已保存')
    }
    router.replace(`/products/${editId.value}`)
  } catch (err) {
    // Keep the current form, images, and withdrawal selections; never record a failure as success or navigate away.
    // On upload/save failure prefer the specific reason (size, type, empty file, or server detail) so the banner and thumbnail hints stay consistent.
    submitError.value = `保存失败：${uploadErrorMessage(err, '请求失败，请稍后重试')}。已保留当前表单与撤回选择，未显示成功。`
  } finally {
    loading.value = false
  }
}

async function loadEditProduct() {
  try {
    const data = await http.get(`/products/${editId.value}`)
    if (data.seller_id !== session.user?.id) {
      showToast('只能编辑本人商品')
      router.replace(`/products/${editId.value}`)
      return
    }
    product.value = data
    form.title = data.title
    form.description = data.description
    priceYuan.value = (Number(data.price_cents || 0) / 100).toFixed(2)
    selectedCategoryIds.value = [...(data.tag_ids || [])]
    initialCategoryIds.value = [...(data.tag_ids || [])]
    withdrawTagIds.value = []
    fileList.value = (data.image_urls || []).map((url, index) => ({
      url,
      key: data.image_keys?.[index] || '',
      isImage: true,
    }))
  } catch {
    router.replace('/me/products')
  }
}

onMounted(async () => {
  // Account restrictions are refreshed by route transitions; do not request /auth/me again here.
  try {
    categories.value = await http.get('/categories')
  } catch (err) {
    submitError.value = `分类标签加载失败：${serverDetail(err)}。请刷新页面后重试。`
  }
  prohibited.value = await http.get('/prohibited-items').catch(() => [])
  if (isEdit.value) await loadEditProduct()
})
</script>

<style scoped>
.publish-page {
  padding-bottom: calc(20px + var(--safe-bottom));
}

.scope-entry {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  color: var(--ink);
  text-align: left;
  cursor: pointer;
}

.scope-entry:active {
  border-color: var(--line-strong);
}

.scope-entry__icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand);
}

.scope-entry__main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.scope-entry__title {
  font-size: 13.5px;
  font-weight: 600;
}

.scope-entry__sub {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.scope-entry__arrow {
  flex: 0 0 auto;
  color: var(--ink-faint);
}

.form-section {
  margin-bottom: 12px;
  overflow: hidden;
}

.form-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 13px 16px 11px;
  border-bottom: 1px solid var(--line);
}

.form-section__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.form-section__head span {
  color: var(--ink-meta);
  font-size: 11.5px;
}

.form-fields :deep(.van-field) {
  padding: 12px 16px;
}

.form-fields :deep(.van-field::after) {
  left: 16px;
  right: 16px;
  border-color: var(--line);
}

.form-fields :deep(.van-field:last-child::after) {
  display: none;
}

.form-fields :deep(.van-field__label) {
  width: 74px;
  margin-right: 8px;
  color: var(--ink-soft);
  font-size: 13px;
}

.form-fields :deep(.van-field__control) {
  font-size: 14px;
}

.form-fields--top {
  border-top: 1px solid var(--line);
}

.upload-wrap {
  padding: 14px 16px;
}

.upload-wrap :deep(.van-uploader__upload) {
  width: 82px;
  height: 82px;
}

.upload-wrap :deep(.van-uploader__preview-image) {
  width: 82px;
  height: 82px;
}

.form-hint {
  margin: 8px 0 0;
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.5;
}

.form-hint--pad {
  padding: 0 16px 12px;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 0;
  padding: 10px 16px 12px;
}

.tags :deep(.van-checkbox) {
  margin: 4px 14px 4px 0;
}

.tags :deep(.van-checkbox__label) {
  font-size: 13.5px;
}

.category-name--off {
  color: var(--ink-faint);
}

.category-disabled {
  margin-left: 4px;
  padding: 1px 6px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink-meta);
  font-size: 10.5px;
  line-height: 1.5;
}

.edit-tag-hint {
  margin: 0;
  padding: 10px 16px 12px;
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.55;
}

.publish-submit {
  padding: 8px 4px 0;
}

.publish-submit :deep(.van-button) {
  height: 46px;
}

.publish-hint {
  margin: 8px 0 0;
  color: var(--ink-meta);
  font-size: 11.5px;
  line-height: 1.55;
  text-align: center;
}

.prohibited {
  max-height: 58vh;
  overflow: auto;
  padding: 8px 16px calc(20px + var(--safe-bottom));
}

.prohibited__item {
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}

.prohibited__item b {
  font-size: 13.5px;
}

.prohibited__item p {
  margin: 3px 0 0;
  color: var(--ink-soft);
  font-size: 12.5px;
  line-height: 1.55;
}

@media (max-width: 359px) {
  .form-fields :deep(.van-field),
  .form-section__head {
    padding-left: 12px;
    padding-right: 12px;
  }

  .tags,
  .edit-tag-hint {
    padding-left: 12px;
    padding-right: 12px;
  }

  .form-fields :deep(.van-field__label) {
    width: 64px;
  }
}
</style>
