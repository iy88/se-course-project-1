<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";
import UiIcon from "../../../../shared/UiIcon.vue";
import { listCategories, searchProducts } from "../../api/products";
import type { ProductSummary } from "../../api/contracts";
import { useAsyncData, usePagedList } from "../../app/async";
import { categoryFilterOptions } from "../../app/category-filters";
import { formatCents, formatRelative, parseYuanToCents } from "../../app/format";
import ErrorNotice from "../../components/ErrorNotice.vue";
import EmptyState from "../../components/EmptyState.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PaginationBar from "../../components/PaginationBar.vue";

const route = useRoute();
const router = useRouter();

const searching = computed(() => route.name === "product-search");
const appliedKeyword = computed(() =>
  searching.value && typeof route.query.q === "string" ? route.query.q.trim() : "",
);
const appliedCategories = computed(() => {
  if (!searching.value) return [];
  return [route.query.category]
    .flat()
    .filter((value): value is string => typeof value === "string" && value !== "");
});
const appliedMinPrice = computed(() =>
  searching.value && typeof route.query.min === "string" ? route.query.min : "",
);
const appliedMaxPrice = computed(() =>
  searching.value && typeof route.query.max === "string" ? route.query.max : "",
);

const keyword = ref("");
const minPrice = ref("");
const maxPrice = ref("");
const selectedCategories = ref<string[]>([]);
const filterError = ref("");

const categories = useAsyncData(listCategories);
const filterableCategories = computed(() =>
  (categories.data.value?.items ?? []).filter(
    (category) => category.has_public_products || category.selectable,
  ),
);
const categoryFilters = computed(() => categoryFilterOptions(filterableCategories.value));
const hasAdvancedFilters = computed(
  () => selectedCategories.value.length > 0 || minPrice.value !== "" || maxPrice.value !== "",
);

const list = usePagedList<ProductSummary>((page, pageSize, signal) => {
  const minimum = parseYuanToCents(appliedMinPrice.value);
  const maximum = parseYuanToCents(appliedMaxPrice.value);
  return searchProducts(
    {
      keyword: appliedKeyword.value || undefined,
      category_ids: appliedCategories.value.length ? appliedCategories.value : undefined,
      min_price_cents: minimum ?? undefined,
      max_price_cents: maximum ?? undefined,
      page,
      page_size: pageSize,
    },
    signal,
  );
});

watch(
  () => route.fullPath,
  () => {
    if (route.name !== "home" && route.name !== "product-search") return;
    keyword.value = appliedKeyword.value;
    selectedCategories.value = [...appliedCategories.value];
    minPrice.value = appliedMinPrice.value;
    maxPrice.value = appliedMaxPrice.value;
    filterError.value = "";
    void list.load(1);
    if (searching.value && categories.state.value === "idle") void categories.run();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  list.cancel();
  categories.cancel();
});

function openSearch(query: LocationQueryRaw): void {
  void router.push({ name: "product-search", query });
}

function submitSearch(): void {
  openSearch({
    q: keyword.value.trim() || undefined,
    category: appliedCategories.value,
    min: appliedMinPrice.value || undefined,
    max: appliedMaxPrice.value || undefined,
  });
}

function applyFilters(): void {
  filterError.value = "";
  const min = minPrice.value.trim();
  const max = maxPrice.value.trim();
  const minimum = parseYuanToCents(min);
  const maximum = parseYuanToCents(max);
  if (min && minimum === null) {
    filterError.value = "最低价需填写为数字，例如 20 或 20.50。";
    return;
  }
  if (max && maximum === null) {
    filterError.value = "最高价需填写为数字，例如 200 或 200.50。";
    return;
  }
  if (minimum !== null && maximum !== null && minimum > maximum) {
    filterError.value = "最低价不能高于最高价。";
    return;
  }
  openSearch({
    q: appliedKeyword.value || undefined,
    category: [...selectedCategories.value],
    min: min || undefined,
    max: max || undefined,
  });
}

function resetFilters(): void {
  filterError.value = "";
  selectedCategories.value = [];
  minPrice.value = "";
  maxPrice.value = "";
  openSearch({ q: appliedKeyword.value || undefined });
}

function toggleCategory(id: string): void {
  selectedCategories.value = selectedCategories.value.includes(id)
    ? selectedCategories.value.filter((value) => value !== id)
    : [...selectedCategories.value, id];
}
</script>

<template>
  <div class="stack stack--loose">
    <h1 class="visually-hidden">{{ searching ? "搜索结果" : "校园二手" }}</h1>
    <form class="catalogue-search" role="search" @submit.prevent="submitSearch">
      <label for="keyword" class="catalogue-search__field">
        <span class="visually-hidden">搜索商品</span>
        <input
          id="keyword"
          v-model="keyword"
          name="q"
          type="search"
          enterkeyhint="search"
          placeholder="搜索商品标题或描述"
        />
      </label>
      <button type="submit" class="btn btn--primary">
        <UiIcon name="search" />
        搜索
      </button>
    </form>

    <section v-if="searching" class="filters card" aria-labelledby="search-filter-title">
      <h2 id="search-filter-title">筛选</h2>
      <form class="stack" @submit.prevent="applyFilters">
        <div class="filters__prices">
          <div class="field">
            <label class="field__label" for="min-price">最低价（元）</label>
            <input id="min-price" v-model="minPrice" class="input" inputmode="decimal" />
          </div>
          <div class="field">
            <label class="field__label" for="max-price">最高价（元）</label>
            <input id="max-price" v-model="maxPrice" class="input" inputmode="decimal" />
          </div>
        </div>

        <ErrorNotice
          v-if="categories.problem.value"
          :error="categories.error.value"
          @retry="categories.run"
        />
        <fieldset v-else-if="filterableCategories.length" class="filters__categories">
          <legend class="field__label">分类</legend>
          <div class="inline">
            <button
              v-for="category in categoryFilters"
              :key="category.id"
              type="button"
              class="chip chip--action"
              :class="{ 'chip--active': selectedCategories.includes(category.id) }"
              :aria-pressed="selectedCategories.includes(category.id)"
              @click="toggleCategory(category.id)"
            >
              {{ category.label }}
            </button>
          </div>
        </fieldset>
        <p v-if="filterError" class="field__error" role="alert">{{ filterError }}</p>
        <div class="inline">
          <button type="submit" class="btn btn--primary"><UiIcon name="filter" />应用筛选</button>
          <button
            type="button"
            class="btn btn--ghost"
            :disabled="!hasAdvancedFilters"
            @click="resetFilters"
          >
            <UiIcon name="reset" />清除筛选
          </button>
        </div>
      </form>
    </section>

    <LoadingBlock v-if="list.isLoading.value" label="正在加载商品…" />
    <ErrorNotice
      v-else-if="list.problem.value"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <EmptyState
      v-else-if="list.isEmpty.value"
      :title="searching ? '没有符合条件的商品' : '暂时没有在售商品'"
      :description="searching ? '可以换个关键词，或调整筛选条件。' : undefined"
    />
    <template v-else>
      <ul class="product-grid" aria-label="在售商品">
        <li v-for="product in list.items.value" :key="product.id">
          <RouterLink
            :to="{ name: 'product-detail', params: { productId: product.id } }"
            class="product-card"
          >
            <div class="product-card__media">
              <img v-if="product.thumbnail" :src="product.thumbnail.url" alt="" loading="lazy" />
              <span v-else class="product-card__placeholder">
                <UiIcon name="box" />
                暂无图片
              </span>
            </div>
            <div class="product-card__body">
              <h2 class="product-card__title clamp-2">{{ product.title }}</h2>
              <p class="product-card__price amount">{{ formatCents(product.price_cents) }}</p>
              <p class="product-card__meta muted">
                <span>{{ product.seller.display_name }}</span>
                <span aria-hidden="true">·</span>
                <span>{{ formatRelative(product.created_at) }}</span>
              </p>
              <p v-if="product.categories.length" class="inline product-card__tags">
                <span v-for="category in product.categories" :key="category.id" class="tag">{{
                  category.name
                }}</span>
              </p>
            </div>
          </RouterLink>
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
.catalogue-search {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  inline-size: 100%;
  padding: var(--space-1);
  border: 1px solid var(--control-line);
  border-radius: var(--radius);
  background: var(--panel);
}

.catalogue-search:focus-within {
  border-color: var(--brand);
}

.catalogue-search__field {
  flex: 1;
  min-inline-size: 0;
  padding-inline: var(--space-3);
  cursor: text;
}

.catalogue-search input {
  display: block;
  inline-size: 100%;
  min-block-size: var(--control-min-block);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink);
  font: inherit;
}

.catalogue-search:has(input:focus-visible) {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.catalogue-search input:focus-visible {
  outline: none;
}

.catalogue-search button {
  flex: 0 0 auto;
  padding-inline: var(--space-3);
}

.filters h2 {
  margin-block-end: var(--space-3);
  font-size: 1rem;
}

.filters__prices {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  max-inline-size: 24rem;
}

.filters__categories {
  min-inline-size: 0;
  border: 0;
  margin: 0;
  padding: 0;
}

.filters__categories legend {
  margin-block-end: var(--space-1);
  padding: 0;
}

.filters__categories .chip {
  min-block-size: var(--control-min-block);
  padding-inline: var(--space-3);
  border-radius: var(--radius-sm);
  font-size: 0.8125rem;
}

.product-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.product-card {
  display: grid;
  grid-template-rows: auto 1fr;
  block-size: 100%;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  color: var(--ink);
}

.product-card:hover {
  border-color: var(--brand);
  text-decoration: none;
}

.product-card:hover .product-card__title {
  text-decoration: underline;
}

.product-card__media {
  display: grid;
  place-items: center;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--panel-soft);
}

.product-card__media img {
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}

.product-card__placeholder {
  display: grid;
  justify-items: center;
  gap: var(--space-1);
  font-size: 0.75rem;
  color: var(--ink-faint);
}

.product-card__body {
  display: grid;
  align-content: start;
  gap: var(--space-1);
  min-inline-size: 0;
  padding: var(--space-3);
}

.product-card__title {
  font-size: 0.9375rem;
  overflow-wrap: anywhere;
}

.product-card__price {
  color: var(--accent);
}

.product-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--space-1);
  overflow-wrap: anywhere;
}

.product-card__tags {
  margin-block-start: var(--space-1);
}

@media (width >= 40rem) {
  .product-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (width >= 62rem) {
  .product-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
