/*
 * File upload flow: authorise, transfer straight to the private bucket, then ask
 * the backend to verify the stored bytes. Mirrors
 * docs/design/detailed-design/interfaces/文件上传.md.
 */
import { ApiError } from "./errors";
import { request } from "./http";
import type {
  CompleteUploadResult,
  CreateUploadRequest,
  CreateUploadResult,
  FilePurpose,
  UploadCapabilities,
} from "./contracts";

export function readUploadCapabilities(signal?: AbortSignal): Promise<UploadCapabilities> {
  return request<UploadCapabilities>("GET", "/files/upload-capabilities", { signal });
}

/**
 * Request body of `POST /files/uploads`.
 *
 * A null target is sent as an omitted key: the server derives the account for
 * `account_avatar` from the session and requires no target for staged
 * `product_image` or `case_evidence` uploads.
 */
export function uploadRequestBody(payload: CreateUploadRequest): Record<string, unknown> {
  const body: Record<string, unknown> = {
    purpose: payload.purpose,
    declared_size: payload.declared_size,
    declared_content_type: payload.declared_content_type,
  };
  if (payload.target) body.target = payload.target;
  return body;
}

export function createUpload(
  payload: CreateUploadRequest,
  idempotencyKey: string,
): Promise<CreateUploadResult> {
  return request<CreateUploadResult>("POST", "/files/uploads", {
    body: uploadRequestBody(payload),
    idempotencyKey,
  });
}

export function completeUpload(
  fileId: string,
  idempotencyKey: string,
): Promise<CompleteUploadResult> {
  return request<CompleteUploadResult>("POST", `/files/${fileId}/completion`, {
    body: {},
    idempotencyKey,
  });
}

/**
 * Post the signed form and the bytes to the bucket entry point.
 *
 * The browser must send exactly the fields the backend signed; appending the
 * `file` part last is required by the OSS PostObject contract. A 204 answer is
 * the success signal, and an already existing object also resolves so the caller
 * can continue to verification.
 *
 * A transport failure (bucket unreachable, CORS, offline) is reported as a
 * retryable domain error instead of the browser's raw "Failed to fetch".
 */
export async function uploadToOss(upload: CreateUploadResult["upload"], file: File): Promise<void> {
  const form = new FormData();
  for (const [key, value] of Object.entries(upload.fields)) form.append(key, value);
  form.append("file", file, file.name);
  let response: Response;
  try {
    response = await fetch(upload.url, { method: upload.method, body: form });
  } catch {
    throw new ApiError(0, "UPLOAD_TRANSFER_FAILED", "无法连接对象存储，请检查网络后重试。");
  }
  if (response.status === 204 || response.ok) return;
  if (response.status === 409) return;
  throw new ApiError(
    0,
    "UPLOAD_TRANSFER_FAILED",
    `对象存储拒绝了上传（HTTP ${response.status}），请重新选择文件。`,
  );
}

/** Authorise, transfer and verify one file, returning the verified file id. */
export async function uploadVerifiedFile(
  purpose: FilePurpose,
  file: File,
  target: CreateUploadRequest["target"],
  keyFactory: () => string,
): Promise<string> {
  const created = await createUpload(
    {
      purpose,
      declared_size: file.size,
      declared_content_type: file.type,
      target,
    },
    keyFactory(),
  );
  await uploadToOss(created.upload, file);
  const verified = await completeUpload(created.file_id, keyFactory());
  return verified.file_id;
}
