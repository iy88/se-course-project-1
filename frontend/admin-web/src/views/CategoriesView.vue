<script setup lang="ts">
/* Category and alias maintenance (API-PRD-015—021). */
import { computed, onMounted, ref } from "vue";
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
import ConfirmDialog from "../components/ConfirmDialog.vue";
import EmptyState from "../components/EmptyState.vue";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";

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
const createName = ref("");
const creating = ref(false);
const selectedId = ref<string | null>(null);
const renameValue = ref("");
const aliasValue = ref("");
const busy = ref(false);
const pending = ref<PendingAction | null>(null);
const keys = new IdempotencyKeys();

const selected = computed(() => items.value.find((item) => item.id === selectedId.value) ?? null);
const aliases = computed(
  () => selected.value?.names.filter((name) => name.kind === "alias" && name.active) ?? [],
);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    items.value = (await listAdminCategories()).items;
    if (selectedId.value && !items.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = null;
    }
    if (selectedId.value) {
      const current = items.value.find((item) => item.id === selectedId.value);
      if (current) renameValue.value = current.main_name;
    }
  } catch (caught) {
    error.value = caught;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function select(category: CategoryDetail): void {
  selectedId.value = category.id;
  renameValue.value = category.main_name;
  aliasValue.value = "";
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
    await load();
    select(created);
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
    await renameCategory(category.id, name, keys.current(`rename-${category.id}`));
    keys.rotate(`rename-${category.id}`);
    notify.success("分类主名已更新，旧主名保留为别名。");
    await load();
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
    await load();
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
  try {
    if (action.type === "disable") {
      await disableCategory(category.id, keys.current(`disable-${category.id}`));
      keys.rotate(`disable-${category.id}`);
      notify.success("分类已停用，已有商品保留关联。");
    } else if (action.type === "delete") {
      await deleteCategory(category.id, keys.current(`delete-${category.id}`));
      keys.rotate(`delete-${category.id}`);
      notify.success("分类已删除。");
      selectedId.value = null;
    } else if (action.type === "alias" && action.nameId) {
      await removeCategoryAlias(
        category.id,
        action.nameId,
        keys.current(`alias-remove-${action.nameId}`),
      );
      keys.rotate(`alias-remove-${action.nameId}`);
      notify.success("别名已移除。");
    }
    await load();
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    busy.value = false;
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
        <span class="chip">{{ items.length }} 个分类</span>
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
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>主名</th>
              <th>别名</th>
              <th>状态</th>
              <th>关联商品</th>
              <th>创建时间</th>
              <th><span class="visually-hidden">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="category in items"
              :key="category.id"
              :class="{ 'row--selected': category.id === selectedId }"
            >
              <td>
                <span class="mono muted">#{{ category.id }}</span>
                <div>{{ category.main_name }}</div>
              </td>
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
                <button type="button" class="btn btn--small" @click="select(category)">管理</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="selected" class="card">
      <div class="card__head">
        <h2>编辑「{{ selected.main_name }}」</h2>
        <span class="chip">{{ categoryStateLabels[selected.state] ?? selected.state }}</span>
      </div>

      <div class="edit-grid">
        <form class="stack stack--tight" @submit.prevent="rename">
          <label class="field">
            <span class="field__label">主名</span>
            <input v-model="renameValue" class="input" maxlength="50" />
            <span class="field__hint">改名后旧主名自动保留为别名。</span>
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

      <div class="stack stack--tight">
        <h3 class="section-title">别名</h3>
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
      </div>

      <div class="divider" />

      <div class="spread">
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
        <div class="inline">
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
        </div>
      </div>
    </section>

    <ConfirmDialog
      :open="pending !== null"
      :title="pending?.title ?? ''"
      :description="pending?.description"
      :confirm-label="pending?.confirmLabel"
      tone="danger"
      @cancel="pending = null"
      @confirm="runPending"
    />
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
</style>
