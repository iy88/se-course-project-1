/* Copy for the administrative error codes the interface can act on. */
import { ApiError } from "../api/errors";

export interface ProblemCopy {
  message: string;
  retryable: boolean;
}

const copy: Record<string, ProblemCopy> = {
  AUTHENTICATION_REQUIRED: { message: "登录状态已失效，请重新登录。", retryable: false },
  CREDENTIALS_INVALID: { message: "邮箱或密码不正确。", retryable: false },
  ACTION_NOT_ALLOWED: { message: "当前账号不能执行该操作。", retryable: false },
  MANAGEMENT_NOT_ALLOWED: { message: "需要平台管理权限。", retryable: false },
  RESOURCE_NOT_VISIBLE: { message: "内容不存在，或当前账号无权查看。", retryable: false },
  CATEGORY_NAME_CONFLICT: { message: "该分类名称已被占用。", retryable: false },
  CATEGORY_NOT_DELETABLE: { message: "该分类曾关联商品，只能停用。", retryable: false },
  CATEGORY_NOT_SELECTABLE: { message: "所选分类当前不可用。", retryable: false },
  CATEGORY_APPLICATION_NOT_ALLOWED: { message: "当前分类申请不可修改。", retryable: false },
  REVIEW_NOT_PENDING: { message: "该审核已结束，不能重复提交结论。", retryable: false },
  REVIEW_ALREADY_CLAIMED: { message: "该事项已被其他管理员认领。", retryable: false },
  CASE_ALREADY_CLAIMED: { message: "该事项已被其他管理员认领。", retryable: false },
  CASE_CLOSED: { message: "该事项已结束。", retryable: false },
  REVIEW_CATEGORY_INSUFFICIENT: {
    message: "通过审核需要至少一个有效分类或批准分类申请。",
    retryable: false,
  },
  BANNED_SCOPE_INCOMPLETE: { message: "禁发范围至少保留一条细目。", retryable: false },
  STATE_CONFLICT: { message: "当前状态已变化，请刷新后重试。", retryable: true },
  INPUT_INVALID: { message: "填写内容无效，请检查后重试。", retryable: false },
  IDEMPOTENCY_PAYLOAD_CONFLICT: { message: "同一操作的内容已变化，请重新提交。", retryable: false },
  RATE_LIMITED: { message: "操作过于频繁，请稍后再试。", retryable: true },
  DEPENDENCY_UNAVAILABLE: { message: "依赖服务暂不可用，请稍后重试。", retryable: true },
  NETWORK_UNAVAILABLE: { message: "网络不可用，请检查连接后重试。", retryable: true },
  UNEXPECTED_RESPONSE: { message: "服务返回了无法识别的结果。", retryable: true },
};

export function describeProblem(error: unknown): ProblemCopy {
  if (error instanceof ApiError) {
    const known = copy[error.code];
    if (known) return known;
    if (error.status === 401) return copy.AUTHENTICATION_REQUIRED;
    if (error.status === 403) return copy.ACTION_NOT_ALLOWED;
    if (error.status === 404) return copy.RESOURCE_NOT_VISIBLE;
    if (error.status === 409) return copy.STATE_CONFLICT;
    if (error.status === 422) return copy.INPUT_INVALID;
    if (error.status === 429) return copy.RATE_LIMITED;
    if (error.status >= 500) return copy.DEPENDENCY_UNAVAILABLE;
    return { message: error.message, retryable: false };
  }
  return { message: "操作未能完成，请稍后重试。", retryable: true };
}

export function problemMessage(error: unknown): string {
  return describeProblem(error).message;
}
