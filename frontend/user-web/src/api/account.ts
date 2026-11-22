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

export function readCurrentIdentity(signal?: AbortSignal): Promise<CurrentIdentity> {
  return request<CurrentIdentity>("GET", "/account/session", { signal });
}

export function login(payload: LoginRequest, idempotencyKey: string): Promise<CurrentIdentity> {
  return request<CurrentIdentity>("POST", "/account/session", {
    body: payload,
    idempotencyKey,
  });
}

export function logout(): Promise<void> {
  return request<void>("DELETE", "/account/session");
}

export function readEntryContext(signal?: AbortSignal): Promise<EntryContext> {
  return request<EntryContext>("GET", "/account/entry-context", { signal });
}

export function requestEmailVerification(
  payload: EmailVerificationRequest,
  idempotencyKey: string,
): Promise<EmailVerificationAccepted> {
  return request<EmailVerificationAccepted>("POST", "/account/email-verifications", {
    body: payload,
    idempotencyKey,
  });
}

export function register(
  payload: RegisterRequest,
  idempotencyKey: string,
): Promise<RegisterResult> {
  return request<RegisterResult>("POST", "/accounts", { body: payload, idempotencyKey });
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

/** Remove the current avatar; the interface then shows the default. */
export function removeAvatar(idempotencyKey: string): Promise<UpdateProfileResult> {
  return updateProfile({ avatar_file_id: null }, idempotencyKey);
}
