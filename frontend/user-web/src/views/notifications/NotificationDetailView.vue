<script setup lang="ts">
/*
 * One notification. Opening the detail is what records the first read; the source
 * object still needs its own permission check, so the jump link is only a hint.
 */
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { getNotification, markNotificationRead } from "../../api/notifications";
import type { NotificationDetail } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { newIdempotencyKey } from "../../app/keys";
import { notificationTypeLabel } from "../../app/labels";
import { refreshesNotificationDetail } from "../../app/notification-events";
import { problemMessage } from "../../app/problems";
import { registerSnapshotReloader, subscribeRealtime } from "../../app/realtime";
import { refreshBadges } from "../../app/badges";
import { notify } from "../../app/toast";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";

const route = useRoute();
const notificationId = computed(() => String(route.params.notificationId ?? ""));
const notification = useAsyncData<NotificationDetail>((signal) =>
  getNotification(notificationId.value, signal),
);

let readAttemptedFor: string | null = null;
let markingRead = false;
let unsubscribe: (() => void) | undefined;
let unregisterReloader: (() => void) | undefined;

const sourceLink = computed(() => {
  const source = notification.data.value?.source;
  if (!source) return null;
  switch (source.resource_type) {
    case "product":
      return {
        name: "product-detail",
        params: { productId: source.resource_id },
        hash: notification.data.value?.comment_id
          ? `#comment-${notification.data.value.comment_id}`
          : undefined,
      };
    case "trade":
      return { name: "trade-detail", params: { tradeId: source.resource_id } };
    case "case":
      return { name: "case-detail", params: { caseId: source.resource_id } };
    default:
      return null;
  }
});

const sourceLabel = computed(() => {
  if (notification.data.value?.comment_id) {
    return notification.data.value.event_type === "product_comment.replied"
      ? "查看回复"
      : "查看评论";
  }
  const type = notification.data.value?.source?.resource_type;
  if (type === "product") return "查看商品";
  if (type === "trade") return "查看交易";
  if (type === "case") return "查看事项";
  return "";
});

/**
 * Reload the detail without repeating the read write.
 *
 * Realtime replay and the sync snapshot both use this path, so only the initial
 * open (or an explicit retry) is allowed to send `PUT .../read`.
 */
async function refreshDetail(): Promise<void> {
  await notification.run();
}

async function loadNotification(markRead: boolean): Promise<void> {
  await notification.run();
  const data = notification.data.value;
  if (!markRead || markingRead || !notification.isReady.value || !data || data.read_at) return;
  if (readAttemptedFor === data.notification_id) return;
  readAttemptedFor = data.notification_id;
  markingRead = true;
  try {
    const { read_at } = await markNotificationRead(data.notification_id, newIdempotencyKey());
    if (notification.data.value === data) notification.data.value = { ...data, read_at };
    void refreshBadges();
  } catch (caught) {
    // Recording the read is a side effect; failing it must not hide the content.
    notify.warn(problemMessage(caught));
  } finally {
    markingRead = false;
  }
}

function retryLoad(): void {
  readAttemptedFor = null;
  void loadNotification(true);
}

function onRealtimeFrame(frame: Parameters<typeof refreshesNotificationDetail>[0]): void {
  if (refreshesNotificationDetail(frame, notificationId.value)) void refreshDetail();
}

watch(notificationId, () => {
  readAttemptedFor = null;
  notification.cancel();
  notification.data.value = null;
  void loadNotification(true);
});

onMounted(() => {
  void loadNotification(true);
  unregisterReloader = registerSnapshotReloader(() => refreshDetail());
  unsubscribe = subscribeRealtime(onRealtimeFrame);
});

onBeforeUnmount(() => {
  unsubscribe?.();
  unregisterReloader?.();
  notification.cancel();
});
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader eyebrow="通知" :title="notification.data.value?.summary ?? '通知详情'">
      <template #actions>
        <RouterLink to="/me/notifications" class="btn btn--ghost">返回通知列表</RouterLink>
      </template>
    </PageHeader>

    <LoadingBlock
      v-if="notification.isLoading.value && !notification.data.value"
      label="正在加载通知…"
    />
    <ErrorNotice
      v-else-if="notification.problem.value && !notification.data.value"
      :error="notification.error.value"
      @retry="retryLoad"
    />
    <article v-else-if="notification.data.value" class="card stack">
      <p v-if="notification.problem.value" class="banner banner--warn" role="alert">
        刷新通知失败：{{ notification.problem.value.message }}
        <button type="button" class="btn btn--small" @click="refreshDetail">重试</button>
      </p>
      <div class="inline">
        <span class="chip">{{ notificationTypeLabel(notification.data.value.event_type) }}</span>
        <time class="muted" :datetime="notification.data.value.occurred_at">
          {{ formatDateTime(notification.data.value.occurred_at) }}
        </time>
      </div>
      <dl
        v-if="
          notification.data.value.subject ||
          notification.data.value.source?.resource_type === 'trade'
        "
        class="context"
      >
        <div v-if="notification.data.value.subject">
          <dt>关联商品</dt>
          <dd class="break-anywhere">{{ notification.data.value.subject }}</dd>
        </div>
        <div v-if="notification.data.value.source?.resource_type === 'trade'">
          <dt>交易编号</dt>
          <dd>#{{ notification.data.value.source.resource_id }}</dd>
        </div>
      </dl>
      <p v-if="notification.data.value.body" class="body pre-line break-anywhere">
        {{ notification.data.value.body }}
      </p>
      <div v-if="sourceLink" class="inline">
        <RouterLink :to="sourceLink" class="btn btn--primary">{{ sourceLabel }}</RouterLink>
      </div>
      <p v-if="notification.data.value.read_at" class="muted read-time">
        首次已读
        <time :datetime="notification.data.value.read_at">
          {{ formatDateTime(notification.data.value.read_at) }}
        </time>
      </p>
    </article>
  </div>
</template>

<style scoped>
.context {
  display: grid;
  gap: var(--space-2);
  padding-block-end: var(--space-3);
  border-block-end: 1px solid var(--line);
}

.context > div {
  display: grid;
  grid-template-columns: 5em minmax(0, 1fr);
  gap: var(--space-2);
}

.context dt {
  color: var(--ink-faint);
}

.context dd {
  margin: 0;
}

.body {
  line-height: 1.7;
}

.read-time {
  font-size: 0.8125rem;
}
</style>
