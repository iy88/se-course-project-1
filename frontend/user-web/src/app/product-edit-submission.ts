/*
 * Complete an editable product submission.
 *
 * The server remains the permission authority: only a product whose updated
 * projection allows another review submission is resubmitted. Other edits are
 * saved without creating a review case.
 */
import type { ProductDetail } from "../api/contracts";

export interface ProductEditSubmissionResult {
  product: ProductDetail;
  resubmitted: boolean;
}

export async function saveProductEditAndResubmit(
  update: () => Promise<ProductDetail>,
  resubmit: (product: ProductDetail) => Promise<unknown>,
): Promise<ProductEditSubmissionResult> {
  const product = await update();
  if (!product.permissions?.can_submit_review) {
    return { product, resubmitted: false };
  }
  await resubmit(product);
  return { product, resubmitted: true };
}
