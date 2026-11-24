<script setup lang="ts">
/*
 * One notification. Opening the detail is what records the first read; the source
 * object still needs its own permission check, so the jump link is only a hint.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getNotification, markNotificationRead } from "../../api/notifications";
import type { NotificationSummary } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { newIdempotencyKey } from "../../app/keys";
import { notificationTypeLabel } from "../../app/labels";
import { problemMessage } from "../../app/problems";
import { refreshBadges } from "../../app/badges";
import { notify } from "../../app/toast";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";

const route = useRoute();
const notificationId = computed(() => String(route.params.notificationId ?? ""));
const notification = useAsyncData<NotificationSummary>((signal) =>
  getNotification(notificationId.value, signal),
);

const sourceLink = computed(() => {
  const source = notification.data.value?.source;
  if (!source) return null;
  switch (source.resource_type) {
    case "product":
      return { name: "product-detail", params: { productId: source.resource_id } };
    case "trade":
      return { name: "trade-detail", params: { tradeId: source.resource_id } };
    case "case":
      return { name: "case-detail", params: { caseId: source.resource_id } };
    default:
      return null;
  }
});

const sourceLabel = computed(() => {
  const type = notification.data.value?.source?.resource_type;
  if (type === "product") return "查看商品";
  if (type === "trade") return "查看交易";
  if (type === "case") return "查看事项";
  return "";
});

const readRecorded = ref(false);

onMounted(async () => {
  await notification.run();
  const data = notification.data.value;
  if (!data || readRecorded.value) return;
  readRecorded.value = true;
  try {
    await markNotificationRead(data.notification_id, newIdempotencyKey());
    void refreshBadges();
  } catch (caught) {
    // Recording the read is a side effect; failing it must not hide the content.
    notify.warn(problemMessage(caught));
  }
});
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader eyebrow="通知" title="通知详情">
      <template #actions>
        <RouterLink to="/me/notifications" class="btn btn--ghost">返回通知列表</RouterLink>
      </template>
    </PageHeader>

    <LoadingBlock v-if="notification.isLoading.value" label="正在加载通知…" />
    <ErrorNotice
      v-else-if="notification.problem.value"
      :error="notification.error.value"
      @retry="notification.run"
    />
    <section v-else-if="notification.data.value" class="card stack">
      <div class="inline">
        <span class="chip">{{ notificationTypeLabel(notification.data.value.event_type) }}</span>
        <span class="muted">发生于 {{ formatDateTime(notification.data.value.occurred_at) }}</span>
      </div>
      <p class="body break-anywhere">{{ notification.data.value.summary }}</p>
      <p class="muted">首次已读：{{ formatDateTime(notification.data.value.read_at) }}</p>
      <p v-if="!notification.data.value.source" class="banner banner--info">
        该通知关联的来源当前不可见，因此不提供跳转。
      </p>
      <div v-else-if="sourceLink" class="inline">
        <RouterLink :to="sourceLink" class="btn btn--primary">{{ sourceLabel }}</RouterLink>
      </div>
    </section>
  </div>
</template>

<style scoped>
.body {
  font-size: 0.9375rem;
  line-height: 1.7;
}
</style>
