<script setup lang="ts">
/*
 * Notification centre (US-11).
 *
 * Reading the list never marks anything as read; the detail screen records the
 * first read, which matches the contract rule that only opening a concrete
 * notification advances the read state.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { listNotifications } from "../../api/notifications";
import type { NotificationReadFilter, NotificationSummary } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { notificationReadLabels, notificationTypeLabel } from "../../app/labels";
import { refreshesNotificationList } from "../../app/notification-events";
import { registerSnapshotReloader, subscribeRealtime } from "../../app/realtime";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";

const filter = ref<NotificationReadFilter>("all");
const unreadCount = ref(0);

const list = usePagedList<NotificationSummary>(async (page, pageSize, signal) => {
  const result = await listNotifications({ page, page_size: pageSize, read: filter.value }, signal);
  if (!signal.aborted) unreadCount.value = result.unread_count;
  return result;
}, 10);

const filters: NotificationReadFilter[] = ["all", "unread", "read"];
let requestedPage = 1;
let loading = false;
let pending = false;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;
let unsubscribe: (() => void) | undefined;
let unregisterReloader: (() => void) | undefined;

/**
 * Serialise refreshes for the current filter/page.
 *
 * A notification event may arrive while the user is also paging; both intents
 * collapse into the newest requested page instead of aborting each other. The
 * list keeps its existing rows until the replacement page arrives.
 */
async function refreshPage(page = list.paging.page): Promise<void> {
  requestedPage = page;
  if (loading) {
    pending = true;
    return;
  }
  loading = true;
  try {
    do {
      pending = false;
      await list.load(requestedPage);
      if (!pending && list.state.value === "ready" && list.paging.page > list.totalPages.value) {
        requestedPage = list.totalPages.value;
        pending = true;
      }
    } while (pending);
  } finally {
    loading = false;
  }
}

function scheduleRefresh(): void {
  if (refreshTimer !== undefined) return;
  refreshTimer = setTimeout(() => {
    refreshTimer = undefined;
    void refreshPage();
  }, 80);
}

onMounted(() => {
  void refreshPage(1);
  unregisterReloader = registerSnapshotReloader(() => refreshPage());
  unsubscribe = subscribeRealtime((frame) => {
    if (refreshesNotificationList(frame)) scheduleRefresh();
  });
});

onBeforeUnmount(() => {
  unsubscribe?.();
  unregisterReloader?.();
  clearTimeout(refreshTimer);
  refreshTimer = undefined;
  pending = false;
  list.cancel();
});

function selectFilter(next: NotificationReadFilter): void {
  if (filter.value === next) return;
  filter.value = next;
  void refreshPage(1);
}

async function reload(): Promise<void> {
  await refreshPage(list.paging.page);
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader title="通知">
      <template #actions>
        <span v-if="unreadCount > 0" class="chip chip--active">{{ unreadCount }} 条未读</span>
      </template>
    </PageHeader>

    <div class="status-filter notification-filters" role="group" aria-label="按已读状态筛选">
      <button
        v-for="option in filters"
        :key="option"
        type="button"
        class="status-filter__option"
        :aria-pressed="filter === option"
        @click="selectFilter(option)"
      >
        {{ notificationReadLabels[option] }}
      </button>
    </div>

    <LoadingBlock v-if="list.isLoading.value && !list.items.value.length" label="正在加载通知…" />
    <ErrorNotice
      v-else-if="list.problem.value && !list.items.value.length"
      :error="list.error.value"
      @retry="reload"
    />
    <EmptyState
      v-else-if="list.isEmpty.value && !list.problem.value"
      :title="filter === 'unread' ? '没有未读通知' : '暂无通知'"
    />
    <template v-else>
      <p v-if="list.problem.value" class="banner banner--warn" role="alert">
        刷新通知失败：{{ list.problem.value.message }}
        <button type="button" class="btn btn--small" @click="reload">重试</button>
      </p>
      <ul class="rows" :aria-busy="list.isLoading.value">
        <li v-for="item in list.items.value" :key="item.notification_id">
          <RouterLink
            :to="{ name: 'notification-detail', params: { notificationId: item.notification_id } }"
            class="row"
            :class="{ 'row--unread': !item.read_at }"
          >
            <span class="row__main">
              <span class="row__meta">
                <span class="row__type">{{ notificationTypeLabel(item.event_type) }}</span>
                <strong class="row__summary break-anywhere">{{ item.summary }}</strong>
                <span v-if="!item.read_at" class="row__unread">未读</span>
                <time class="row__time muted" :datetime="item.occurred_at">
                  {{ formatDateTime(item.occurred_at) }}
                </time>
              </span>
              <span
                v-if="item.subject || item.source?.resource_type === 'trade'"
                class="row__details muted"
              >
                <span v-if="item.subject" class="break-anywhere">
                  <template v-if="['product', 'trade'].includes(item.source?.resource_type ?? '')">
                    商品名称
                  </template>
                  {{ item.subject }}
                </span>
                <span v-if="item.source?.resource_type === 'trade'" class="row__trade">
                  交易编号 #{{ item.source.resource_id }}
                </span>
              </span>
            </span>
            <span class="row__go" aria-hidden="true">›</span>
          </RouterLink>
        </li>
      </ul>
      <PaginationBar
        :page="list.paging.page"
        :page-size="list.paging.pageSize"
        :total="list.paging.total"
        show-single-page
        @change="refreshPage"
      />
    </template>
  </div>
</template>

<style scoped src="../../../../shared/notification-list.css"></style>
