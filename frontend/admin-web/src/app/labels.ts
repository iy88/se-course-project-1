/* Copy for the administrative enumerations shown in the interface. */
import type { BannedGroupKey } from "../api/contracts";

export const bannedGroupLabels: Record<BannedGroupKey, string> = {
  legal_prohibited: "法律法规禁止",
  dangerous_controlled: "危险与管制物品",
  live_animals: "活体动物",
  medicine_device: "药品与医疗器械",
  account_virtual: "账号与虚拟资产",
  service_promotion: "服务推广",
  other: "其他",
};

export const bannedGroupOrder: BannedGroupKey[] = [
  "legal_prohibited",
  "dangerous_controlled",
  "live_animals",
  "medicine_device",
  "account_virtual",
  "service_promotion",
  "other",
];

export const reviewStatusLabels: Record<string, string> = {
  pending: "待审核",
  passed: "已通过",
  rejected: "未通过",
  withdrawn: "已撤回",
};

export const lifecycleLabels: Record<string, string> = {
  pending_review: "待审核",
  review_rejected: "审核未通过",
  public: "公开可交易",
  in_trade: "交易中",
  off_shelf: "已下架",
};

export const reviewDecisionLabels: Record<string, string> = {
  approved: "通过",
  rejected: "不通过",
  passed: "通过",
};

export const categoryStateLabels: Record<string, string> = {
  active: "有效",
  disabled: "已停用",
};

export const ownershipLabels: Record<"unclaimed" | "mine", string> = {
  unclaimed: "待认领",
  mine: "我的认领",
};
