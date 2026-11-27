import type { CaseRelatedAccount, ManagementCaseDetail } from "../api/cases";

const targetLabels = {
  account: "账户",
  product: "商品",
  comment: "评论",
  evaluation: "评价",
  trade: "交易",
};

type TargetKind = keyof typeof targetLabels;
type DispositionDetail = Pick<
  ManagementCaseDetail,
  "related_accounts" | "disposition_targets" | "reported_object"
>;

interface Choice {
  id: string;
  label: string;
}

/** Candidate projection only; the server still validates every submitted enforcement. */
export function dispositionTargets(
  detail: DispositionDetail | undefined,
  target: TargetKind,
  accountLabel: (account: CaseRelatedAccount) => string,
): Choice[] {
  const disposition = detail?.disposition_targets;
  const reported = detail?.reported_object;
  if (target === "account") {
    return (detail?.related_accounts ?? [])
      .filter((account) => account.eligible)
      .map((account) => ({ id: account.account_id, label: accountLabel(account) }));
  }
  if (target === "product") {
    const products =
      disposition?.products ??
      (reported?.target_type === "product"
        ? [{ id: reported.target_id, title: reported.product?.title ?? "商品" }]
        : []);
    return products.map((product) => ({
      id: product.id,
      label: `${product.title} #${product.id}`,
    }));
  }
  const subject = disposition ?? reported;
  return subject?.target_type === target
    ? [{ id: subject.target_id, label: `${targetLabels[target]} #${subject.target_id}` }]
    : [];
}

export function resolveDispositionTarget(choices: Choice[], selectedId: string): Choice | undefined {
  return choices.length === 1 ? choices[0] : choices.find(({ id }) => id === selectedId);
}
