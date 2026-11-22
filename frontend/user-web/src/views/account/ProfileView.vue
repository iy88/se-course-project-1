<script setup lang="ts">
/*
 * Own profile: avatar and display name.
 *
 * Both mutations are re-read from the server afterwards so the header, the
 * aggregation page and the trade counterparty projection all show the same value.
 */
import { computed, ref } from "vue";
import { removeAvatar, setAvatar, updateProfile } from "../../api/account";
import { uploadVerifiedFile } from "../../api/files";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { refreshSession, session } from "../../app/session";
import { entryLimits } from "../../app/entry";
import { notify } from "../../app/toast";
import { getDataSource, setDataSource } from "../../api/http";
import { resetMockState } from "../../mock/handlers";
import AvatarBadge from "../../components/AvatarBadge.vue";
import PageHeader from "../../components/PageHeader.vue";

const displayName = ref(session.displayName.value);
const savingName = ref(false);
const uploadingAvatar = ref(false);
const removingAvatar = ref(false);
const error = ref<string | null>(null);
const source = ref(getDataSource());

const nameChanged = computed(
  () => displayName.value.trim() !== session.displayName.value && displayName.value.trim() !== "",
);
const maxNameLength = computed(() => entryLimits.value?.display_name_max_length ?? 24);

const avatarInput = ref<HTMLInputElement | null>(null);

async function saveName(): Promise<void> {
  if (!nameChanged.value || savingName.value) return;
  error.value = null;
  savingName.value = true;
  try {
    await updateProfile({ display_name: displayName.value.trim() }, newIdempotencyKey());
    await refreshSession();
    notify.success("显示名称已更新。");
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    savingName.value = false;
  }
}

async function onAvatarSelected(event: Event): Promise<void> {
  const picker = event.target as HTMLInputElement;
  const file = picker.files?.[0];
  picker.value = "";
  if (!file) return;
  error.value = null;
  uploadingAvatar.value = true;
  try {
    const fileId = await uploadVerifiedFile("account_avatar", file, null, () =>
      newIdempotencyKey(),
    );
    // Design 0.2.6: the avatar is set through the profile endpoint, not its own route.
    await setAvatar(fileId, newIdempotencyKey());
    await refreshSession();
    notify.success("头像已更新。");
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    uploadingAvatar.value = false;
  }
}

async function clearAvatar(): Promise<void> {
  if (removingAvatar.value) return;
  error.value = null;
  removingAvatar.value = true;
  try {
    await removeAvatar(newIdempotencyKey());
    await refreshSession();
    notify.success("头像已移除，将显示默认标识。");
  } catch (caught) {
    error.value = problemMessage(caught);
  } finally {
    removingAvatar.value = false;
  }
}

function toggleDataSource(next: "live" | "mock"): void {
  setDataSource(next);
  source.value = next;
  if (next === "mock") resetMockState();
  window.location.reload();
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="我的"
      title="个人资料"
      description="头像与显示名称会展示在商品页、交易对方视图和会话中。"
    />

    <section class="card">
      <div class="card__head"><h2>头像</h2></div>
      <div class="avatar-row">
        <AvatarBadge
          :display-name="session.displayName.value"
          :url="session.avatarUrl.value"
          size="lg"
        />
        <div class="stack stack--tight">
          <div class="inline">
            <button
              type="button"
              class="btn"
              :disabled="uploadingAvatar"
              @click="avatarInput?.click()"
            >
              {{ uploadingAvatar ? "上传中…" : session.avatarUrl.value ? "更换头像" : "上传头像" }}
            </button>
            <button
              v-if="session.avatarUrl.value"
              type="button"
              class="btn btn--ghost"
              :disabled="removingAvatar"
              @click="clearAvatar"
            >
              {{ removingAvatar ? "移除中…" : "移除头像" }}
            </button>
          </div>
          <p class="muted">支持 JPG、PNG，建议使用 1:1 的正方形图片。</p>
        </div>
      </div>
      <input
        ref="avatarInput"
        type="file"
        accept="image/jpeg,image/png"
        class="visually-hidden"
        @change="onAvatarSelected"
      />
    </section>

    <section class="card">
      <div class="card__head"><h2>显示名称</h2></div>
      <div class="field">
        <label class="field__label" for="display-name">名称</label>
        <input
          id="display-name"
          v-model="displayName"
          class="input"
          :maxlength="maxNameLength"
          autocomplete="nickname"
        />
        <span class="field__hint">最多 {{ maxNameLength }} 个字符</span>
      </div>
      <div class="inline">
        <button
          type="button"
          class="btn btn--primary"
          :disabled="!nameChanged || savingName"
          @click="saveName"
        >
          {{ savingName ? "保存中…" : "保存名称" }}
        </button>
        <RouterLink to="/me/security" class="btn btn--ghost">账户安全</RouterLink>
      </div>
    </section>

    <p v-if="error" class="banner banner--danger" role="alert">{{ error }}</p>

    <section class="card">
      <div class="card__head">
        <h2>本地联调</h2>
        <span class="muted">数据源</span>
      </div>
      <p class="muted">
        真实接口需要对应后端工作包已合入并启动；本地模拟使用内置示例数据，覆盖相同的接口与错误码。
      </p>
      <div class="inline source-row">
        <label class="chip" :class="{ 'chip--active': source === 'live' }">
          <input
            type="radio"
            name="data-source"
            value="live"
            :checked="source === 'live'"
            class="visually-hidden"
            @change="toggleDataSource('live')"
          />
          真实接口
        </label>
        <label class="chip" :class="{ 'chip--active': source === 'mock' }">
          <input
            type="radio"
            name="data-source"
            value="mock"
            :checked="source === 'mock'"
            class="visually-hidden"
            @change="toggleDataSource('mock')"
          />
          本地模拟
        </label>
      </div>
    </section>
  </div>
</template>

<style scoped>
.avatar-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.source-row {
  margin-block-start: var(--space-3);
}

.source-row .chip {
  cursor: pointer;
  min-block-size: 2rem;
  padding-inline: var(--space-3);
}
</style>
