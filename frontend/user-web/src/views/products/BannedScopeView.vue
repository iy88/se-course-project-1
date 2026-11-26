<script setup lang="ts">
/*
 * Read-only banned scope.
 *
 * Any signed-in user may read the current scope before publishing; only platform
 * administrators maintain it, so this page never offers an edit control.
 */
import { onMounted } from "vue";
import { readBannedScope } from "../../api/products";
import type { BannedScopeView } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { bannedGroupLabels } from "../../app/labels";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";

const scope = useAsyncData<BannedScopeView>((signal) => readBannedScope(signal));

onMounted(() => {
  void scope.run();
});
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="发布"
      title="禁发范围"
      description="该范围由平台管理员维护；发布前请确认商品不涉及以下内容。"
    >
      <template #actions>
        <RouterLink to="/products/new" class="btn btn--primary">去发布</RouterLink>
      </template>
    </PageHeader>

    <LoadingBlock v-if="scope.isLoading.value" label="正在加载禁发范围…" />
    <ErrorNotice v-else-if="scope.problem.value" :error="scope.error.value" @retry="scope.run" />
    <template v-else-if="scope.data.value">
      <p class="muted">最近更新：{{ formatDateTime(scope.data.value.updated_at) }}</p>
      <section
        v-for="group in scope.data.value.groups"
        v-show="group.items.length"
        :key="group.group"
        class="card"
      >
        <div class="card__head">
          <h2>{{ bannedGroupLabels[group.group] }}</h2>
          <span class="chip">{{ group.items.length }} 条</span>
        </div>
        <ul class="items">
          <li v-for="item in group.items" :key="item.id" class="item">
            <span class="state state--danger">禁发</span>
            <span>{{ item.content }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.items {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: 0.875rem;
}
</style>
