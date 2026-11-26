/*
 * Account, session, profile and avatar use cases.
 * Paths and payloads follow docs/design/detailed-design/interfaces/账户与通知.md.
 */
import { request } from "./http";
import type {
  ChangeEmailRequest,
  ChangePasswordRequest,
  CurrentIdentity,
  EmailVerificationAccepted,
  EmailVerificationRequest,
  EntryContext,
  LoginRequest,
  RegisterRequest,
  RegisterResult,
  ResetPasswordRequest,
  UpdateProfileRequest,
  UpdateProfileResult,
} from "./contracts";

/**
 * CSRF token of the current anonymous entry context.
 *
 * Anonymous writes (registration, login, verification request, password reset) are
 * guarded by the entry cookie and this token, so it is captured when the context is
 * read and replayed on those calls.
 */
let entryCsrfToken: string | null = null;

/** The captured entry token, exposed for tests and diagnostics. */
export function currentEntryCsrfToken(): string | null {
  return entryCsrfToken;
}

export function readCurrentIdentity(signal?: AbortSignal): Promise<CurrentIdentity> {
  return request<CurrentIdentity>("GET", "/account/session", { signal });
}

export function login(payload: LoginRequest, idempotencyKey: string): Promise<CurrentIdentity> {
  return request<CurrentIdentity>("POST", "/account/session", {
    body: payload,
    idempotencyKey,
    csrfToken: entryCsrfToken ?? undefined,
  });
}

export function logout(): Promise<void> {
  return request<void>("DELETE", "/account/session");
}

export function readEntryContext(signal?: AbortSignal): Promise<EntryContext> {
  return request<EntryContext>("GET", "/account/entry-context", { signal }).then((context) => {
    entryCsrfToken = context.csrf_token;
    return context;
  });
}

export function requestEmailVerification(
  payload: EmailVerificationRequest,
  idempotencyKey: string,
): Promise<EmailVerificationAccepted> {
  return request<EmailVerificationAccepted>("POST", "/account/email-verifications", {
    body: payload,
    idempotencyKey,
    csrfToken: entryCsrfToken ?? undefined,
  });
}

export function register(
  payload: RegisterRequest,
  idempotencyKey: string,
): Promise<RegisterResult> {
  return request<RegisterResult>("POST", "/accounts", {
    body: payload,
    idempotencyKey,
    csrfToken: entryCsrfToken ?? undefined,
  });
}

export function updateProfile(
  payload: UpdateProfileRequest,
  idempotencyKey: string,
): Promise<UpdateProfileResult> {
  return request<UpdateProfileResult>("PATCH", "/account/profile", {
    body: payload,
    idempotencyKey,
  });
}

export function changePassword(
  payload: ChangePasswordRequest,
  idempotencyKey: string,
): Promise<void> {
  return request<void>("PUT", "/account/password", { body: payload, idempotencyKey });
}

export function resetPassword(
  payload: ResetPasswordRequest,
  idempotencyKey: string,
): Promise<void> {
  return request<void>("POST", "/account/password-resets", {
    body: payload,
    idempotencyKey,
    csrfToken: entryCsrfToken ?? undefined,
  });
}

export function changeEmail(
  payload: ChangeEmailRequest,
  idempotencyKey: string,
): Promise<{ account_id: string; email: string }> {
  return request<{ account_id: string; email: string }>("PUT", "/account/email", {
    body: payload,
    idempotencyKey,
  });
}

/** Set or replace the avatar with a verified `account_avatar` file. */
export function setAvatar(fileId: string, idempotencyKey: string): Promise<UpdateProfileResult> {
  return updateProfile({ avatar_file_id: fileId }, idempotencyKey);
}

/** Remove the current avatar with an explicit `null`; the interface then shows the default. */
export function removeAvatar(idempotencyKey: string): Promise<UpdateProfileResult> {
  return updateProfile({ avatar_file_id: null }, idempotencyKey);
}
