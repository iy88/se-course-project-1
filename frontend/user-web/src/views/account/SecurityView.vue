<script setup lang="ts">
/*
 * Account security: password change and mailbox change.
 *
 * Both operations invalidate every existing session, so a success sends the user
 * back to the login screen instead of leaving a page that can no longer read
 * anything.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { changeEmail, changePassword, requestEmailVerification } from "../../api/account";
import type { EmailVerificationTicket } from "../../api/contracts";
import { newIdempotencyKey } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { clearSession, session } from "../../app/session";
import { resetBadges } from "../../app/badges";
import { ensureEntryContext, entryLimits, passwordRuleText } from "../../app/entry";
import { notify } from "../../app/toast";
import PageHeader from "../../components/PageHeader.vue";

const router = useRouter();

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

const passwordsMatch = computed(
  () => newPassword.value.length > 0 && newPassword.value === confirmingPassword.value,
);

onMounted(() => {
  void ensureEntryContext();
});

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
      title="账户安全"
      description="修改密码或更换登录邮箱后，其他设备上的登录状态会立即失效。"
    />

    <section class="card">
      <div class="card__head"><h2>当前账户</h2></div>
      <dl class="facts">
        <dt>登录邮箱</dt>
        <dd>{{ session.account.value?.email ?? "—" }}</dd>
        <dt>显示名称</dt>
        <dd>{{ session.displayName.value || "—" }}</dd>
      </dl>
    </section>

    <section class="card">
      <div class="card__head"><h2>修改密码</h2></div>
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

    <section class="card">
      <div class="card__head"><h2>更换登录邮箱</h2></div>
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
  </div>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: minmax(6rem, auto) 1fr;
  gap: var(--space-2) var(--space-4);
  margin: 0;
  font-size: 0.875rem;
}

.facts dt {
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
}
</style>
