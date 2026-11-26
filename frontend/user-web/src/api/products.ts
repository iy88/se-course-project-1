/*
 * Product and category use cases for the seller-facing user interface.
 * Paths and payloads follow docs/design/detailed-design/interfaces/商品与分类.md.
 */
import { request } from "./http";
import type {
  BannedScopeView,
  CategoryView,
  CommentPage,
  CommentView,
  CreateProductRequest,
  FavoritePage,
  FavoriteStatus,
  Page,
  ProductDetail,
  ProductEditSnapshot,
  ProductSummary,
  SearchProductsQuery,
  UpdateProductRequest,
} from "./contracts";

export function listCategories(signal?: AbortSignal): Promise<{ items: CategoryView[] }> {
  return request<{ items: CategoryView[] }>("GET", "/categories", { signal });
}

export function readBannedScope(signal?: AbortSignal): Promise<BannedScopeView> {
  return request<BannedScopeView>("GET", "/banned-items", { signal });
}

export function searchProducts(
  query: SearchProductsQuery,
  signal?: AbortSignal,
): Promise<Page<ProductSummary>> {
  return request<Page<ProductSummary>>("GET", "/products", {
    query,
    signal,
  });
}

export function getProduct(productId: string, signal?: AbortSignal): Promise<ProductDetail> {
  return request<ProductDetail>("GET", `/products/${productId}`, { signal });
}

export function createProduct(
  payload: CreateProductRequest,
  idempotencyKey: string,
): Promise<ProductDetail> {
  return request<ProductDetail>("POST", "/products", { body: payload, idempotencyKey });
}

export function updateProduct(
  productId: string,
  payload: UpdateProductRequest,
  idempotencyKey: string,
): Promise<ProductDetail> {
  return request<ProductDetail>("PATCH", `/products/${productId}`, {
    body: payload,
    idempotencyKey,
  });
}

export function resubmitForReview(
  productId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<{
  audit_id: string;
  case_id: string;
  lifecycle_state: string;
  content_version: number;
}> {
  return request("POST", `/products/${productId}/review-submissions`, {
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

export function withdrawPendingProduct(
  productId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<{
  lifecycle_state: string;
  audit_status: string;
  category_application_status: string | null;
  content_version: number;
}> {
  return request("POST", `/products/${productId}/withdrawal`, {
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

export function takeOffShelf(
  productId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<{ product: ProductDetail; closed_pending_request_count: number }> {
  return request("POST", `/products/${productId}/off-shelf`, {
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

export function putOnShelf(
  productId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<ProductDetail> {
  return request<ProductDetail>("POST", `/products/${productId}/on-shelf`, {
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

export function listEditHistory(
  productId: string,
  page: number,
  pageSize: number,
  tradeId?: string,
  signal?: AbortSignal,
): Promise<Page<ProductEditSnapshot>> {
  return request<Page<ProductEditSnapshot>>("GET", `/products/${productId}/edit-history`, {
    query: { page, page_size: pageSize, trade_id: tradeId },
    signal,
  });
}

export function listProductComments(
  productId: string,
  query: { page?: number; page_size?: number; case_id?: string; anchor_comment_id?: string },
  signal?: AbortSignal,
): Promise<CommentPage> {
  return request<CommentPage>("GET", `/products/${productId}/comments`, { query, signal });
}

export function createProductComment(
  productId: string,
  body: string,
  idempotencyKey: string,
): Promise<CommentView> {
  return request<CommentView>("POST", `/products/${productId}/comments`, {
    body: { body },
    idempotencyKey,
  });
}

export function replyToProductComment(
  productId: string,
  commentId: string,
  body: string,
  idempotencyKey: string,
): Promise<CommentView> {
  return request<CommentView>("POST", `/products/${productId}/comments/${commentId}/replies`, {
    body: { body },
    idempotencyKey,
  });
}

export function deleteProductComment(
  productId: string,
  commentId: string,
  idempotencyKey: string,
): Promise<void> {
  return request<void>("DELETE", `/products/${productId}/comments/${commentId}`, {
    idempotencyKey,
  });
}

export function listMyFavorites(
  query: { page?: number; page_size?: number },
  signal?: AbortSignal,
): Promise<FavoritePage> {
  return request<FavoritePage>("GET", "/me/favorites", { query, signal });
}

export function getFavoriteStatus(
  productId: string,
  signal?: AbortSignal,
): Promise<FavoriteStatus> {
  return request<FavoriteStatus>("GET", `/me/favorites/${productId}`, { signal });
}

export function addFavorite(productId: string, idempotencyKey: string): Promise<FavoriteStatus> {
  return request<FavoriteStatus>("PUT", `/me/favorites/${productId}`, { idempotencyKey });
}

export function removeFavorite(productId: string, idempotencyKey: string): Promise<void> {
  return request<void>("DELETE", `/me/favorites/${productId}`, { idempotencyKey });
}
