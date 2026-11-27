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
  TradeView,
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

export function tradeTerminalReasonLabel(
  reason: TradeView["terminal_reason"],
  bothConfirmed: boolean,
  history: TradeView["state_history"],
): string | null {
  switch (reason) {
    case "completed":
      if (
        history?.some((entry) => entry.action === "trade.completed" && entry.actor_kind === "admin")
      ) {
        return "管理员处置完成";
      }
      return bothConfirmed ? "双方确认完成" : "交易已完成";
    case "cancelled":
      return "已取消";
    case "admin_terminated":
      return "管理终止";
    default:
      return null;
  }
}

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

/**
 * Progress rows, enforcement actions and their state snapshots.
 *
 * The API keeps the registered names; only the rendering is translated. Values the
 * client does not know yet fall back to a neutral phrase instead of leaking a raw
 * identifier into the interface.
 */
export const caseActionKindLabels: Record<string, string> = {
  submit: "提交举报",
  supplement: "补充材料",
  claim: "认领事项",
  inquire: "发起问询",
  statement: "提交说明",
  appeal: "提交申辩",
  manager_reply: "管理员回复",
  decide: "作出决定",
  close: "结案归档",
  execute: "执行处置",
  lift: "解除处置",
  publish_result: "公开结果",
};

export const caseActorKindLabels: Record<string, string> = {
  account: "相关账户",
  manager: "管理员",
  system: "系统",
};

export const enforcementActionLabels: Record<string, string> = {
  restrict_account: "账户限制",
  lift_account_restriction: "解除账户限制",
  withdraw_public_access: "撤销商品公开访问",
  remove_content: "移除违规内容",
  restore_display: "恢复商品展示",
  freeze_trade: "冻结交易",
  lift_trade_freeze: "解除交易冻结",
  adjust_trade_status: "调整交易状态",
  remove_evaluation_content: "移除违规评价",
};

export const enforcementStateLabels: Record<string, string> = {
  applied: "已生效",
  replayed: "已生效",
  failed: "执行失败",
  restricted: "受限",
  restricted_account: "账户受限",
  restricted_display: "停止公开展示",
  released: "已解除",
  visible: "正常展示",
  frozen: "已冻结",
  active: "进行中",
  in_progress: "进行中",
  closed: "已关闭",
  removed: "已移除",
};

/** Neutral fallbacks so an unknown server value still reads as Chinese copy. */
export function caseActionKindText(value: string): string {
  return caseActionKindLabels[value] ?? "其他处理";
}

export function caseActorKindText(value: string): string {
  return caseActorKindLabels[value] ?? "参与方";
}

export function enforcementActionText(value: string): string {
  return enforcementActionLabels[value] ?? "处置措施";
}

export function enforcementStateText(value: string): string {
  return enforcementStateLabels[value] ?? "已记录";
}

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

/**
 * Reason copy for one review outcome: only a rejection is a rejection reason.
 * An approved review may carry an explanation for the seller.
 */
export function reviewReasonLabel(status: ReviewStatus): string {
  return status === "rejected" ? "拒绝原因" : "审核说明";
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
