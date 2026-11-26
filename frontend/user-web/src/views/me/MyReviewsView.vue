<script setup lang="ts">
/*
 * My reviews in both directions.
 *
 * The list endpoint returns only the signed-in account's own reviews; the
 * direction toggle is a server filter, not a client-side guess.
 */
import { onMounted, ref } from "vue";
import { listMyReviews } from "../../api/trades";
import type { TradeReview } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { session } from "../../app/session";
import AvatarBadge from "../../components/AvatarBadge.vue";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";

type Direction = "written" | "received";

const direction = ref<Direction>("written");
const directions: { value: Direction; label: string }[] = [
  { value: "written", label: "我写的评价" },
  { value: "received", label: "我收到的评价" },
];

const list = usePagedList<TradeReview>((page, pageSize, signal) =>
  listMyReviews(direction.value, page, pageSize, signal),
);

onMounted(() => {
  void list.load(1);
});

function selectDirection(next: Direction): void {
  if (direction.value === next) return;
  direction.value = next;
  void list.load(1);
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="我的"
      title="我的评价"
      description="查看你写出的评价和收到的评价；同一笔交易的双方各可评价一次。"
    >
      <template #actions>
        <RouterLink to="/me/trades" class="btn btn--ghost">我的交易</RouterLink>
      </template>
    </PageHeader>

    <div class="status-filter review-filters" role="group" aria-label="评价方向">
      <button
        v-for="option in directions"
        :key="option.value"
        type="button"
        class="status-filter__option"
        :aria-pressed="direction === option.value"
        @click="selectDirection(option.value)"
      >
        {{ option.label }}
      </button>
    </div>

    <LoadingBlock v-if="list.isLoading.value && !list.items.value.length" label="正在加载评价…" />
    <ErrorNotice
      v-else-if="list.problem.value && !list.items.value.length"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <EmptyState
      v-else-if="list.isEmpty.value"
      :title="direction === 'written' ? '还没有写过评价' : '还没有收到评价'"
      :description="
        direction === 'written'
          ? '交易完成后可在交易详情中评价对方。'
          : '对方在交易完成后提交的评价会显示在这里。'
      "
    >
      <RouterLink to="/me/trades" class="btn btn--primary">查看我的交易</RouterLink>
    </EmptyState>
    <template v-else>
      <p v-if="list.problem.value" class="banner banner--warn" role="alert">
        刷新评价失败：{{ list.problem.value.message }}
        <button type="button" class="btn btn--small" @click="list.load(list.paging.page)">
          重试
        </button>
      </p>
      <ul class="reviews" :aria-busy="list.isLoading.value">
        <li v-for="item in list.items.value" :key="item.review_id" class="review card">
          <div class="review__head">
            <AvatarBadge
              :display-name="item.reviewer.display_name"
              :url="item.reviewer.avatar_url"
              size="sm"
            />
            <div class="review__people">
              <strong>{{ item.reviewer.display_name }}</strong>
              <span class="muted">评价 {{ item.reviewee.display_name }}</span>
            </div>
            <span class="chip">{{ direction === "written" ? "我写的" : "我收到的" }}</span>
            <span class="review__rating">评分 {{ item.rating }}/5</span>
          </div>
          <p v-if="item.content" class="review__body pre-line break-anywhere">
            {{ item.content }}
          </p>
          <div class="review__foot">
            <time class="muted" :datetime="item.created_at">
              {{ formatDateTime(item.created_at) }}
            </time>
            <RouterLink
              :to="{ name: 'trade-detail', params: { tradeId: item.trade_id } }"
              class="btn btn--small"
            >
              查看交易
            </RouterLink>
            <RouterLink
              v-if="
                direction === 'received' &&
                item.visible &&
                item.reviewee.id === session.accountId.value
              "
              :to="{
                name: 'report',
                query: { target_type: 'evaluation', target_id: item.review_id },
              }"
              class="btn btn--small btn--ghost"
            >
              举报评价
            </RouterLink>
          </div>
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
.review-filters {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  max-inline-size: 28rem;
}

.reviews {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.review {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.review__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.review__people {
  display: grid;
  gap: 0.0625rem;
  min-inline-size: 0;
  font-size: 0.875rem;
}

.review__people .muted {
  font-size: 0.75rem;
}

.review__head .chip {
  margin-inline-start: auto;
}

.review__rating {
  color: var(--accent);
  font-size: 0.8125rem;
  font-weight: 650;
}

.review__body {
  margin: 0;
  color: var(--ink-soft);
}

.review__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: 0.75rem;
}
</style>
