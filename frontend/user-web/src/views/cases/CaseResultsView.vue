<script setup lang="ts">
import { onMounted } from "vue";
import { listPublicCaseResults } from "../../api/cases";
import type { PublicCaseResult } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { caseDecisionLabels } from "../../app/labels";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";

const list = usePagedList<PublicCaseResult>((page, pageSize, signal) =>
  listPublicCaseResults({ page, page_size: pageSize }, signal),
);

onMounted(() => {
  void list.load(1);
});
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader title="公开结果" />
    <ErrorNotice
      v-if="list.problem.value"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <LoadingBlock v-else-if="list.isLoading.value && !list.items.value.length" />
    <EmptyState v-else-if="list.isEmpty.value" title="暂无公开结果" />
    <template v-else>
      <article v-for="result in list.items.value" :key="result.case_id" class="card stack">
        <h2 class="break-anywhere">{{ result.public_summary }}</h2>
        <p>{{ caseDecisionLabels[result.decision_kind] }}</p>
        <p class="pre-line break-anywhere">{{ result.public_reason }}</p>
        <time class="muted" :datetime="result.published_at">
          {{ formatDateTime(result.published_at) }}
        </time>
      </article>
      <PaginationBar
        :page="list.paging.page"
        :page-size="list.paging.pageSize"
        :total="list.paging.total"
        @change="list.load"
      />
    </template>
  </div>
</template>
