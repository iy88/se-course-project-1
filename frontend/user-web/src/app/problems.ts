/*
 * Translates API failure codes into copy the user can act on.
 *
 * Interface text states the operation, its result and the error only; the
 * mapping keeps that rule in one place so every screen reports the same cause
 * with the same wording.
 */
import { ApiError } from "../api/errors";

interface ProblemCopy {
  /** Short sentence shown next to the failing control or at the top of a panel. */
  message: string;
  /** True when re-running the same request can plausibly succeed. */
  retryable: boolean;
  /** True when the session must be re-established before anything else works. */
  requiresLogin: boolean;
}

const copy: Record<string, ProblemCopy> = {
  AUTHENTICATION_REQUIRED: {
    message: "登录状态已失效，请重新登录后继续。",
    retryable: false,
    requiresLogin: true,
  },
  AUTHENTICATION_UNAVAILABLE: {
    message: "登录状态暂时无法确认，请稍后重试。",
    retryable: true,
    requiresLogin: false,
  },
  CREDENTIALS_INVALID: {
    message: "邮箱或密码不正确。",
    retryable: false,
    requiresLogin: false,
  },
  CSRF_INVALID: {
    message: "页面状态已过期，请刷新页面后重试。",
    retryable: true,
    requiresLogin: false,
  },
  ACCOUNT_WRITE_RESTRICTED: {
    message: "当前账户处于限制状态，该操作暂不可用。",
    retryable: false,
    requiresLogin: false,
  },
  ACTION_NOT_ALLOWED: {
    message: "当前身份不能执行该操作。",
    retryable: false,
    requiresLogin: false,
  },
  RESOURCE_NOT_VISIBLE: {
    message: "内容不存在，或你当前无权查看。",
    retryable: false,
    requiresLogin: false,
  },
  STATE_CONFLICT: {
    message: "状态已变化，请刷新后按最新状态重试。",
    retryable: true,
    requiresLogin: false,
  },
  VERSION_CONFLICT: {
    message: "内容已被更新，请刷新后重试。",
    retryable: true,
    requiresLogin: false,
  },
  IDEMPOTENCY_PAYLOAD_CONFLICT: {
    message: "本次操作与之前的请求不一致，请返回后重新提交。",
    retryable: false,
    requiresLogin: false,
  },
  INPUT_INVALID: {
    message: "填写内容不符合要求，请检查后重试。",
    retryable: false,
    requiresLogin: false,
  },
  RATE_LIMITED: {
    message: "操作过于频繁，请稍后再试。",
    retryable: true,
    requiresLogin: false,
  },
  DEPENDENCY_UNAVAILABLE: {
    message: "依赖服务暂时不可用，请稍后重试。",
    retryable: true,
    requiresLogin: false,
  },
  STORAGE_UNAVAILABLE: {
    message: "文件服务暂时不可用，请稍后重试。",
    retryable: true,
    requiresLogin: false,
  },
  NETWORK_UNAVAILABLE: {
    message: "网络不可用，请检查连接后重试。",
    retryable: true,
    requiresLogin: false,
  },
  UNEXPECTED_RESPONSE: {
    message: "服务返回了无法识别的结果，请稍后重试。",
    retryable: true,
    requiresLogin: false,
  },
  UNEXPECTED_ERROR: {
    message: "操作未能完成，请稍后重试。",
    retryable: true,
    requiresLogin: false,
  },

  /* account */
  EMAIL_IN_USE: { message: "该邮箱已被使用，请更换邮箱。", retryable: false, requiresLogin: false },
  EMAIL_UNCHANGED: { message: "新邮箱与当前邮箱相同。", retryable: false, requiresLogin: false },
  CURRENT_PASSWORD_INVALID: {
    message: "当前密码不正确。",
    retryable: false,
    requiresLogin: false,
  },
  VERIFICATION_CODE_INVALID: {
    message: "验证码不正确或已失效，请重新获取。",
    retryable: false,
    requiresLogin: false,
  },
  VERIFICATION_NOT_USABLE: {
    message: "该验证码已被使用或已过期，请重新获取。",
    retryable: false,
    requiresLogin: false,
  },
  SELF_CONVERSATION_FORBIDDEN: {
    message: "不能与自己建立会话。",
    retryable: false,
    requiresLogin: false,
  },

  /* files */
  FILE_ACTION_NOT_ALLOWED: {
    message: "该文件不属于当前账户，或当前状态下不能使用。",
    retryable: false,
    requiresLogin: false,
  },
  FILE_PURPOSE_MISMATCH: {
    message: "文件用途不符，请重新选择文件。",
    retryable: false,
    requiresLogin: false,
  },
  FILE_METADATA_INVALID: {
    message: "文件大小或格式不符合要求。",
    retryable: false,
    requiresLogin: false,
  },
  FILE_CONTENT_INVALID: {
    message: "文件内容未通过校验，请更换文件后重试。",
    retryable: false,
    requiresLogin: false,
  },
  FILE_UPLOAD_INCOMPLETE: {
    message: "文件尚未上传完成，请重试。",
    retryable: true,
    requiresLogin: false,
  },
  FILE_NOT_REFERENCEABLE: {
    message: "文件当前不可引用，请重新上传。",
    retryable: false,
    requiresLogin: false,
  },
  FILE_CONTENT_CHANGED: {
    message: "文件内容在上传后发生变化，请重新上传。",
    retryable: false,
    requiresLogin: false,
  },
  UPLOAD_AUTH_EXPIRED: {
    message: "上传授权已过期，请重新选择文件。",
    retryable: false,
    requiresLogin: false,
  },
  UPLOAD_TRANSFER_FAILED: {
    message: "无法连接对象存储，请检查网络后重试。",
    retryable: true,
    requiresLogin: false,
  },
  STORAGE_CONFIGURATION_INVALID: {
    message: "文件服务配置异常，请联系管理员。",
    retryable: false,
    requiresLogin: false,
  },

  /* products */
  CATEGORY_REQUIRED: {
    message: "请至少选择一个分类，或提交新分类申请。",
    retryable: false,
    requiresLogin: false,
  },
  CATEGORY_NOT_SELECTABLE: {
    message: "所选分类当前不可选择，请重新选择。",
    retryable: false,
    requiresLogin: false,
  },
  CATEGORY_APPLICATION_CONFLICT: {
    message: "该商品已有待处理的分类申请。",
    retryable: false,
    requiresLogin: false,
  },
  TRADE_FROZEN: {
    message: "交易冻结期间不能发布、上下架商品。",
    retryable: false,
    requiresLogin: false,
  },
  PRODUCT_LOCKED: {
    message: "商品存在未结束的占用，不能主动下架。",
    retryable: false,
    requiresLogin: false,
  },
  PRODUCT_NOT_RELISTABLE: {
    message: "商品最新审核未通过，不能重新上架。",
    retryable: false,
    requiresLogin: false,
  },
  DISPLAY_RESTRICTED: {
    message: "商品存在生效中的展示限制，当前不能上架。",
    retryable: false,
    requiresLogin: false,
  },
  EDIT_NOT_ALLOWED_IN_TRADE: {
    message: "交易中的商品不能修改关键内容。",
    retryable: false,
    requiresLogin: false,
  },
  PRODUCT_NOT_RESUBMITTABLE: {
    message: "当前状态不能重新提交审核。",
    retryable: false,
    requiresLogin: false,
  },
  REVIEW_NOT_PENDING: {
    message: "该审核已有结论，无需重复处理。",
    retryable: false,
    requiresLogin: false,
  },
  REVIEW_ALREADY_CLAIMED: {
    message: "审核已被管理员认领，不能撤回商品。",
    retryable: false,
    requiresLogin: false,
  },

  /* trade */
  PRODUCT_NOT_AVAILABLE: {
    message: "商品当前不可交易，请刷新后查看最新状态。",
    retryable: true,
    requiresLogin: false,
  },
  OCCUPANCY_CONFLICT: {
    message: "该商品已被其他交易锁定。",
    retryable: false,
    requiresLogin: false,
  },
  OCCUPANCY_NOT_HELD: {
    message: "该交易当前未持有商品占用。",
    retryable: false,
    requiresLogin: false,
  },
  REQUEST_ALREADY_ENDED: {
    message: "该购买请求已经结束，请刷新列表。",
    retryable: true,
    requiresLogin: false,
  },
  TRADE_NOT_COMPLETED: {
    message: "交易完成后才可以评价。",
    retryable: false,
    requiresLogin: false,
  },
  REVIEW_ALREADY_SUBMITTED: {
    message: "你已评价过本笔交易。",
    retryable: false,
    requiresLogin: false,
  },
  TRADE_TERMINAL: {
    message: "交易已结束，不能执行该操作。",
    retryable: false,
    requiresLogin: false,
  },

  /* conversations */
  PARTICIPANT_REQUIRED: {
    message: "会话不存在，或你当前无权查看。",
    retryable: false,
    requiresLogin: false,
  },
  BRANCH_ARCHIVED: {
    message: "该会话已归档，不能继续发送消息。",
    retryable: false,
    requiresLogin: false,
  },
  MESSAGE_SEND_FORBIDDEN: {
    message: "当前状态下不能在该会话发送消息。",
    retryable: false,
    requiresLogin: false,
  },

  /* cases */
  TARGET_INVALID: {
    message: "举报对象不存在或已失效。",
    retryable: false,
    requiresLogin: false,
  },
  CASE_CLOSED: {
    message: "事项已结案，不能再操作。",
    retryable: false,
    requiresLogin: false,
  },
  NOT_CASE_PARTICIPANT: {
    message: "事项不存在，或你当前无权查看。",
    retryable: false,
    requiresLogin: false,
  },
  EVIDENCE_OUT_OF_SCOPE: {
    message: "证据文件不属于当前账户或用途不符。",
    retryable: false,
    requiresLogin: false,
  },
  CASE_APPEAL_WINDOW_ENDED: {
    message: "申辩期已结束，不能再提交申辩。",
    retryable: false,
    requiresLogin: false,
  },
  CASE_APPEAL_PENDING: {
    message: "存在待处理的申辩，事项暂不能结案。",
    retryable: false,
    requiresLogin: false,
  },
  CASE_APPEAL_WINDOW_OPEN: {
    message: "申辩期尚未届满，事项暂不能结案。",
    retryable: false,
    requiresLogin: false,
  },
};

const fallback: ProblemCopy = {
  message: "操作未能完成，请稍后重试。",
  retryable: true,
  requiresLogin: false,
};

/** Resolve the copy for one failure. */
export function describeProblem(error: unknown): ProblemCopy {
  if (error instanceof ApiError) {
    const known = copy[error.code];
    if (known) return known;
    // Server messages are only used when no reviewed copy exists, so wording
    // stays consistent for the codes the interface is expected to handle.
    if (error.status === 401) return copy.AUTHENTICATION_REQUIRED;
    if (error.status === 404) return copy.RESOURCE_NOT_VISIBLE;
    if (error.status === 409) return copy.STATE_CONFLICT;
    if (error.status === 422) return copy.INPUT_INVALID;
    if (error.status === 429) return copy.RATE_LIMITED;
    if (error.status >= 500) return copy.DEPENDENCY_UNAVAILABLE;
    return { ...fallback, message: error.message || fallback.message };
  }
  if (error instanceof Error && error.message) {
    return { ...fallback, message: error.message };
  }
  return fallback;
}

/** Convenience accessor used by views that only need the sentence. */
export function problemMessage(error: unknown): string {
  return describeProblem(error).message;
}

/** True when the failure means the current session can no longer be used. */
export function requiresLogin(error: unknown): boolean {
  return describeProblem(error).requiresLogin;
}
