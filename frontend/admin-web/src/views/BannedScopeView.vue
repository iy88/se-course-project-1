<script setup lang="ts">
/*
 * Banned-scope maintenance (API-PRD-013). The endpoint replaces the whole
 * scope: retained rows keep their identifier, new rows are created and omitted
 * rows are logically removed by the server.
 */
import { onMounted, ref } from "vue";
import type { BannedGroupKey, BannedItemInput } from "../api/contracts";
import { readBannedScope, replaceBannedScope } from "../api/banned";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { bannedGroupLabels, bannedGroupOrder } from "../app/labels";
import { problemMessage } from "../app/problems";
import { notify } from "../app/toast";
import EmptyState from "../components/EmptyState.vue";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";

interface EditRow {
  key: number;
  id: string | null;
  group: BannedGroupKey;
  content: string;
  order: number;
}

const rows = ref<EditRow[]>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref<unknown>(null);
const updatedAt = ref<string | null>(null);
const keys = new IdempotencyKeys();
let nextKey = 1;

function blankRow(): EditRow {
  return { key: nextKey++, id: null, group: "other", content: "", order: rows.value.length + 1 };
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const scope = await readBannedScope();
    updatedAt.value = scope.updated_at;
    rows.value = scope.groups.flatMap((group) =>
      group.items.map((item) => ({
        key: nextKey++,
        id: item.id,
        group: group.group,
        content: item.content,
        order: item.display_order,
      })),
    );
    if (!rows.value.length) rows.value = [blankRow()];
  } catch (caught) {
    error.value = caught;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function addRow(): void {
  rows.value = [...rows.value, blankRow()];
}

function removeRow(key: number): void {
  if (rows.value.length <= 1) {
    notify.error("禁发范围至少保留一条细目。");
    return;
  }
  rows.value = rows.value.filter((row) => row.key !== key);
}

async function save(): Promise<void> {
  if (saving.value) return;
  const inputs: BannedItemInput[] = [];
  for (const row of rows.value) {
    const content = row.content.trim();
    if (!content) {
      notify.error("每条禁发细目都需要填写内容。");
      return;
    }
    inputs.push({
      ...(row.id ? { banned_item_id: row.id } : {}),
      group: row.group,
      content,
      display_order: row.order,
    });
  }
  saving.value = true;
  try {
    const scope = await replaceBannedScope(inputs, keys.current("banned-save"));
    keys.rotate("banned-save");
    updatedAt.value = scope.updated_at;
    notify.success("禁发范围已保存。");
    await load();
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      title="禁发范围"
      description="维护发布前展示的禁发细目。保存时保留现有条目、新建新增条目，未保留的条目会被移除。"
    >
      <template #actions>
        <span class="chip">最近更新 {{ formatDateTime(updatedAt) }}</span>
      </template>
    </PageHeader>

    <section class="card" :aria-busy="loading">
      <LoadingBlock v-if="loading && !rows.length" label="正在加载禁发范围…" />
      <ErrorNotice v-else-if="error" :error="error" @retry="load" />
      <EmptyState
        v-else-if="!rows.length"
        title="还没有禁发细目"
        description="添加第一条细目后保存。"
      />
      <template v-else>
        <div class="table-wrap">
          <table class="table banned-table">
            <thead>
              <tr>
                <th>分组</th>
                <th>细目内容</th>
                <th>顺序</th>
                <th><span class="visually-hidden">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.key">
                <td>
                  <select v-model="row.group" class="select" :aria-label="`第 ${row.order} 条分组`">
                    <option v-for="group in bannedGroupOrder" :key="group" :value="group">
                      {{ bannedGroupLabels[group] }}
                    </option>
                  </select>
                </td>
                <td>
                  <input
                    v-model="row.content"
                    class="input"
                    maxlength="200"
                    :aria-label="`第 ${row.order} 条内容`"
                    placeholder="例如：处方药与医疗器械"
                  />
                </td>
                <td class="order-cell">
                  <input
                    v-model.number="row.order"
                    class="input"
                    type="number"
                    min="0"
                    :aria-label="`第 ${row.order} 条顺序`"
                  />
                </td>
                <td class="row-actions">
                  <button
                    type="button"
                    class="btn btn--small btn--ghost"
                    @click="removeRow(row.key)"
                  >
                    移除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="spread banned-actions">
          <button type="button" class="btn btn--small" @click="addRow">添加细目</button>
          <div class="inline">
            <button type="button" class="btn btn--ghost" :disabled="saving" @click="load">
              放弃修改
            </button>
            <button type="button" class="btn btn--primary" :disabled="saving" @click="save">
              {{ saving ? "正在保存…" : "保存禁发范围" }}
            </button>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.banned-table td {
  vertical-align: top;
}

.order-cell {
  inline-size: 5.5rem;
}

.row-actions {
  text-align: end;
}

.banned-actions {
  margin-block-start: var(--space-3);
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-3);
}
</style>
