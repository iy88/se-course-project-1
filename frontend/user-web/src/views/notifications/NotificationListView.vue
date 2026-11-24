<script setup lang="ts">
/*
 * Notification centre (US-11).
 *
 * Reading the list never marks anything as read; the detail screen records the
 * first read, which matches the contract rule that only opening a concrete
 * notification advances the read state.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listNotifications } from "../../api/notifications";
import type { NotificationReadFilter, NotificationSummary } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatDateTime, formatRelative } from "../../app/format";
import { notificationReadLabels, notificationTypeLabel } from "../../app/labels";
import { refreshBadges } from "../../app/badges";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";

const router = useRouter();
const filter = ref<NotificationReadFilter>("all");

const list = usePagedList<NotificationSummary>((page, pageSize, signal) =>
  listNotifications({ page, page_size: pageSize, read: filter.value }, signal),
);

const unreadCount = computed(() => {
  const data = list.items.value;
  const locallyUnread = data.filter((item) => !item.read_at).length;
  return filter.value === "unread" ? list.paging.total : locallyUnread;
});

const filters: NotificationReadFilter[] = ["all", "unread", "read"];

onMounted(() => {
  void list.load(1);
});

function selectFilter(next: NotificationReadFilter): void {
  filter.value = next;
  void list.load(1);
}

function open(item: NotificationSummary): void {
  void router.push({
    name: "notification-detail",
    params: { notificationId: item.notification_id },
  });
}

async function reload(): Promise<void> {
  await list.load(list.paging.page);
  void refreshBadges();
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="消息"
      title="通知"
      description="审核结果、交易进展与事项提醒都会在这里留下记录。"
    >
      <template #actions>
        <span v-if="unreadCount > 0" class="chip chip--active">{{ unreadCount }} 条未读</span>
        <RouterLink to="/conversations" class="btn btn--ghost">去消息列表</RouterLink>
      </template>
    </PageHeader>

    <div class="inline">
      <button
        v-for="option in filters"
        :key="option"
        type="button"
        class="chip chip--action"
        :class="{ 'chip--active': filter === option }"
        @click="selectFilter(option)"
      >
        {{ notificationReadLabels[option] }}
      </button>
    </div>

    <LoadingBlock v-if="list.isLoading.value" label="正在加载通知…" />
    <ErrorNotice v-else-if="list.problem.value" :error="list.error.value" @retry="reload" />
    <EmptyState
      v-else-if="list.isEmpty.value"
      :title="filter === 'unread' ? '没有未读通知' : '暂无通知'"
      description="有新的审核结果或交易进展时会在这里显示。"
    />
    <template v-else>
      <ul class="rows">
        <li v-for="item in list.items.value" :key="item.notification_id">
          <button
            type="button"
            class="row"
            :class="{ 'row--unread': !item.read_at }"
            @click="open(item)"
          >
            <span class="row__main">
              <span class="inline">
                <span class="chip">{{ notificationTypeLabel(item.event_type) }}</span>
                <span v-if="!item.read_at" class="dot" aria-label="未读" />
              </span>
              <span class="row__summary">{{ item.summary }}</span>
              <span class="muted" :title="formatDateTime(item.occurred_at)">
                {{ formatRelative(item.occurred_at) }}
              </span>
            </span>
            <span class="row__go" aria-hidden="true">›</span>
          </button>
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
.rows {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  inline-size: 100%;
  padding: var(--space-3) var(--space-4);
  text-align: start;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
}

.row:hover {
  border-color: var(--brand);
}

.row--unread {
  background: #fcfdfb;
  border-inline-start: 3px solid var(--brand);
}

.row__main {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-inline-size: 0;
  flex: 1;
}

.row__summary {
  font-size: 0.875rem;
}

.row__go {
  color: var(--ink-faint);
}

.dot {
  inline-size: 0.4375rem;
  block-size: 0.4375rem;
  border-radius: 50%;
  background: var(--danger);
}
</style>
