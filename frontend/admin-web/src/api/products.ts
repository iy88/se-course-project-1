/* Administrator product operations owned by the product module (API-PRD-032). */
import { request } from "./http";
import type { CategoryCorrectionRequest, CategoryCorrectionResult } from "./contracts";

export function correctProductCategory(
  productId: string,
  payload: CategoryCorrectionRequest,
  idempotencyKey: string,
): Promise<CategoryCorrectionResult> {
  return request<CategoryCorrectionResult>(
    "POST",
    `/admin/products/${encodeURIComponent(productId)}/category-correction`,
    { body: payload, idempotencyKey },
  );
}
