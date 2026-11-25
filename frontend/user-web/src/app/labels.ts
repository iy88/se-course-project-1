/*
 * Presentation labels for the enumerations used by the API.
 *
 * Kept free of any HTTP or Vue dependency so it can be unit tested and reused by
 * tests describing expected copy.
 */
import type {
  AgreementStatus,
  BannedGroup,
  CaseDecisionKind,
  CaseMessageKind,
  CaseStatus,
  DecisionKind,
  MessageSenderKind,
  NotificationReadFilter,
  ProductLifecycle,
  ReviewStatus,
  TodoKind,
  TradeAction,
  TradeStatus,
} from "../api/contracts";

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

export const tradeStatusLabels: Record<TradeStatus, string> = {
  pending_acceptance: "待接受",
  rejected: "已拒绝",
  withdrawn: "已撤回",
  closed: "已关闭",
  in_progress: "交易中",
  disputed: "争议中",
  abnormal: "异常处理中",
  terminated: "已终止",
  completed: "已完成",
};

export const tradeStatusTones: Record<TradeStatus, Tone> = {
  pending_acceptance: "warn",
  rejected: "neutral",
  withdrawn: "neutral",
  closed: "neutral",
  in_progress: "ok",
  disputed: "danger",
  abnormal: "danger",
  terminated: "neutral",
  completed: "ok",
};

export const productLifecycleLabels: Record<ProductLifecycle, string> = {
  pending_review: "待审核",
  review_rejected: "审核未通过",
  public: "在售",
  in_trade: "交易中",
  off_shelf: "已下架",
};

export const productLifecycleTones: Record<ProductLifecycle, Tone> = {
  pending_review: "warn",
  review_rejected: "danger",
  public: "ok",
  in_trade: "info",
  off_shelf: "neutral",
};

export const reviewStatusLabels: Record<ReviewStatus, string> = {
  pending: "待审核",
  passed: "已通过",
  rejected: "未通过",
  withdrawn: "已撤回",
};

export const agreementStatusLabels: Record<AgreementStatus, string> = {
  proposed: "待回应",
  effective: "已生效",
  rejected: "已拒绝",
  withdrawn: "已撤回",
  superseded: "已被替代",
};

export const caseStatusLabels: Record<CaseStatus, string> = {
  pending: "待认领",
  claimed: "处理中",
  decided: "已决定",
};

export const caseStatusTones: Record<CaseStatus, Tone> = {
  pending: "warn",
  claimed: "info",
  decided: "ok",
};

export const caseDecisionLabels: Record<CaseDecisionKind, string> = {
  no_action: "无需处理",
  not_actionable: "不予处理",
  violation: "违规成立",
};

export const decisionLabels: Record<DecisionKind, string> = {
  accept: "同意",
  reject: "拒绝",
  withdraw: "撤回",
};

export const tradeActionLabels: Record<TradeAction, string> = {
  accept: "接受请求",
  reject: "拒绝请求",
  withdraw: "撤回请求",
  propose_agreement: "提出约定",
  decide_agreement: "回应约定",
  submit_confirmation: "提交完成确认",
  propose_cancellation: "申请取消",
  decide_cancellation: "回应取消申请",
  open_dispute: "发起争议",
  confirm_dispute_resolution: "确认争议已解决",
};

export const bannedGroupLabels: Record<BannedGroup, string> = {
  legal_prohibited: "违法违规物品",
  dangerous_controlled: "易燃易爆与危险化学品",
  live_animals: "活体动物",
  medicine_device: "药品与医疗器械",
  account_virtual: "账号与虚拟资产",
  service_promotion: "服务推广",
  other: "其他",
};

export const todoKindLabels: Record<TodoKind, string> = {
  request_response: "待处理购买请求",
  agreement_response: "待回应交易约定",
  completion_response: "待确认交付完成",
  cancellation_response: "待回应取消申请",
  inquiry_response: "待回复管理问询",
};

export const notificationReadLabels: Record<NotificationReadFilter, string> = {
  all: "全部",
  unread: "未读",
  read: "已读",
};

export const caseMessageKindLabels: Record<CaseMessageKind, string> = {
  inquiry: "管理问询",
  statement: "说明",
  appeal: "申辩",
  manager_reply: "管理员回复",
  system: "系统消息",
};

export const senderKindLabels: Record<MessageSenderKind, string> = {
  user: "用户",
  system: "系统",
  manager: "管理员",
  peer: "对方",
};

/**
 * Notification event types are dot-separated names registered by the owning
 * module. The user interface only needs a readable group label.
 */
export function notificationTypeLabel(eventType: string): string {
  const [group] = eventType.split(".");
  const groups: Record<string, string> = {
    trade: "交易",
    product_audit: "商品审核",
    product_comment: "商品评论",
    case: "事项",
    account: "账户",
    conversation: "会话",
  };
  return groups[group] ?? "通知";
}

/** Tail of the trade lifecycle shown as progress on the detail page. */
export function tradeStageLabel(status: TradeStatus, phase: string | null | undefined): string {
  if (status === "in_progress") {
    if (phase === "first_agreement_pending") return "等待约定生效";
    if (phase === "awaiting_completion") return "等待双方完成确认";
    return "交易进行中";
  }
  return tradeStatusLabels[status];
}
