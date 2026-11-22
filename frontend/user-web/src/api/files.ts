/*
 * File upload flow: authorise, transfer straight to the private bucket, then ask
 * the backend to verify the stored bytes. Mirrors
 * docs/design/detailed-design/interfaces/文件上传.md.
 */
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

export function createUpload(
  payload: CreateUploadRequest,
  idempotencyKey: string,
): Promise<CreateUploadResult> {
  return request<CreateUploadResult>("POST", "/files/uploads", {
    body: payload,
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
 */
export async function uploadToOss(upload: CreateUploadResult["upload"], file: File): Promise<void> {
  const form = new FormData();
  for (const [key, value] of Object.entries(upload.fields)) form.append(key, value);
  form.append("file", file, file.name);
  const response = await fetch(upload.url, { method: upload.method, body: form });
  if (response.status === 204 || response.ok) return;
  if (response.status === 409) return;
  throw new Error(`对象存储拒绝了上传（HTTP ${response.status}）`);
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
