<script setup lang="ts">
/*
 * Product comments and seller replies (API-PRD-024—027).
 *
 * The list is paged by top-level comment; replies arrive with their parent and
 * are rendered inside the same thread. A hidden product only returns the
 * reader's own comments, so the component shows the server result unchanged
 * instead of inventing an empty state.
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  createProductComment,
  deleteProductComment,
  listProductComments,
  replyToProductComment,
} from "../../api/products";
import type { CommentView } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatRelative } from "../../app/format";
import { IdempotencyKeys } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { useToastStore } from "../../app/toast";
import { session } from "../../app/session";
import AvatarBadge from "../AvatarBadge.vue";
import ConfirmDialog from "../ConfirmDialog.vue";
import EmptyState from "../EmptyState.vue";
import ErrorNotice from "../ErrorNotice.vue";
import LoadingBlock from "../LoadingBlock.vue";
import PaginationBar from "../PaginationBar.vue";

const { notify } = useToastStore();

const props = defineProps<{
  productId: string;
  canComment: boolean;
  sellerId: string;
}>();

const route = useRoute();
const section = ref<HTMLElement | null>(null);
const anchorId = computed(() => /^#comment-([1-9][0-9]*)$/.exec(route.hash)?.[1]);
let pendingAnchor: string | undefined;
const comments = usePagedList<CommentView>((page, pageSize, signal) =>
  listProductComments(
    props.productId,
    { page, page_size: pageSize, anchor_comment_id: pendingAnchor },
    signal,
  ),
);
const keys = new IdempotencyKeys();

const draft = ref("");
const posting = ref(false);
const replyTarget = ref<CommentView | null>(null);
const replyDraft = ref("");
const replying = ref(false);
const removing = ref<string | null>(null);
const commentToDelete = ref<CommentView | null>(null);

const isSeller = computed(() => session.accountId.value === props.sellerId);

async function load(): Promise<void> {
  const targetId = anchorId.value;
  const productId = props.productId;
  pendingAnchor = targetId;
  const loading = comments.load(1);
  pendingAnchor = undefined;
  await loading;
  if (
    !targetId ||
    targetId !== anchorId.value ||
    productId !== props.productId ||
    comments.state.value !== "ready"
  )
    return;
  await nextTick();
  (document.getElementById(`comment-${targetId}`) ?? section.value)?.scrollIntoView({
    block: "start",
  });
}

onMounted(load);
watch([() => props.productId, anchorId], () => {
  replyTarget.value = null;
  void load();
});

function statusLabel(comment: CommentView): string {
  if (comment.status === "deleted_by_author") return "作者已删除";
  if (comment.status === "removed_by_admin") return "管理员已移除";
  return "";
}

function canReply(comment: CommentView): boolean {
  return isSeller.value && comment.status === "published" && !comment.reply_to_comment_id;
}

function canReport(comment: CommentView): boolean {
  const accountId = session.accountId.value;
  return accountId !== null && comment.status === "published" && comment.author.id !== accountId;
}

function canDelete(comment: CommentView): boolean {
  return comment.status === "published" && comment.author.id === session.accountId.value;
}

function startReply(comment: CommentView): void {
  replyTarget.value = comment;
  replyDraft.value = "";
}

async function submitComment(): Promise<void> {
  const body = draft.value.trim();
  if (!body || posting.value) return;
  posting.value = true;
  try {
    await createProductComment(props.productId, body, keys.current("comment-create"));
    keys.rotate("comment-create");
    draft.value = "";
    notify.success("评论已发表。");
    await comments.load(1);
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    posting.value = false;
  }
}

async function submitReply(): Promise<void> {
  const target = replyTarget.value;
  const body = replyDraft.value.trim();
  if (!target || !body || replying.value) return;
  replying.value = true;
  const operation = `reply-${target.id}`;
  try {
    await replyToProductComment(props.productId, target.id, body, keys.current(operation));
    keys.rotate(operation);
    replyTarget.value = null;
    replyDraft.value = "";
    notify.success("回复已发表。");
    await comments.load();
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    replying.value = false;
  }
}

async function confirmDelete(): Promise<void> {
  const comment = commentToDelete.value;
  if (!comment || removing.value) return;
  commentToDelete.value = null;
  removing.value = comment.id;
  const operation = `delete-${comment.id}`;
  try {
    await deleteProductComment(props.productId, comment.id, keys.current(operation));
    keys.rotate(operation);
    notify.success("评论已删除。");
    await comments.load();
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    removing.value = null;
  }
}
</script>

<template>
  <section ref="section" class="card comment-section">
    <div class="card__head">
      <h2>商品评论</h2>
      <span class="chip">{{ comments.paging.total }} 条</span>
    </div>

    <form v-if="canComment" class="comment-form" @submit.prevent="submitComment">
      <label class="visually-hidden" for="comment-body">评论内容</label>
      <textarea
        id="comment-body"
        v-model="draft"
        class="textarea"
        rows="3"
        placeholder="分享你的使用感受，或向卖方提问"
      />
      <div class="comment-form__actions">
        <span class="muted">评论将公开显示</span>
        <button type="submit" class="btn btn--primary" :disabled="posting || !draft.trim()">
          {{ posting ? "正在发表…" : "发表评论" }}
        </button>
      </div>
    </form>
    <p v-else-if="isSeller" class="muted">你是卖方，可以在买家评论下回复。</p>

    <LoadingBlock
      v-if="comments.isLoading.value && !comments.items.value.length"
      label="正在加载评论…"
    />
    <ErrorNotice v-else-if="comments.problem.value" :error="comments.error.value" @retry="load" />
    <EmptyState
      v-else-if="comments.isEmpty.value"
      title="还没有评论"
      description="买家的评论和你的回复会显示在这里。"
    />
    <ul v-else class="comment-list">
      <li
        v-for="comment in comments.items.value"
        :id="`comment-${comment.id}`"
        :key="comment.id"
        class="comment"
      >
        <header class="comment__head">
          <AvatarBadge
            :display-name="comment.author.display_name"
            :url="comment.author.avatar_url"
            size="sm"
          />
          <span class="comment__author">{{ comment.author.display_name }}</span>
          <span class="muted">{{ formatRelative(comment.created_at) }}</span>
          <span v-if="statusLabel(comment)" class="chip chip--warn">{{
            statusLabel(comment)
          }}</span>
        </header>
        <p v-if="comment.body" class="comment__body pre-line break-anywhere">{{ comment.body }}</p>
        <div class="comment__actions">
          <button
            v-if="canReply(comment)"
            type="button"
            class="btn btn--small btn--ghost"
            @click="startReply(comment)"
          >
            回复
          </button>
          <RouterLink
            v-if="canReport(comment)"
            :to="{ name: 'report', query: { target_type: 'comment', target_id: comment.id } }"
            class="btn btn--small btn--ghost"
          >
            举报
          </RouterLink>
          <button
            v-if="canDelete(comment)"
            type="button"
            class="btn btn--small btn--ghost"
            :disabled="removing === comment.id"
            @click="commentToDelete = comment"
          >
            删除
          </button>
        </div>

        <form
          v-if="replyTarget?.id === comment.id"
          class="reply-form"
          @submit.prevent="submitReply"
        >
          <label class="visually-hidden" for="reply-body">回复内容</label>
          <textarea
            id="reply-body"
            v-model="replyDraft"
            class="textarea"
            rows="2"
            placeholder="回复这条评论"
          />
          <div class="comment-form__actions">
            <button type="button" class="btn btn--small btn--ghost" @click="replyTarget = null">
              取消
            </button>
            <button
              type="submit"
              class="btn btn--small btn--primary"
              :disabled="replying || !replyDraft.trim()"
            >
              {{ replying ? "正在回复…" : "发表回复" }}
            </button>
          </div>
        </form>

        <ul v-if="comment.replies?.length" class="reply-list">
          <li
            v-for="reply in comment.replies"
            :id="`comment-${reply.id}`"
            :key="reply.id"
            class="reply"
          >
            <header class="comment__head">
              <AvatarBadge
                :display-name="reply.author.display_name"
                :url="reply.author.avatar_url"
                size="sm"
              />
              <span class="comment__author">{{ reply.author.display_name }}</span>
              <span class="chip">卖方回复</span>
              <span class="muted">{{ formatRelative(reply.created_at) }}</span>
            </header>
            <p v-if="reply.body" class="comment__body pre-line break-anywhere">{{ reply.body }}</p>
            <div class="comment__actions">
              <RouterLink
                v-if="canReport(reply)"
                :to="{ name: 'report', query: { target_type: 'comment', target_id: reply.id } }"
                class="btn btn--small btn--ghost"
              >
                举报
              </RouterLink>
              <button
                v-if="canDelete(reply)"
                type="button"
                class="btn btn--small btn--ghost"
                :disabled="removing === reply.id"
                @click="commentToDelete = reply"
              >
                删除
              </button>
            </div>
          </li>
        </ul>
      </li>
    </ul>

    <PaginationBar
      v-if="!comments.isEmpty.value"
      :page="comments.paging.page"
      :page-size="comments.paging.pageSize"
      :total="comments.paging.total"
      @change="comments.load"
    />

    <ConfirmDialog
      :open="commentToDelete !== null"
      title="删除这条评论？"
      description="删除后评论不再公开显示，记录会保留。"
      confirm-label="确认删除"
      tone="danger"
      @cancel="commentToDelete = null"
      @confirm="confirmDelete"
    />
  </section>
</template>

<style scoped>
.comment-section,
.comment,
.reply {
  scroll-margin-block-start: 5rem;
}

.comment-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-block-end: var(--space-4);
  border-block-end: 1px solid var(--line);
  margin-block-end: var(--space-4);
}

.comment-form__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.comment-list,
.reply-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.comment {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-block-end: var(--space-4);
  border-block-end: 1px solid var(--line);
}

.comment:last-child {
  border-block-end: none;
  padding-block-end: 0;
}

.comment__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: 0.875rem;
}

.comment__author {
  font-weight: 600;
}

.comment__body {
  margin: 0;
  font-size: 0.9375rem;
}

.comment__actions {
  display: flex;
  gap: var(--space-2);
}

.reply-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--panel-soft, #f7faf8);
  border-radius: var(--radius-sm);
}

.reply-list {
  gap: var(--space-3);
  margin-inline-start: var(--space-4);
  padding-inline-start: var(--space-3);
  border-inline-start: 2px solid var(--line);
}

.reply {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
</style>
