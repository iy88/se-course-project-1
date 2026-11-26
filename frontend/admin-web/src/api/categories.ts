/* Category maintenance endpoints (API-PRD-015—021). */
import { request } from "./http";
import type { CategoryDetail, Page } from "./contracts";

export interface CategoryPageQuery {
  page: number;
  page_size: number;
}

export function listAdminCategories(
  query: CategoryPageQuery,
  signal?: AbortSignal,
): Promise<Page<CategoryDetail>> {
  return request<Page<CategoryDetail>>("GET", "/admin/categories", {
    query: { page: query.page, page_size: query.page_size },
    signal,
  });
}

/**
 * The review correction picker needs the complete active category directory.
 * The maintenance table itself uses the paginated query above.
 */
export async function listAllAdminCategories(signal?: AbortSignal): Promise<CategoryDetail[]> {
  const pageSize = 100;
  const result: CategoryDetail[] = [];
  for (let page = 1; ; page += 1) {
    const current = await listAdminCategories({ page, page_size: pageSize }, signal);
    result.push(...current.items);
    if (result.length >= current.total || current.items.length === 0) return result;
  }
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
