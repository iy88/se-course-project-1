<script setup lang="ts">
/*
 * Account settings: one page, one entry.
 *
 * Avatar, display name, password and mailbox live in sections here instead of on
 * separate routes, so the profile page only needs a single "账户设置" entry.
 * Avatar changes are cropped before upload: the picked image is previewed in a
 * square frame and only the confirmed crop is sent as an `account_avatar` file,
 * then bound through `PATCH /account/profile`. Cancelling the crop uploads
 * nothing. Password and mailbox changes invalidate every session, so a success
 * returns to the login screen.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  changeEmail,
  changePassword,
  removeAvatar,
  requestEmailVerification,
  setAvatar,
  updateProfile,
} from "../../api/account";
import type { EmailVerificationTicket } from "../../api/contracts";
import { uploadVerifiedFile } from "../../api/files";
import { resetBadges } from "../../app/badges";
import { resetRealtimeCursor } from "../../app/realtime";
import { clearCaseScopes } from "../../app/case-directory";
import { ensureEntryContext, entryLimits, passwordRuleText } from "../../app/entry";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { clearSession, refreshSession, session } from "../../app/session";
import { notify } from "../../app/toast";
import AvatarBadge from "../../components/AvatarBadge.vue";
import ImageCropper from "../../components/ImageCropper.vue";
import PageHeader from "../../components/PageHeader.vue";

const router = useRouter();

const displayName = ref(session.displayName.value);
const savingName = ref(false);
const uploadingAvatar = ref(false);
const removingAvatar = ref(false);
const avatarError = ref<string | null>(null);
const pendingAvatar = ref<File | null>(null);
const avatarInput = ref<HTMLInputElement | null>(null);

const currentPassword = ref("");
const newPassword = ref("");
const confirmingPassword = ref("");
const passwordError = ref<string | null>(null);
const passwordPending = ref(false);

const newEmail = ref("");
const oldCode = ref("");
const newCode = ref("");
const ticketGroup = ref<EmailVerificationTicket[]>([]);
const sendingEmailCode = ref(false);
const emailPending = ref(false);
const emailError = ref<string | null>(null);
const emailNotice = ref<string | null>(null);

const nameChanged = computed(
  () => displayName.value.trim() !== session.displayName.value && displayName.value.trim() !== "",
);
const maxNameLength = computed(() => entryLimits.value?.display_name_max_length ?? 24);
const passwordsMatch = computed(
  () => newPassword.value.length > 0 && newPassword.value === confirmingPassword.value,
);

onMounted(() => {
  void ensureEntryContext();
});

async function saveName(): Promise<void> {
  if (!nameChanged.value || savingName.value) return;
  avatarError.value = null;
  savingName.value = true;
  try {
    await updateProfile({ display_name: displayName.value.trim() }, newIdempotencyKey());
    await refreshSession();
    notify.success("显示名称已更新。");
  } catch (caught) {
    avatarError.value = problemMessage(caught);
  } finally {
    savingName.value = false;
  }
}

function onAvatarPicked(event: Event): void {
  const picker = event.target as HTMLInputElement;
  const file = picker.files?.[0];
  picker.value = "";
  if (!file) return;
  avatarError.value = null;
  // Preview the crop first; nothing is uploaded until the user confirms it.
  pendingAvatar.value = file;
}

function cancelCrop(): void {
  pendingAvatar.value = null;
}

async function uploadCropped(cropped: File): Promise<void> {
  pendingAvatar.value = null;
  avatarError.value = null;
  uploadingAvatar.value = true;
  try {
    const fileId = await uploadVerifiedFile("account_avatar", cropped, null, () =>
      newIdempotencyKey(),
    );
    // Design 0.2.6: the avatar is bound through the profile endpoint, not its own route.
    await setAvatar(fileId, newIdempotencyKey());
    await refreshSession();
    notify.success("头像已更新。");
  } catch (caught) {
    avatarError.value = problemMessage(caught);
  } finally {
    uploadingAvatar.value = false;
  }
}

async function clearAvatar(): Promise<void> {
  if (removingAvatar.value) return;
  avatarError.value = null;
  removingAvatar.value = true;
  try {
    await removeAvatar(newIdempotencyKey());
    await refreshSession();
    notify.success("头像已移除，将显示默认标识。");
  } catch (caught) {
    avatarError.value = problemMessage(caught);
  } finally {
    removingAvatar.value = false;
  }
}

async function submitPassword(): Promise<void> {
  if (passwordPending.value) return;
  passwordError.value = null;
  if (!passwordsMatch.value) {
    passwordError.value = "两次输入的新密码不一致。";
    return;
  }
  passwordPending.value = true;
  try {
    await changePassword(
      { current_password: currentPassword.value, new_password: newPassword.value },
      newIdempotencyKey(),
    );
    clearSession();
    clearCaseScopes();
    resetRealtimeCursor();
    resetBadges();
    notify.info("密码已更新，请使用新密码重新登录。");
    await router.replace({ name: "login" });
  } catch (caught) {
    passwordError.value = problemMessage(caught);
  } finally {
    passwordPending.value = false;
  }
}

async function sendEmailCodes(): Promise<void> {
  if (sendingEmailCode.value || newEmail.value.trim().length < 4) return;
  emailError.value = null;
  emailNotice.value = null;
  sendingEmailCode.value = true;
  try {
    const accepted = await requestEmailVerification(
      { purpose: "email_change", email: newEmail.value.trim() },
      newIdempotencyKey(),
    );
    ticketGroup.value = accepted.requests;
    emailNotice.value =
      accepted.requests.length >= 2
        ? "验证码已分别发送到当前邮箱与新邮箱，请填写两组验证码。"
        : "验证码已发送，请填写后确认。";
  } catch (caught) {
    emailError.value = problemMessage(caught);
  } finally {
    sendingEmailCode.value = false;
  }
}

async function submitEmail(): Promise<void> {
  if (emailPending.value || ticketGroup.value.length < 2) return;
  emailError.value = null;
  emailPending.value = true;
  try {
    await changeEmail(
      {
        new_email: newEmail.value.trim(),
        old_verification_id: ticketGroup.value[0].verification_id,
        old_code: oldCode.value.trim(),
        new_verification_id: ticketGroup.value[1].verification_id,
        new_code: newCode.value.trim(),
      },
      newIdempotencyKey(),
    );
    clearSession();
    clearCaseScopes();
    resetRealtimeCursor();
    resetBadges();
    notify.info("邮箱已更换，请使用新邮箱重新登录。");
    await router.replace({ name: "login" });
  } catch (caught) {
    emailError.value = problemMessage(caught);
  } finally {
    emailPending.value = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="我的"
      title="账户设置"
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
          <p class="muted">选择图片后可裁剪为正方形，确认后才会上传。支持 JPG、PNG。</p>
        </div>
      </div>
      <input
        ref="avatarInput"
        type="file"
        accept="image/jpeg,image/png"
        class="visually-hidden"
        @change="onAvatarPicked"
      />
      <p v-if="avatarError" class="field__error" role="alert">{{ avatarError }}</p>
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
      <button
        type="button"
        class="btn btn--primary"
        :disabled="!nameChanged || savingName"
        @click="saveName"
      >
        {{ savingName ? "保存中…" : "保存名称" }}
      </button>
    </section>

    <section class="card">
      <div class="card__head"><h2>登录邮箱</h2></div>
      <dl class="facts">
        <dt>当前邮箱</dt>
        <dd>{{ session.account.value?.email ?? "—" }}</dd>
      </dl>
      <div class="stack">
        <div class="field">
          <label class="field__label" for="new-email">新邮箱</label>
          <div class="inline">
            <input
              id="new-email"
              v-model="newEmail"
              class="input"
              type="email"
              autocomplete="email"
            />
            <button type="button" class="btn" :disabled="sendingEmailCode" @click="sendEmailCodes">
              {{ sendingEmailCode ? "发送中…" : "发送验证码" }}
            </button>
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label class="field__label" for="old-code">当前邮箱验证码</label>
            <input id="old-code" v-model="oldCode" class="input" inputmode="numeric" />
          </div>
          <div class="field">
            <label class="field__label" for="new-code">新邮箱验证码</label>
            <input id="new-code" v-model="newCode" class="input" inputmode="numeric" />
          </div>
        </div>
        <p v-if="emailNotice" class="banner banner--info">{{ emailNotice }}</p>
        <p v-if="emailError" class="field__error" role="alert">{{ emailError }}</p>
        <button
          type="button"
          class="btn btn--primary"
          :disabled="emailPending || ticketGroup.length < 2 || !oldCode || !newCode"
          @click="submitEmail"
        >
          {{ emailPending ? "正在更换…" : "更换邮箱" }}
        </button>
      </div>
    </section>

    <section class="card">
      <div class="card__head">
        <h2>密码</h2>
        <span class="muted">修改后其他设备的登录状态立即失效</span>
      </div>
      <div class="stack">
        <div class="field">
          <label class="field__label" for="current-password">当前密码</label>
          <input
            id="current-password"
            v-model="currentPassword"
            class="input"
            type="password"
            autocomplete="current-password"
          />
        </div>
        <div class="field">
          <label class="field__label" for="new-password">新密码</label>
          <input
            id="new-password"
            v-model="newPassword"
            class="input"
            type="password"
            autocomplete="new-password"
            :minlength="entryLimits?.password_min_length ?? 10"
          />
          <span class="field__hint">{{ passwordRuleText(entryLimits) }}</span>
        </div>
        <div class="field">
          <label class="field__label" for="confirm-password">确认新密码</label>
          <input
            id="confirm-password"
            v-model="confirmingPassword"
            class="input"
            type="password"
            autocomplete="new-password"
          />
        </div>
        <p v-if="passwordError" class="field__error" role="alert">{{ passwordError }}</p>
        <button
          type="button"
          class="btn btn--primary"
          :disabled="passwordPending || !currentPassword || !passwordsMatch"
          @click="submitPassword"
        >
          {{ passwordPending ? "正在保存…" : "修改密码" }}
        </button>
      </div>
    </section>

    <ImageCropper
      v-if="pendingAvatar"
      :file="pendingAvatar"
      :busy="uploadingAvatar"
      @confirm="uploadCropped"
      @cancel="cancelCrop"
    />
  </div>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: minmax(6rem, auto) 1fr;
  gap: var(--space-2) var(--space-4);
  margin: 0 0 var(--space-3);
  font-size: 0.875rem;
}

.facts dt {
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
}
</style>
