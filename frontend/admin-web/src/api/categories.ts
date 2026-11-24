/* Category maintenance endpoints (API-PRD-015—021). */
import { request } from "./http";
import type { CategoryDetail } from "./contracts";

export function listAdminCategories(signal?: AbortSignal): Promise<{ items: CategoryDetail[] }> {
  return request<{ items: CategoryDetail[] }>("GET", "/admin/categories", { signal });
}

export function createCategory(name: string, idempotencyKey: string): Promise<CategoryDetail> {
  return request<CategoryDetail>("POST", "/admin/categories", {
    body: { name },
    idempotencyKey,
  });
}

export function renameCategory(
  categoryId: string,
  mainName: string,
  idempotencyKey: string,
): Promise<CategoryDetail> {
  return request<CategoryDetail>("PATCH", `/admin/categories/${categoryId}`, {
    body: { main_name: mainName },
    idempotencyKey,
  });
}

export function addCategoryAlias(
  categoryId: string,
  name: string,
  idempotencyKey: string,
): Promise<{ category_name_id: string; name: string }> {
  return request<{ category_name_id: string; name: string }>(
    "POST",
    `/admin/categories/${categoryId}/aliases`,
    { body: { name }, idempotencyKey },
  );
}

export function removeCategoryAlias(
  categoryId: string,
  categoryNameId: string,
  idempotencyKey: string,
): Promise<void> {
  return request<void>("DELETE", `/admin/categories/${categoryId}/aliases/${categoryNameId}`, {
    idempotencyKey,
  });
}

export function disableCategory(
  categoryId: string,
  idempotencyKey: string,
): Promise<CategoryDetail> {
  return request<CategoryDetail>("POST", `/admin/categories/${categoryId}/disable`, {
    idempotencyKey,
  });
}

export function deleteCategory(categoryId: string, idempotencyKey: string): Promise<void> {
  return request<void>("DELETE", `/admin/categories/${categoryId}`, { idempotencyKey });
}
