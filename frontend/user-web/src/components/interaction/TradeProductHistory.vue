<script setup lang="ts">
/*
 * Lazy, paged product history scoped to one trade.
 *
 * A trade participant may read only the projection the endpoint permits. The
 * first page is requested when the disclosure opens; a permission failure is
 * shown as an error instead of being mistaken for an empty history.
 */
import { ref } from "vue";
import { listEditHistory } from "../../api/products";
import type { ProductEditSnapshot } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { productEditChanges } from "../../app/product-edit-changes";
import EmptyState from "../EmptyState.vue";
import ErrorNotice from "../ErrorNotice.vue";
import LoadingBlock from "../LoadingBlock.vue";
import PaginationBar from "../PaginationBar.vue";

const props = defineProps<{ productId: string; tradeId: string }>();

const opened = ref(false);
const loaded = ref(false);

const history = usePagedList<ProductEditSnapshot>((page, pageSize, signal) =>
  listEditHistory(props.productId, page, pageSize, props.tradeId, signal),
);

function onToggle(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLDetailsElement) || !target.open) return;
  opened.value = true;
  if (loaded.value) return;
  loaded.value = true;
  void history.load(1);
}

function operatorLabel(kind: string): string {
  if (kind === "seller") return "卖家";
  if (kind === "manager") return "管理员";
  return kind || "系统";
}
</script>

<template>
  <details class="card history" @toggle="onToggle">
    <summary>商品历史</summary>
    <p class="muted history__note">只显示本商品在此交易中可查看的标题、描述与价格变化。</p>

    <LoadingBlock
      v-if="opened && history.isLoading.value && !history.items.value.length"
      label="正在加载商品历史…"
    />
    <ErrorNotice
      v-else-if="history.problem.value"
      :error="history.error.value"
      @retry="history.load(history.paging.page)"
    />
    <EmptyState
      v-else-if="history.state.value === 'ready' && !history.items.value.length"
      title="没有商品变更记录"
      description="该商品在此交易前没有可查看的编辑记录。"
    />
    <template v-else-if="history.items.value.length">
      <ol class="history__list" :aria-busy="history.isLoading.value">
        <li v-for="snapshot in history.items.value" :key="snapshot.edit_id" class="snapshot">
          <div class="snapshot__head">
            <span class="chip">{{ operatorLabel(snapshot.operator_kind) }}</span>
            <span class="muted">{{ formatDateTime(snapshot.edited_at) }}</span>
          </div>
          <dl
            v-if="productEditChanges(snapshot.before_content, snapshot.after_content).length"
            class="facts"
          >
            <template
              v-for="change in productEditChanges(snapshot.before_content, snapshot.after_content)"
              :key="change.key"
            >
              <dt>{{ change.label }}</dt>
              <dd class="snapshot__change">
                <span class="snapshot__before">{{ change.before }}</span>
                <span aria-hidden="true">→</span>
                <span>{{ change.after }}</span>
              </dd>
            </template>
          </dl>
          <p v-else class="muted">本次记录没有标题、描述或价格变化。</p>
          <p v-if="snapshot.reason" class="muted break-anywhere">原因：{{ snapshot.reason }}</p>
        </li>
      </ol>
      <PaginationBar
        :page="history.paging.page"
        :page-size="history.paging.pageSize"
        :total="history.paging.total"
        @change="history.load"
      />
    </template>
  </details>
</template>

<style scoped>
.history summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9375rem;
}

.history__note {
  margin-block-start: var(--space-2);
  font-size: 0.8125rem;
}

.history__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-block-start: var(--space-3);
  padding: 0;
  list-style: none;
}

.snapshot {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
}

.snapshot__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  justify-content: space-between;
  flex-wrap: wrap;
  font-size: 0.75rem;
}

.facts {
  display: grid;
  grid-template-columns: minmax(4.5rem, auto) minmax(0, 1fr);
  gap: var(--space-2) var(--space-3);
  margin: 0;
  font-size: 0.8125rem;
}

.facts dt {
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.snapshot__change {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.snapshot__before {
  color: var(--ink-faint);
  text-decoration: line-through;
}
</style>
