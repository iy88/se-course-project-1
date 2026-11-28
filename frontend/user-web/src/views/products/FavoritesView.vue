<script setup lang="ts">
/*
 * Personal favourites (API-PRD-028).
 *
 * The server marks an item valid only while the product is publicly visible.
 * Invalid items keep the product identifier and a neutral "expired" message,
 * never the title, image, seller or category, so this page cannot leak a
 * product that is no longer visible.
 */
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { listMyFavorites, removeFavorite } from "../../api/products";
import type { FavoriteItem } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatCents, formatRelative } from "../../app/format";
import { IdempotencyKeys } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { useToastStore } from "../../app/toast";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";

const { notify } = useToastStore();

const favorites = usePagedList<FavoriteItem>((page, pageSize, signal) =>
  listMyFavorites({ page, page_size: pageSize }, signal),
);
const keys = new IdempotencyKeys();
const removing = ref<string | null>(null);

function load(): void {
  void favorites.load();
}

onMounted(load);

async function remove(item: FavoriteItem): Promise<void> {
  if (removing.value) return;
  removing.value = item.product_id;
  const operation = `favorite-remove-${item.product_id}`;
  try {
    await removeFavorite(item.product_id, keys.current(operation));
    keys.rotate(operation);
    notify.info("已取消收藏。");
    await favorites.load();
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    removing.value = null;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      title="我的收藏"
      description="商品下架后仍会保留在这里；重新公开后自动恢复有效，失效商品可随时清理。"
    >
      <template #actions>
        <RouterLink to="/" class="btn btn--ghost">返回逛逛</RouterLink>
      </template>
    </PageHeader>

    <LoadingBlock
      v-if="favorites.isLoading.value && !favorites.items.value.length"
      label="正在加载收藏…"
    />
    <ErrorNotice v-else-if="favorites.problem.value" :error="favorites.error.value" @retry="load" />
    <EmptyState
      v-else-if="favorites.isEmpty.value"
      title="还没有收藏"
      description="在商品详情页点击收藏，之后可以从这里快速找到它。"
    >
      <RouterLink to="/" class="btn btn--primary">去逛逛</RouterLink>
    </EmptyState>
    <template v-else>
      <ul class="favorite-grid">
        <li v-for="item in favorites.items.value" :key="item.product_id" class="favorite">
          <template v-if="item.status === 'valid' && item.product">
            <RouterLink
              :to="{ name: 'product-detail', params: { productId: item.product_id } }"
              class="favorite__link"
            >
              <span class="favorite__title">{{ item.product.title }}</span>
              <span class="favorite__price amount">{{
                formatCents(item.product.price_cents)
              }}</span>
              <span class="favorite__meta muted">
                {{ item.product.seller.display_name }}
                <template v-if="item.product.categories.length">
                  · {{ item.product.categories.map((category) => category.name).join(" / ") }}
                </template>
              </span>
              <span class="favorite__meta muted"
                >收藏于 {{ formatRelative(item.favorited_at) }}</span
              >
            </RouterLink>
          </template>
          <div v-else class="favorite__link favorite__link--invalid">
            <span class="favorite__title">该商品已失效</span>
            <span class="favorite__meta muted">
              {{ item.message ?? "商品当前不可见" }} · 收藏于
              {{ formatRelative(item.favorited_at) }}
            </span>
          </div>
          <button
            type="button"
            class="btn btn--small btn--ghost"
            :disabled="removing === item.product_id"
            @click="remove(item)"
          >
            取消收藏
          </button>
        </li>
      </ul>

      <PaginationBar
        :page="favorites.paging.page"
        :page-size="favorites.paging.pageSize"
        :total="favorites.paging.total"
        @change="favorites.load"
      />
    </template>
  </div>
</template>

<style scoped>
.favorite-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.favorite {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.favorite__link {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.25rem;
  color: var(--ink);
}

.favorite__link:hover {
  text-decoration: none;
  color: var(--brand-ink);
}

.favorite__link--invalid {
  justify-content: center;
  border: 1px dashed var(--line);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  color: var(--ink-faint);
}

.favorite__title {
  font-weight: 600;
}

.favorite__price {
  color: var(--accent);
}

.favorite__meta {
  font-size: 0.8125rem;
}
</style>
