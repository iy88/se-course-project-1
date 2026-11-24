<script setup lang="ts">
/*
 * Banned-scope maintenance (API-PRD-013). Each detail is saved individually
 * inside its category section; the whole-scope replacement endpoint remains
 * available for API compatibility.
 */
import { computed, onMounted, ref } from "vue";
import UiIcon from "../../../shared/UiIcon.vue";
import type { BannedGroupKey, BannedItemPayload, BannedItemView } from "../api/contracts";
import {
  createBannedItem,
  deleteBannedItem,
  readBannedScope,
  updateBannedItem,
} from "../api/banned";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { bannedGroupLabels, bannedGroupOrder } from "../app/labels";
import { problemMessage } from "../app/problems";
import { notify } from "../app/toast";
import ConfirmDialog from "../components/ConfirmDialog.vue";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";

interface EditRow {
  key: number;
  id: string | null;
  group: BannedGroupKey;
  content: string;
  savedContent: string;
  order: number;
  savedOrder: number;
  saving: boolean;
}

const rows = ref<EditRow[]>([]);
const loading = ref(false);
const error = ref<unknown>(null);
const updatedAt = ref<string | null>(null);
const pendingRemove = ref<EditRow | null>(null);
const keys = new IdempotencyKeys();
let nextKey = 1;

const groupSections = computed(() =>
  bannedGroupOrder.map((group) => ({
    group,
    label: bannedGroupLabels[group],
    rows: rows.value.filter((row) => row.group === group),
  })),
);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const scope = await readBannedScope();
    updatedAt.value = scope.updated_at;
    rows.value = scope.groups.flatMap((group) =>
      group.items.map((item) => editRow(group.group, item)),
    );
  } catch (caught) {
    error.value = caught;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function editRow(group: BannedGroupKey, item: BannedItemView): EditRow {
  return {
    key: nextKey++,
    id: item.id,
    group,
    content: item.content,
    savedContent: item.content,
    order: item.display_order,
    savedOrder: item.display_order,
    saving: false,
  };
}

function nextOrder(group: BannedGroupKey): number {
  return (
    Math.max(0, ...rows.value.filter((row) => row.group === group).map((row) => row.order)) + 1
  );
}

function addRow(group: BannedGroupKey): void {
  rows.value = [
    ...rows.value,
    {
      key: nextKey++,
      id: null,
      group,
      content: "",
      savedContent: "",
      order: nextOrder(group),
      savedOrder: 0,
      saving: false,
    },
  ];
}

function isDirty(row: EditRow): boolean {
  return (
    row.id === null ||
    row.content.trim() !== row.savedContent ||
    Number(row.order) !== row.savedOrder
  );
}

function requestRemove(row: EditRow): void {
  if (row.id === null) {
    rows.value = rows.value.filter((candidate) => candidate.key !== row.key);
    return;
  }
  pendingRemove.value = row;
}

async function confirmRemove(): Promise<void> {
  const row = pendingRemove.value;
  pendingRemove.value = null;
  if (!row?.id || row.saving) return;
  row.saving = true;
  try {
    const mutation = await deleteBannedItem(row.id, keys.current(`banned-item-${row.id}`));
    keys.rotate(`banned-item-${row.id}`);
    rows.value = rows.value.filter((candidate) => candidate.key !== row.key);
    updatedAt.value = mutation.updated_at;
    notify.success("禁发细目已移除。");
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    row.saving = false;
  }
}

function payload(row: EditRow): BannedItemPayload | null {
  const content = row.content.trim();
  if (!content) {
    notify.error("禁发细目内容不能为空。");
    return null;
  }
  const order = Number(row.order);
  if (String(row.order).trim() === "" || !Number.isInteger(order) || order < 0) {
    notify.error("展示顺序必须是非负整数。");
    return null;
  }
  return { group: row.group, content, display_order: order };
}

async function saveRow(row: EditRow): Promise<void> {
  if (row.saving) return;
  const input = payload(row);
  if (!input) return;
  const operation = row.id ? `banned-item-${row.id}` : `banned-item-new-${row.key}`;
  row.saving = true;
  try {
    const mutation = row.id
      ? await updateBannedItem(row.id, input, keys.current(operation))
      : await createBannedItem(input, keys.current(operation));
    keys.rotate(operation);
    row.id = mutation.item.id;
    row.content = mutation.item.content;
    row.savedContent = mutation.item.content;
    row.order = mutation.item.display_order;
    row.savedOrder = mutation.item.display_order;
    updatedAt.value = mutation.updated_at;
    notify.success("禁发细目已保存。");
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    row.saving = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader title="禁发范围" description="按大类维护禁发细目；每一条都可以单独保存或移除。">
      <template #actions>
        <span class="chip">最近更新 {{ formatDateTime(updatedAt) }}</span>
      </template>
    </PageHeader>

    <LoadingBlock v-if="loading && !rows.length" label="正在加载禁发范围…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="load" />
    <form v-else class="banned-groups" aria-label="禁发范围" @submit.prevent>
      <fieldset
        v-for="section in groupSections"
        :key="section.group"
        class="banned-group"
        :data-group="section.group"
      >
        <legend>
          <span>{{ section.label }}</span>
          <span class="banned-group__count">{{ section.rows.length }} 条</span>
        </legend>
        <div class="banned-group__body">
          <p v-if="!section.rows.length" class="banned-group__empty">
            暂无细目，可在本大类下添加。
          </p>
          <ul v-else class="banned-list">
            <li
              v-for="row in section.rows"
              :key="row.key"
              class="banned-row"
              :class="{ 'banned-row--dirty': isDirty(row) }"
            >
              <div class="field banned-row__content">
                <label :for="`banned-content-${row.key}`">细目内容</label>
                <input
                  :id="`banned-content-${row.key}`"
                  v-model="row.content"
                  class="input"
                  maxlength="200"
                  placeholder="例如：处方药与医疗器械"
                />
              </div>
              <div class="field banned-row__order">
                <label :for="`banned-order-${row.key}`">顺序</label>
                <input
                  :id="`banned-order-${row.key}`"
                  v-model.number="row.order"
                  class="input"
                  type="number"
                  min="0"
                  inputmode="numeric"
                />
              </div>
              <div class="banned-row__actions">
                <button
                  type="button"
                  class="btn btn--primary btn--small"
                  :disabled="row.saving || (row.id !== null && !isDirty(row))"
                  @click="saveRow(row)"
                >
                  {{ row.saving ? "保存中…" : row.id ? "保存" : "添加" }}
                </button>
                <button
                  type="button"
                  class="btn btn--ghost btn--small"
                  :disabled="row.saving"
                  @click="requestRemove(row)"
                >
                  {{ row.id ? "移除" : "取消" }}
                </button>
              </div>
            </li>
          </ul>
          <button
            type="button"
            class="btn btn--small banned-group__add"
            @click="addRow(section.group)"
          >
            <UiIcon name="plus" />
            添加细目
          </button>
        </div>
      </fieldset>
    </form>

    <ConfirmDialog
      :open="pendingRemove !== null"
      title="移除这条禁发细目？"
      description="移除后，发布和审核页面将不再展示该细目；已有审核记录不会改变。"
      confirm-label="确认移除"
      tone="danger"
      @cancel="pendingRemove = null"
      @confirm="confirmRemove"
    />
  </div>
</template>

<style scoped>
.banned-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 27rem), 1fr));
  gap: var(--space-4);
  align-items: start;
}

.banned-group {
  min-inline-size: 0;
  margin: 0;
  padding: 0;
  overflow: clip;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
}

.banned-group legend {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  inline-size: 100%;
  padding: var(--space-3) var(--space-4);
  border-block-end: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel-soft) 42%, var(--panel));
  color: var(--ink);
  font-size: 0.9375rem;
  font-weight: 700;
}

.banned-group__count {
  color: var(--ink-soft);
  font-size: 0.75rem;
  font-weight: 500;
}

.banned-group__body {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
}

.banned-group__empty {
  padding-block: var(--space-2);
  color: var(--ink-faint);
  font-size: 0.8125rem;
}

.banned-list {
  display: grid;
  gap: var(--space-2);
}

.banned-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 5.5rem auto;
  align-items: end;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--panel-soft) 34%, var(--panel));
}

.banned-row--dirty {
  border-color: var(--brand);
  box-shadow: inset 3px 0 0 var(--brand);
}

.banned-row .field {
  gap: var(--space-1);
}

.banned-row__content {
  min-inline-size: 0;
}

.banned-row__actions {
  display: flex;
  gap: var(--space-1);
  padding-block-end: 0.0625rem;
}

.banned-group__add {
  justify-self: start;
}

@media (width < 40rem) {
  .banned-row {
    grid-template-columns: minmax(0, 1fr) 5rem;
  }

  .banned-row__actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
  }
}
</style>
