<script setup lang="ts">
/*
 * Create or edit a product and submit it for review.
 *
 * One form serves both modes because the fields are identical; the only
 * difference is that editing sends `expected_version` so a concurrent change is
 * rejected instead of silently overwritten. The banned-scope summary is shown
 * before publishing, as US-02 requires the seller to see it first.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  createProduct,
  getProduct,
  listCategories,
  readBannedScope,
  updateProduct,
} from "../../api/products";
import type { BannedScopeView, CategoryView, ProductDetail } from "../../api/contracts";
import { formatCentsAsYuanInput, parseYuanToCents } from "../../app/format";
import { IdempotencyKeys } from "../../app/keys";
import { bannedGroupLabels } from "../../app/labels";
import { problemMessage } from "../../app/problems";
import { notify } from "../../app/toast";
import ErrorNotice from "../../components/ErrorNotice.vue";
import ImageUploader from "../../components/ImageUploader.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";

const route = useRoute();
const router = useRouter();

const productId = computed(() => {
  const value = route.params.productId;
  return typeof value === "string" && value !== "" ? value : null;
});
const isEditing = computed(() => productId.value !== null);

const title = ref("");
const description = ref("");
const priceInput = ref("");
const selectedCategoryIds = ref<string[]>([]);
const newCategoryName = ref("");
const imageFileIds = ref<string[]>([]);

const categories = ref<CategoryView[]>([]);
const bannedScope = ref<BannedScopeView | null>(null);
const loaded = ref(false);
const loading = ref(false);
const loadError = ref<unknown>(null);
const submitting = ref(false);
const submitError = ref<string | null>(null);
const fieldErrors = ref<Record<string, string>>({});
const editing = ref<ProductDetail | null>(null);
const keys = new IdempotencyKeys();

const selectableCategories = computed(() =>
  categories.value.filter(
    (category) => category.selectable || selectedCategoryIds.value.includes(category.id),
  ),
);

const canApplyNewCategory = computed(() => {
  if (!isEditing.value) return true;
  const state = editing.value?.lifecycle_state;
  return state === "pending_review" || state === "review_rejected";
});

const bannedItemCount = computed(
  () => bannedScope.value?.groups.reduce((sum, group) => sum + group.items.length, 0) ?? 0,
);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  try {
    const [categoryResult, scope] = await Promise.all([
      listCategories(),
      readBannedScope().catch(() => null),
    ]);
    categories.value = categoryResult.items;
    bannedScope.value = scope;
    if (productId.value) {
      const detail = await getProduct(productId.value);
      editing.value = detail;
      title.value = detail.title;
      description.value = detail.description;
      priceInput.value = formatCentsAsYuanInput(detail.price_cents);
      selectedCategoryIds.value = detail.categories.map((category) => category.id);
      imageFileIds.value = detail.images.map((image) => image.file_id);
    }
    loaded.value = true;
  } catch (caught) {
    loadError.value = caught;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void load();
});

watch(productId, () => {
  void load();
});

function toggleCategory(id: string): void {
  selectedCategoryIds.value = selectedCategoryIds.value.includes(id)
    ? selectedCategoryIds.value.filter((value) => value !== id)
    : [...selectedCategoryIds.value, id];
}

function validate(): boolean {
  const errors: Record<string, string> = {};
  if (!title.value.trim()) errors.title = "请填写标题。";
  if (!description.value.trim()) errors.description = "请填写商品描述。";
  const cents = parseYuanToCents(priceInput.value);
  if (cents === null) errors.price = "请填写有效的价格，例如 45 或 45.50。";
  if (!selectedCategoryIds.value.length && !newCategoryName.value.trim()) {
    errors.categories = "请至少选择一个分类，或填写新分类名称。";
  }
  if (isEditing.value && editing.value?.lifecycle_state === "in_trade") {
    errors.form = "交易中的商品不能修改关键内容。";
  }
  fieldErrors.value = errors;
  return Object.keys(errors).length === 0;
}

async function submit(): Promise<void> {
  if (submitting.value) return;
  submitError.value = null;
  if (!validate()) return;
  const priceCents = parseYuanToCents(priceInput.value);
  if (priceCents === null) return;

  submitting.value = true;
  const operation = isEditing.value ? "update-product" : "create-product";
  try {
    const application = newCategoryName.value.trim()
      ? { proposed_name: newCategoryName.value.trim() }
      : undefined;
    if (productId.value && editing.value) {
      const updated = await updateProduct(
        productId.value,
        {
          title: title.value.trim(),
          description: description.value.trim(),
          price_cents: priceCents,
          category_ids: selectedCategoryIds.value,
          image_file_ids: imageFileIds.value,
          category_application: canApplyNewCategory.value ? application : undefined,
          expected_version: editing.value.content_version,
        },
        keys.current(operation),
      );
      keys.rotate(operation);
      notify.success(
        updated.lifecycle_state === "pending_review"
          ? "修改已保存，审核结论以最新内容为准。"
          : "修改已保存。",
      );
      await router.push({ name: "product-detail", params: { productId: updated.id } });
      return;
    }
    const created = await createProduct(
      {
        title: title.value.trim(),
        description: description.value.trim(),
        price_cents: priceCents,
        category_ids: selectedCategoryIds.value,
        image_file_ids: imageFileIds.value,
        category_application: application,
      },
      keys.current(operation),
    );
    keys.rotate(operation);
    notify.success("商品已提交审核，通过后会公开展示。");
    await router.push({ name: "product-detail", params: { productId: created.id } });
  } catch (caught) {
    submitError.value = problemMessage(caught);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      :eyebrow="isEditing ? '我的商品' : '发布'"
      :title="isEditing ? '编辑商品' : '发布商品'"
      :description="
        isEditing
          ? '修改后仍需通过审核才能在列表中展示；待审核期间的修改以审核结论时最新内容为准。'
          : '填写商品与分类后提交审核，审核通过后公开可交易。'
      "
    >
      <template #actions>
        <RouterLink to="/me/banned-items" class="btn btn--ghost">查看禁发范围</RouterLink>
      </template>
    </PageHeader>

    <LoadingBlock v-if="loading" label="正在加载商品信息…" />
    <ErrorNotice v-else-if="loadError" :error="loadError" @retry="load" />
    <form v-else-if="loaded" class="stack stack--loose" @submit.prevent="submit">
      <section class="card stack">
        <div class="field">
          <label class="field__label" for="product-title">标题</label>
          <input
            id="product-title"
            v-model="title"
            class="input"
            :aria-invalid="Boolean(fieldErrors.title)"
            maxlength="80"
          />
          <span v-if="fieldErrors.title" class="field__error">{{ fieldErrors.title }}</span>
        </div>

        <div class="field">
          <label class="field__label" for="product-description">描述</label>
          <textarea
            id="product-description"
            v-model="description"
            class="textarea body-textarea"
            :aria-invalid="Boolean(fieldErrors.description)"
            maxlength="2000"
          />
          <span class="field__hint">{{ description.length }}/2000</span>
          <span v-if="fieldErrors.description" class="field__error">
            {{ fieldErrors.description }}
          </span>
        </div>

        <div class="field price-field">
          <label class="field__label" for="product-price">价格（元）</label>
          <input
            id="product-price"
            v-model="priceInput"
            class="input"
            inputmode="decimal"
            :aria-invalid="Boolean(fieldErrors.price)"
          />
          <span v-if="fieldErrors.price" class="field__error">{{ fieldErrors.price }}</span>
        </div>

        <ImageUploader
          v-model="imageFileIds"
          purpose="product_image"
          label="商品图片"
          hint="支持 JPG、PNG"
          :max-count="6"
          :target="productId ? { resource_type: 'product', resource_id: productId } : null"
        />
      </section>

      <section class="card stack">
        <div>
          <span class="field__label">分类（至少选择一个，或申请新分类）</span>
          <p class="field__hint">已停用的分类不能用于新发布。</p>
        </div>
        <div class="inline">
          <button
            v-for="category in selectableCategories"
            :key="category.id"
            type="button"
            class="chip chip--action"
            :class="{ 'chip--active': selectedCategoryIds.includes(category.id) }"
            @click="toggleCategory(category.id)"
          >
            {{ category.main_name }}
            <span v-if="!category.selectable" class="muted">（已停用）</span>
          </button>
        </div>
        <span v-if="fieldErrors.categories" class="field__error">{{ fieldErrors.categories }}</span>

        <div v-if="canApplyNewCategory" class="field">
          <label class="field__label" for="new-category">申请新分类（可选）</label>
          <input
            id="new-category"
            v-model="newCategoryName"
            class="input"
            maxlength="20"
            placeholder="没有合适的分类时填写，将随本次审核一并处理"
          />
        </div>
        <p v-else class="banner banner--info">
          当前状态不再接受新的分类申请；如需更换分类，请在上方重新选择。
        </p>
      </section>

      <section class="card">
        <div class="card__head">
          <h2>发布前确认禁发范围</h2>
          <RouterLink to="/me/banned-items" class="btn btn--small">查看完整范围</RouterLink>
        </div>
        <p class="muted">当前禁发范围共 {{ bannedItemCount }} 条；发布内容不得涉及以下类目。</p>
        <ul class="banned-preview">
          <li v-for="group in bannedScope?.groups ?? []" :key="group.group">
            <template v-if="group.items.length">
              <strong>{{ bannedGroupLabels[group.group] }}</strong>
              <span class="muted">{{ group.items.map((item) => item.content).join("；") }}</span>
            </template>
          </li>
        </ul>
      </section>

      <p v-if="fieldErrors.form" class="banner banner--danger">{{ fieldErrors.form }}</p>
      <p v-if="submitError" class="banner banner--danger" role="alert">{{ submitError }}</p>

      <div class="inline">
        <button type="submit" class="btn btn--primary" :disabled="submitting">
          {{ submitting ? "正在提交…" : isEditing ? "保存并重新提交审核" : "提交审核" }}
        </button>
        <RouterLink to="/me/products" class="btn btn--ghost">取消</RouterLink>
        <span v-if="editing && editing.lifecycle_state !== 'pending_review'" class="muted">
          当前价格：{{ formatCentsAsYuanInput(editing.price_cents) }} 元
        </span>
      </div>
    </form>
  </div>
</template>

<style scoped>
.body-textarea {
  min-block-size: 8rem;
}

.price-field {
  max-inline-size: 12rem;
}

.banned-preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-block-start: var(--space-2);
  font-size: 0.8125rem;
}

.banned-preview li {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}
</style>
