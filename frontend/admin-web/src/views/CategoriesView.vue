<script setup lang="ts">
/* Category and alias maintenance (API-PRD-015—021). */
import { computed, nextTick, onMounted, ref } from "vue";
import type { CategoryDetail } from "../api/contracts";
import {
  addCategoryAlias,
  createCategory,
  deleteCategory,
  disableCategory,
  listAdminCategories,
  removeCategoryAlias,
  renameCategory,
} from "../api/categories";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { categoryStateLabels } from "../app/labels";
import { problemMessage } from "../app/problems";
import { notify } from "../app/toast";
import EmptyState from "../components/EmptyState.vue";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";
import PaginationBar from "../components/PaginationBar.vue";

interface PendingAction {
  type: "disable" | "delete" | "alias";
  title: string;
  description: string;
  confirmLabel: string;
  nameId?: string;
}

const items = ref<CategoryDetail[]>([]);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const createName = ref("");
const creating = ref(false);
const selected = ref<CategoryDetail | null>(null);
const editorDialog = ref<HTMLDialogElement | null>(null);
const renameValue = ref("");
const aliasValue = ref("");
const busy = ref(false);
const pending = ref<PendingAction | null>(null);
const keys = new IdempotencyKeys();

const aliases = computed(
  () => selected.value?.names.filter((name) => name.kind === "alias" && name.active) ?? [],
);
const editorTitle = computed(() =>
  selected.value ? `管理分类「${selected.value.main_name}」` : "管理分类",
);

async function load(targetPage = page.value): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const result = await listAdminCategories({ page: targetPage, page_size: pageSize.value });
    items.value = result.items;
    page.value = result.page;
    pageSize.value = result.page_size;
    total.value = result.total;
    syncSelected();
  } catch (caught) {
    error.value = caught;
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());

function syncSelected(): void {
  if (!selected.value) return;
  const current = items.value.find((item) => item.id === selected.value?.id);
  if (current) selected.value = current;
}

function replaceCategory(category: CategoryDetail): void {
  items.value = items.value.map((item) => (item.id === category.id ? category : item));
}

function openEditor(category: CategoryDetail): void {
  selected.value = category;
  renameValue.value = category.main_name;
  aliasValue.value = "";
  pending.value = null;
  void nextTick(() => {
    if (editorDialog.value && !editorDialog.value.open) editorDialog.value.showModal();
  });
}

function closeEditor(): void {
  if (busy.value) return;
  editorDialog.value?.close();
}

function editorClosed(): void {
  selected.value = null;
  renameValue.value = "";
  aliasValue.value = "";
  pending.value = null;
}

async function create(): Promise<void> {
  const name = createName.value.trim();
  if (!name || creating.value) return;
  creating.value = true;
  try {
    const created = await createCategory(name, keys.current("category-create"));
    keys.rotate("category-create");
    createName.value = "";
    notify.success(`已创建分类「${created.main_name}」。`);
    const targetPage = Math.max(1, Math.ceil((total.value + 1) / pageSize.value));
    await load(targetPage);
    openEditor(items.value.find((item) => item.id === created.id) ?? created);
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    creating.value = false;
  }
}

async function rename(): Promise<void> {
  const category = selected.value;
  const name = renameValue.value.trim();
  if (!category || !name || busy.value) return;
  if (name === category.main_name) return;
  busy.value = true;
  try {
    const updated = await renameCategory(category.id, name, keys.current(`rename-${category.id}`));
    keys.rotate(`rename-${category.id}`);
    selected.value = updated;
    replaceCategory(updated);
    notify.success("分类主名已更新，旧主名保留为别名。");
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    busy.value = false;
  }
}

async function addAlias(): Promise<void> {
  const category = selected.value;
  const name = aliasValue.value.trim();
  if (!category || !name || busy.value) return;
  busy.value = true;
  try {
    await addCategoryAlias(category.id, name, keys.current(`alias-${category.id}`));
    keys.rotate(`alias-${category.id}`);
    aliasValue.value = "";
    notify.success("别名已添加。");
    await load(page.value);
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    busy.value = false;
  }
}

async function runPending(): Promise<void> {
  const action = pending.value;
  const category = selected.value;
  pending.value = null;
  if (!action || !category) return;
  busy.value = true;
  let deleted = false;
  try {
    if (action.type === "disable") {
      const updated = await disableCategory(category.id, keys.current(`disable-${category.id}`));
      keys.rotate(`disable-${category.id}`);
      selected.value = updated;
      replaceCategory(updated);
      notify.success("分类已停用，已有商品保留关联。");
    } else if (action.type === "delete") {
      await deleteCategory(category.id, keys.current(`delete-${category.id}`));
      keys.rotate(`delete-${category.id}`);
      notify.success("分类已删除。");
      deleted = true;
    } else if (action.type === "alias" && action.nameId) {
      await removeCategoryAlias(
        category.id,
        action.nameId,
        keys.current(`alias-remove-${action.nameId}`),
      );
      keys.rotate(`alias-remove-${action.nameId}`);
      notify.success("别名已移除。");
    }
    if (deleted) {
      const remaining = Math.max(0, total.value - 1);
      await load(Math.min(page.value, Math.max(1, Math.ceil(remaining / pageSize.value))));
    } else {
      await load(page.value);
    }
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    busy.value = false;
    if (deleted) closeEditor();
  }
}

function askDisable(): void {
  if (!selected.value) return;
  pending.value = {
    type: "disable",
    title: "停用该分类？",
    description: "停用后新发布不可选择该分类；已有商品保留关联，公开在售商品仍可筛选。",
    confirmLabel: "确认停用",
  };
}

function askDelete(): void {
  if (!selected.value) return;
  pending.value = {
    type: "delete",
    title: "删除该分类？",
    description: "仅从未关联商品的分类可删除。删除后名称停用，记录保留。",
    confirmLabel: "确认删除",
  };
}

function askRemoveAlias(nameId: string, name: string): void {
  if (!selected.value) return;
  pending.value = {
    type: "alias",
    title: `移除别名「${name}」？`,
    description: "移除后搜索与筛选不再按该别名解析；商品归属与历史记录不变。",
    confirmLabel: "确认移除",
    nameId,
  };
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      title="分类管理"
      description="一个分类保留一个主名并可维护多个别名；改名不改变分类身份，停用不影响已有商品与历史。"
    >
      <template #actions>
        <span class="chip">共 {{ total }} 个分类</span>
      </template>
    </PageHeader>

    <section class="card">
      <div class="card__head">
        <h2>新建分类</h2>
      </div>
      <form class="inline-form" @submit.prevent="create">
        <label class="field">
          <span class="field__label">分类名称</span>
          <input v-model="createName" class="input" maxlength="50" placeholder="例如：考研资料" />
        </label>
        <button type="submit" class="btn btn--primary" :disabled="creating || !createName.trim()">
          {{ creating ? "创建中…" : "创建分类" }}
        </button>
      </form>
    </section>

    <section class="card" :aria-busy="loading">
      <LoadingBlock v-if="loading && !items.length" label="正在加载分类…" />
      <ErrorNotice v-else-if="error" :error="error" @retry="load" />
      <EmptyState
        v-else-if="!items.length"
        title="还没有分类"
        description="先创建一个分类，卖方发布商品时即可选择。"
      />
      <div
        v-else
        class="table-wrap"
        role="region"
        aria-labelledby="category-table-caption"
        tabindex="0"
      >
        <table class="table">
          <caption id="category-table-caption" class="visually-hidden">
            分类列表
          </caption>
          <thead>
            <tr>
              <th scope="col">主名</th>
              <th scope="col">别名</th>
              <th scope="col">状态</th>
              <th scope="col">关联商品</th>
              <th scope="col">创建时间</th>
              <th scope="col"><span class="visually-hidden">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="category in items"
              :key="category.id"
              :class="{ 'row--selected': category.id === selected?.id }"
            >
              <th scope="row">
                <span class="mono muted">#{{ category.id }}</span>
                <div>{{ category.main_name }}</div>
              </th>
              <td>
                <span
                  v-if="
                    !category.names.filter((name) => name.kind === 'alias' && name.active).length
                  "
                  class="muted"
                >
                  —
                </span>
                <span
                  v-for="alias in category.names.filter(
                    (name) => name.kind === 'alias' && name.active,
                  )"
                  :key="alias.category_name_id"
                  class="chip alias-chip"
                >
                  {{ alias.name }}
                </span>
              </td>
              <td>{{ categoryStateLabels[category.state] ?? category.state }}</td>
              <td>{{ category.associated_product_count }}</td>
              <td>{{ formatDateTime(category.created_at) }}</td>
              <td class="row-actions">
                <button type="button" class="btn btn--small" @click="openEditor(category)">
                  管理
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationBar
        v-if="items.length"
        :page="page"
        :page-size="pageSize"
        :total="total"
        label="分类列表分页"
        @change="load"
      />
    </section>

    <dialog
      ref="editorDialog"
      class="category-editor"
      aria-labelledby="category-editor-title"
      @close="editorClosed"
    >
      <div v-if="selected" class="category-editor__body">
        <header class="category-editor__head">
          <div>
            <p class="muted mono">分类 #{{ selected.id }}</p>
            <h1 id="category-editor-title">{{ editorTitle }}</h1>
          </div>
          <button
            type="button"
            class="btn btn--small btn--ghost"
            :disabled="busy"
            @click="closeEditor"
          >
            关闭
          </button>
        </header>

        <div class="edit-grid">
          <form class="stack stack--tight" @submit.prevent="rename">
            <label class="field">
              <span class="field__label">主名</span>
              <input
                v-model="renameValue"
                class="input"
                maxlength="50"
                autofocus
                aria-describedby="rename-hint"
              />
              <span id="rename-hint" class="field__hint">改名后旧主名自动保留为别名。</span>
            </label>
            <button
              type="submit"
              class="btn btn--small"
              :disabled="busy || !renameValue.trim() || renameValue.trim() === selected.main_name"
            >
              保存改名
            </button>
          </form>

          <form class="stack stack--tight" @submit.prevent="addAlias">
            <label class="field">
              <span class="field__label">新增别名</span>
              <input v-model="aliasValue" class="input" maxlength="50" placeholder="例如：考研书" />
            </label>
            <button type="submit" class="btn btn--small" :disabled="busy || !aliasValue.trim()">
              添加别名
            </button>
          </form>
        </div>

        <div class="divider" />

        <section class="stack stack--tight" aria-labelledby="category-alias-heading">
          <h2 id="category-alias-heading" class="section-title">别名</h2>
          <p v-if="!aliases.length" class="muted">当前没有有效别名。</p>
          <ul v-else class="alias-list">
            <li v-for="alias in aliases" :key="alias.category_name_id" class="spread alias-row">
              <span>{{ alias.name }}</span>
              <button
                type="button"
                class="btn btn--small btn--ghost"
                :disabled="busy"
                @click="askRemoveAlias(alias.category_name_id, alias.name)"
              >
                移除
              </button>
            </li>
          </ul>
        </section>

        <div class="divider" />

        <div class="spread category-editor__status">
          <p class="muted">
            {{
              selected.associated_product_count > 0
                ? `曾关联 ${selected.associated_product_count} 件商品，只能停用。`
                : "从未关联商品，可以删除。"
            }}
            <template v-if="selected.disabled_at">
              停用于 {{ formatDateTime(selected.disabled_at) }}。
            </template>
          </p>
          <span class="chip">
            {{ categoryStateLabels[selected.state] ?? selected.state }}
          </span>
        </div>

        <div v-if="pending" class="editor-confirm" role="alert">
          <div>
            <strong>{{ pending.title }}</strong>
            <p>{{ pending.description }}</p>
          </div>
          <div class="inline">
            <button type="button" class="btn btn--small" :disabled="busy" @click="pending = null">
              取消
            </button>
            <button
              type="button"
              class="btn btn--small btn--danger"
              :disabled="busy"
              @click="runPending"
            >
              {{ pending.confirmLabel }}
            </button>
          </div>
        </div>

        <footer class="category-editor__actions">
          <button
            v-if="selected.state !== 'disabled'"
            type="button"
            class="btn btn--small"
            :disabled="busy"
            @click="askDisable"
          >
            停用分类
          </button>
          <button
            type="button"
            class="btn btn--small btn--danger"
            :disabled="busy || selected.associated_product_count > 0"
            @click="askDelete"
          >
            删除分类
          </button>
        </footer>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
.inline-form {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.inline-form .field {
  flex: 1;
  min-inline-size: 12rem;
}

.row--selected {
  background: var(--brand-soft);
}

.category-editor {
  inline-size: min(56rem, calc(100vw - 2rem));
  max-block-size: calc(100dvh - 2rem);
  padding: 0;
  border: 0;
  border-radius: var(--radius);
  background: var(--panel);
  color: var(--ink);
  box-shadow: var(--shadow);
  overflow: auto;
}

.category-editor:modal {
  overscroll-behavior: contain;
}

.category-editor::backdrop {
  background: rgb(24 36 32 / 45%);
  overflow: hidden;
  overscroll-behavior: contain;
}

.category-editor__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
}

.category-editor__head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: var(--space-3);
}

.category-editor__head h1 {
  font-size: 1.25rem;
}

.category-editor__head .muted {
  margin-block-end: var(--space-1);
}

.category-editor__status {
  align-items: center;
}

.category-editor__status .muted {
  margin: 0;
}

.category-editor__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding-block-start: var(--space-3);
  border-block-start: 1px solid var(--line);
}

.editor-confirm {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: var(--danger);
}

.editor-confirm p {
  margin-block-start: var(--space-1);
  color: var(--ink-soft);
}

.row-actions {
  text-align: end;
}

.alias-chip {
  margin-inline-end: var(--space-1);
}

.edit-grid {
  display: grid;
  gap: var(--space-4);
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
}

.section-title {
  font-size: 0.875rem;
}

.alias-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.alias-row {
  padding-block: var(--space-2);
  border-block-end: 1px solid var(--line);
}

.alias-row:last-child {
  border-block-end: none;
}

@media (width < 36rem) {
  .category-editor__body {
    padding: var(--space-4);
  }

  .category-editor__status,
  .editor-confirm {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
