<script setup lang="ts">
/*
 * Product discovery: keyword, category and price filters over the public catalogue.
 *
 * US-03 requires combined filters with an explicit empty result state, so the
 * filter panel stays visible when nothing matches and the reset action clears all
 * three criteria at once.
 */
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { listCategories, searchProducts } from "../../api/products";
import type { CategoryView, ProductSummary } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatCents, formatRelative, parseYuanToCents } from "../../app/format";
import { notify } from "../../app/toast";
import ErrorNotice from "../../components/ErrorNotice.vue";
import EmptyState from "../../components/EmptyState.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";

const router = useRouter();

const keyword = ref("");
const minPrice = ref("");
const maxPrice = ref("");
const selectedCategories = ref<string[]>([]);
const categories = ref<CategoryView[]>([]);
const filterError = ref<string | null>(null);

const filters = reactive({
  keyword: "",
  categoryIds: [] as string[],
  minCents: null as number | null,
  maxCents: null as number | null,
});

const list = usePagedList<ProductSummary>((page, pageSize, signal) =>
  searchProducts(
    {
      keyword: filters.keyword || undefined,
      category_ids: filters.categoryIds.length ? filters.categoryIds : undefined,
      min_price_cents: filters.minCents ?? undefined,
      max_price_cents: filters.maxCents ?? undefined,
      page,
      page_size: pageSize,
    },
    signal,
  ),
);

const hasActiveFilters = computed(
  () =>
    filters.keyword !== "" ||
    filters.categoryIds.length > 0 ||
    filters.minCents !== null ||
    filters.maxCents !== null,
);

const filterableCategories = computed(() =>
  categories.value.filter((category) => category.has_public_products || category.selectable),
);

onMounted(async () => {
  void list.load(1);
  try {
    const result = await listCategories();
    categories.value = result.items;
  } catch (caught) {
    filterError.value = caught instanceof Error ? caught.message : "分类未能加载。";
  }
});

function applyFilters(): void {
  const min = minPrice.value.trim() ? parseYuanToCents(minPrice.value) : null;
  const max = maxPrice.value.trim() ? parseYuanToCents(maxPrice.value) : null;
  if (minPrice.value.trim() && min === null) {
    notify.warn("最低价需填写为数字，例如 20 或 20.50。");
    return;
  }
  if (maxPrice.value.trim() && max === null) {
    notify.warn("最高价需填写为数字，例如 200 或 200.50。");
    return;
  }
  if (min !== null && max !== null && min > max) {
    notify.warn("最低价不能高于最高价。");
    return;
  }
  filters.keyword = keyword.value.trim();
  filters.categoryIds = [...selectedCategories.value];
  filters.minCents = min;
  filters.maxCents = max;
  void list.load(1);
}

function resetFilters(): void {
  keyword.value = "";
  minPrice.value = "";
  maxPrice.value = "";
  selectedCategories.value = [];
  filters.keyword = "";
  filters.categoryIds = [];
  filters.minCents = null;
  filters.maxCents = null;
  void list.load(1);
}

function toggleCategory(id: string): void {
  const index = selectedCategories.value.indexOf(id);
  if (index >= 0) {
    selectedCategories.value = selectedCategories.value.filter((value) => value !== id);
    return;
  }
  selectedCategories.value = [...selectedCategories.value, id];
}

function openProduct(productId: string): void {
  void router.push({ name: "product-detail", params: { productId } });
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="逛逛"
      title="校园二手"
      description="按关键词、分类和价格区间查找在售商品。"
    >
      <template #actions>
        <RouterLink to="/products/new" class="btn btn--primary">发布商品</RouterLink>
      </template>
    </PageHeader>

    <section class="card filters">
      <form class="filters__row" @submit.prevent="applyFilters">
        <div class="field filters__keyword">
          <label class="field__label" for="keyword">关键词</label>
          <input
            id="keyword"
            v-model="keyword"
            class="input"
            type="search"
            placeholder="标题或描述中的词"
          />
        </div>
        <div class="field">
          <label class="field__label" for="min-price">最低价（元）</label>
          <input id="min-price" v-model="minPrice" class="input" inputmode="decimal" />
        </div>
        <div class="field">
          <label class="field__label" for="max-price">最高价（元）</label>
          <input id="max-price" v-model="maxPrice" class="input" inputmode="decimal" />
        </div>
        <div class="filters__actions">
          <button type="submit" class="btn btn--primary">搜索</button>
          <button
            type="button"
            class="btn btn--ghost"
            :disabled="!hasActiveFilters"
            @click="resetFilters"
          >
            清除条件
          </button>
        </div>
      </form>

      <div v-if="filterableCategories.length" class="filters__categories">
        <span class="field__label">分类</span>
        <div class="inline">
          <button
            v-for="category in filterableCategories"
            :key="category.id"
            type="button"
            class="chip chip--action"
            :class="{ 'chip--active': selectedCategories.includes(category.id) }"
            @click="toggleCategory(category.id)"
          >
            {{ category.main_name }}
          </button>
        </div>
      </div>
      <p v-if="filterError" class="field__error">{{ filterError }}</p>
    </section>

    <LoadingBlock v-if="list.isLoading.value" label="正在加载商品…" />
    <ErrorNotice
      v-else-if="list.problem.value"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <EmptyState
      v-else-if="list.isEmpty.value"
      :title="hasActiveFilters ? '没有符合条件的商品' : '暂时没有在售商品'"
      :description="
        hasActiveFilters ? '尝试减少分类条件或放宽价格区间。' : '成为第一个在这里发布商品的卖家。'
      "
    >
      <button v-if="hasActiveFilters" type="button" class="btn" @click="resetFilters">
        清除条件
      </button>
    </EmptyState>
    <template v-else>
      <ul class="product-grid">
        <li v-for="product in list.items.value" :key="product.id">
          <article class="product-card" @click="openProduct(product.id)">
            <div class="product-card__media">
              <img
                v-if="product.thumbnail"
                :src="product.thumbnail.url"
                :alt="product.title"
                loading="lazy"
              />
              <span v-else class="product-card__placeholder">暂无图片</span>
            </div>
            <h2 class="product-card__title clamp-2">{{ product.title }}</h2>
            <p class="product-card__price amount">{{ formatCents(product.price_cents) }}</p>
            <p class="product-card__meta muted">
              <span>{{ product.seller.display_name }}</span>
              <span>·</span>
              <span>{{ formatRelative(product.created_at) }}</span>
            </p>
            <p class="inline product-card__tags">
              <span v-for="category in product.categories" :key="category.id" class="tag">
                {{ category.name }}
              </span>
            </p>
          </article>
        </li>
      </ul>
      <PaginationBar
        :page="list.paging.page"
        :page-size="list.paging.pageSize"
        :total="list.paging.total"
        @change="list.load"
      />
    </template>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.filters__row {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  align-items: flex-end;
}

.filters__keyword {
  flex: 2 1 16rem;
}

.filters__row > .field {
  flex: 0 1 8rem;
}

.filters__actions {
  display: flex;
  gap: var(--space-2);
  flex: 0 0 auto;
}

.filters__categories {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-3);
}

.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
  gap: var(--space-3);
}

.product-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  block-size: 100%;
  padding: var(--space-3);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-soft);
  cursor: pointer;
  transition: border-color 120ms ease;
}

.product-card:hover {
  border-color: var(--brand);
}

.product-card__media {
  display: grid;
  place-items: center;
  aspect-ratio: 4 / 3;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #f4f8f5;
  margin-block-end: var(--space-2);
}

.product-card__media img {
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}

.product-card__placeholder {
  font-size: 0.75rem;
  color: var(--ink-faint);
}

.product-card__title {
  font-size: 0.875rem;
  font-weight: 600;
}

.product-card__price {
  color: var(--accent);
}

.product-card__meta {
  display: flex;
  gap: var(--space-1);
}

.product-card__tags {
  margin-block-start: var(--space-1);
}
</style>
